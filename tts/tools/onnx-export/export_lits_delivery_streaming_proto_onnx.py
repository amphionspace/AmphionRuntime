#!/usr/bin/env python3
"""Export a prototype streaming ONNX package for local Android integration work."""

from __future__ import annotations

import argparse
import shutil
import json
import sys
import types
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LITS_ROOT = WORKSPACE_ROOT
DEFAULT_MODEL_ID = "lits_delivery_16k_hifigan_streaming_proto"
DEFAULT_VERSION = "0.1.0"
DEFAULT_MODEL_DIR = (
    WORKSPACE_ROOT
    / "tts"
    / "tools"
    / "trial-export"
    / DEFAULT_MODEL_ID
    / DEFAULT_VERSION
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lits-root", type=Path, default=DEFAULT_LITS_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_LITS_ROOT / "weights" / "lits" / "last.ckpt")
    parser.add_argument(
        "--hifigan-checkpoint",
        type=Path,
        default=DEFAULT_LITS_ROOT / "weights" / "hifigan" / "g_00130000",
    )
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--speaker-id", type=int, default=0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--hop-length", type=int, default=256)
    parser.add_argument("--mel-bins", type=int, default=80)
    parser.add_argument("--n-timesteps", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.667)
    parser.add_argument("--length-scale", type=float, default=1.0)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--pre-lookahead-len", type=int, default=3)
    parser.add_argument("--mel-cache-len", type=int, default=8)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--wav-subtype", default="PCM_24")
    return parser.parse_args()


def ensure_lits_imports(lits_root: Path) -> None:
    train_root = lits_root / "train"
    if str(train_root) not in sys.path:
        sys.path.insert(0, str(train_root))
    __import__("torch")
    __import__("onnxruntime")
    __import__("soundfile")


def install_monotonic_align_stub() -> bool:
    try:
        import lits.utils.monotonic_align.core  # type: ignore # noqa: F401

        return False
    except Exception:
        stub = types.ModuleType("lits.utils.monotonic_align.core")

        def _missing(*_args, **_kwargs):
            raise RuntimeError(
                "lits.utils.monotonic_align.core is unavailable in this export-only environment."
            )

        stub.maximum_path_c = _missing
        sys.modules["lits.utils.monotonic_align.core"] = stub
        return True


def read_vocab(vocab_path: Path) -> dict[str, int]:
    return json.loads(vocab_path.read_text(encoding="utf-8"))["vocab"]


def intersperse_zero(token_ids: list[int]) -> list[int]:
    if not token_ids:
        return []
    output = [0]
    for token_id in token_ids:
        output.append(token_id)
        output.append(0)
    return output


def smoke_inputs(lits_root: Path, speaker_id: int) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    smoke_phonemes = ["h", "ə", "l", "oʊ", "_", "w", "ɜː", "l", "d", "."]
    vocab = read_vocab(lits_root / "train" / "lits" / "text" / "g2p" / "vocab.json")
    token_ids = [int(vocab[item]) for item in smoke_phonemes]
    interspersed = intersperse_zero(token_ids)
    tokens = np.asarray([interspersed], dtype=np.int64)
    lengths = np.asarray([len(interspersed)], dtype=np.int64)
    speakers = np.asarray([speaker_id], dtype=np.int64)
    return smoke_phonemes, tokens, lengths, speakers


def load_model(args: argparse.Namespace):
    from lits.models.lits import LITS

    model = LITS.load_from_checkpoint(
        str(args.checkpoint),
        map_location=args.device,
        weights_only=False,
    )
    return model.eval().to(args.device)


def load_hifigan(args: argparse.Namespace):
    from lits.hifigan.config import v1
    from lits.hifigan.env import AttrDict
    from lits.hifigan.models import Generator as HiFiGAN

    config = dict(v1)
    config["sampling_rate"] = args.sample_rate
    config["hop_size"] = args.hop_length
    config["num_mels"] = args.mel_bins
    hparams = AttrDict(config)
    generator = HiFiGAN(hparams).to(args.device)
    state = torch.load(args.hifigan_checkpoint, map_location=args.device)
    generator.load_state_dict(state["generator"])
    generator.eval()
    generator.remove_weight_norm()
    return generator


def reset_rotary_caches(module: torch.nn.Module) -> None:
    for child in module.modules():
        if hasattr(child, "cos_cached"):
            child.cos_cached = None
        if hasattr(child, "sin_cached"):
            child.sin_cached = None


def export_onnx(*args, **kwargs) -> None:
    kwargs.setdefault("dynamo", False)
    torch.onnx.export(*args, **kwargs)


class HiddenEncoderWrapper(torch.nn.Module):
    def __init__(self, model, *, length_scale: float):
        super().__init__()
        self.model = model
        self.length_scale = length_scale

    def forward(self, token_ids, token_lengths, speaker_id):
        spks = None
        if getattr(self.model, "n_spks", 1) > 1:
            spks = speaker_id.long()
        hidden = self.model.get_hidden_mel(
            token_ids,
            token_lengths,
            spks=spks,
            length_scale=self.length_scale,
        )
        mel_length = hidden["y_mask"].sum(dim=2).to(dtype=torch.int64)
        speaker_embedding = hidden.get("spks")
        if speaker_embedding is None:
            speaker_embedding = torch.zeros(
                (token_ids.size(0), 0),
                dtype=torch.float32,
                device=token_ids.device,
            )
        return hidden["mu_y"], hidden["y_mask"], mel_length, speaker_embedding


class StreamDecoderWrapper(torch.nn.Module):
    def __init__(self, model, *, n_timesteps: int, temperature: float, finalize: bool):
        super().__init__()
        self.model = model
        self.n_timesteps = n_timesteps
        self.temperature = temperature
        self.finalize = finalize

    def forward(self, mu_y, y_mask, speaker_embedding):
        spks = speaker_embedding
        if spks.numel() == 0:
            spks = None
        mel = self.model.get_mel(
            mu_y=mu_y,
            y_mask=y_mask,
            spks=spks,
            n_timesteps=self.n_timesteps,
            temperature=self.temperature,
            finalize=self.finalize,
            streaming=True,
        )
        return mel


def export_hidden_encoder(
    args: argparse.Namespace,
    model,
    tokens_np: np.ndarray,
    lengths_np: np.ndarray,
    speakers_np: np.ndarray,
):
    wrapper = HiddenEncoderWrapper(model, length_scale=args.length_scale).eval()
    token_ids = torch.from_numpy(tokens_np).to(args.device)
    token_lengths = torch.from_numpy(lengths_np).to(args.device)
    speaker_id = torch.from_numpy(speakers_np).to(args.device)
    with torch.inference_mode():
        reset_rotary_caches(wrapper)
        reference = wrapper(token_ids, token_lengths, speaker_id)
    out_path = args.model_dir / "lits_hidden_encoder.onnx"
    reset_rotary_caches(wrapper)
    export_onnx(
        wrapper,
        (token_ids, token_lengths, speaker_id),
        str(out_path),
        input_names=["token_ids", "token_lengths", "speaker_id"],
        output_names=["mu_y", "y_mask", "mel_length", "speaker_embedding"],
        dynamic_axes={
            "token_ids": {1: "token_count"},
            "mu_y": {2: "mel_frames"},
            "y_mask": {2: "mel_frames"},
            "mel_length": {0: "batch_size"},
            "speaker_embedding": {0: "batch_size"},
        },
        opset_version=args.opset,
    )
    return out_path, reference


def export_stream_decoder(
    args: argparse.Namespace,
    model,
    reference_hidden: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
):
    mu_y, y_mask, mel_length, speaker_embedding = reference_hidden
    chunk_frames = min(int(mel_length[0].item()), args.chunk_size + args.pre_lookahead_len)
    final_frames = int(mel_length[0].item())

    if chunk_frames <= args.pre_lookahead_len:
        chunk_frames = final_frames

    mu_y_chunk = mu_y[:, :, :chunk_frames]
    y_mask_chunk = y_mask[:, :, : max(chunk_frames - args.pre_lookahead_len, 1)]
    mu_y_final = mu_y[:, :, :final_frames]
    y_mask_final = y_mask[:, :, :final_frames]

    chunk_wrapper = StreamDecoderWrapper(
        model,
        n_timesteps=args.n_timesteps,
        temperature=args.temperature,
        finalize=False,
    ).eval()
    final_wrapper = StreamDecoderWrapper(
        model,
        n_timesteps=args.n_timesteps,
        temperature=args.temperature,
        finalize=True,
    ).eval()

    with torch.inference_mode():
        reset_rotary_caches(chunk_wrapper)
        reference_chunk_mel = chunk_wrapper(mu_y_chunk, y_mask_chunk, speaker_embedding).detach()
        reset_rotary_caches(final_wrapper)
        reference_final_mel = final_wrapper(mu_y_final, y_mask_final, speaker_embedding).detach()

    chunk_path = args.model_dir / "lits_stream_decoder_chunk.onnx"
    final_path = args.model_dir / "lits_stream_decoder_final.onnx"
    reset_rotary_caches(chunk_wrapper)
    export_onnx(
        chunk_wrapper,
        (mu_y_chunk, y_mask_chunk, speaker_embedding),
        str(chunk_path),
        input_names=["mu_y", "y_mask", "speaker_embedding"],
        output_names=["mel"],
        dynamic_axes={
            "mu_y": {2: "mu_frames"},
            "y_mask": {2: "mask_frames"},
            "speaker_embedding": {0: "batch_size"},
            "mel": {2: "mel_frames"},
        },
        opset_version=args.opset,
    )
    reset_rotary_caches(final_wrapper)
    export_onnx(
        final_wrapper,
        (mu_y_final, y_mask_final, speaker_embedding),
        str(final_path),
        input_names=["mu_y", "y_mask", "speaker_embedding"],
        output_names=["mel"],
        dynamic_axes={
            "mu_y": {2: "mu_frames"},
            "y_mask": {2: "mask_frames"},
            "speaker_embedding": {0: "batch_size"},
            "mel": {2: "mel_frames"},
        },
        opset_version=args.opset,
    )
    return (
        chunk_path,
        final_path,
        (mu_y_chunk, y_mask_chunk, mu_y_final, y_mask_final, speaker_embedding),
        (reference_chunk_mel, reference_final_mel),
    )


def export_vocoder(args: argparse.Namespace, vocoder, reference_final_mel: torch.Tensor):
    out_path = args.model_dir / "hifigan_vocoder.onnx"
    export_mel = reference_final_mel.detach().clone()
    with torch.inference_mode():
        reference_waveform = vocoder(export_mel).detach().cpu().numpy().astype(np.float32)
    export_onnx(
        vocoder,
        (export_mel,),
        str(out_path),
        input_names=["mel"],
        output_names=["waveform"],
        dynamic_axes={
            "mel": {2: "mel_frames"},
            "waveform": {2: "audio_samples"},
        },
        opset_version=args.opset,
    )
    return out_path, reference_waveform


def validate_hidden_encoder(
    hidden_path: Path,
    inputs: tuple[np.ndarray, np.ndarray, np.ndarray],
    reference_hidden: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
) -> dict[str, object]:
    session = ort.InferenceSession(str(hidden_path), providers=["CPUExecutionProvider"])
    outputs = session.run(
        ["mu_y", "y_mask", "mel_length", "speaker_embedding"],
        {
            "token_ids": inputs[0],
            "token_lengths": inputs[1],
            "speaker_id": inputs[2],
        },
    )
    mu_y_ref, y_mask_ref, mel_length_ref, speaker_embedding_ref = reference_hidden
    mu_y = outputs[0].astype(np.float32)
    y_mask = outputs[1].astype(np.float32)
    mel_length = outputs[2].astype(np.int64)
    speaker_embedding = outputs[3].astype(np.float32)
    return {
        "mu_y_shape": list(mu_y.shape),
        "y_mask_shape": list(y_mask.shape),
        "mel_length": mel_length.tolist(),
        "speaker_embedding_shape": list(speaker_embedding.shape),
        "mu_y_max_abs": float(np.abs(mu_y - mu_y_ref.detach().cpu().numpy()).max()),
        "y_mask_max_abs": float(np.abs(y_mask - y_mask_ref.detach().cpu().numpy()).max()),
        "mel_length_match": bool(np.array_equal(mel_length, mel_length_ref.detach().cpu().numpy())),
        "speaker_embedding_max_abs": float(
            np.abs(speaker_embedding - speaker_embedding_ref.detach().cpu().numpy()).max()
        ),
    }


def validate_stream_decoder(
    chunk_path: Path,
    final_path: Path,
    decoder_inputs: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
    reference_decoder: tuple[torch.Tensor, torch.Tensor],
) -> tuple[dict[str, object], np.ndarray]:
    chunk_session = ort.InferenceSession(str(chunk_path), providers=["CPUExecutionProvider"])
    final_session = ort.InferenceSession(str(final_path), providers=["CPUExecutionProvider"])

    mu_y_chunk, y_mask_chunk, mu_y_final, y_mask_final, speaker_embedding = decoder_inputs
    reference_chunk_mel, reference_final_mel = reference_decoder

    chunk_mel = chunk_session.run(
        ["mel"],
        {
            "mu_y": mu_y_chunk.detach().cpu().numpy(),
            "y_mask": y_mask_chunk.detach().cpu().numpy(),
            "speaker_embedding": speaker_embedding.detach().cpu().numpy(),
        },
    )[0].astype(np.float32)
    final_mel = final_session.run(
        ["mel"],
        {
            "mu_y": mu_y_final.detach().cpu().numpy(),
            "y_mask": y_mask_final.detach().cpu().numpy(),
            "speaker_embedding": speaker_embedding.detach().cpu().numpy(),
        },
    )[0].astype(np.float32)

    return {
        "chunk_mel_shape": list(chunk_mel.shape),
        "final_mel_shape": list(final_mel.shape),
        "chunk_mel_repeat_run_max_abs": float(
            np.abs(
                chunk_session.run(
                    ["mel"],
                    {
                        "mu_y": mu_y_chunk.detach().cpu().numpy(),
                        "y_mask": y_mask_chunk.detach().cpu().numpy(),
                        "speaker_embedding": speaker_embedding.detach().cpu().numpy(),
                    },
                )[0].astype(np.float32)
                - chunk_mel
            ).max()
        ),
        "chunk_mel_reference_mean_abs": float(
            np.abs(chunk_mel - reference_chunk_mel.detach().cpu().numpy()).mean()
        ),
        "final_mel_repeat_run_max_abs": float(
            np.abs(
                final_session.run(
                    ["mel"],
                    {
                        "mu_y": mu_y_final.detach().cpu().numpy(),
                        "y_mask": y_mask_final.detach().cpu().numpy(),
                        "speaker_embedding": speaker_embedding.detach().cpu().numpy(),
                    },
                )[0].astype(np.float32)
                - final_mel
            ).max()
        ),
        "final_mel_reference_mean_abs": float(
            np.abs(final_mel - reference_final_mel.detach().cpu().numpy()).mean()
        ),
    }, final_mel


def validate_vocoder(
    vocoder_path: Path,
    final_mel: np.ndarray,
    reference_waveform: np.ndarray,
) -> tuple[dict[str, object], np.ndarray]:
    session = ort.InferenceSession(str(vocoder_path), providers=["CPUExecutionProvider"])
    waveform = session.run(["waveform"], {"mel": final_mel.astype(np.float32)})[0].astype(np.float32)
    waveform_1d = np.squeeze(waveform).astype(np.float32)
    return {
        "shape": list(waveform.shape),
        "reference_mean_abs": float(np.abs(waveform - reference_waveform).mean()),
        "waveform_min": float(waveform_1d.min()),
        "waveform_max": float(waveform_1d.max()),
        "waveform_rms": float(np.sqrt(np.mean(np.square(waveform_1d)))),
    }, np.clip(waveform_1d, -1.0, 1.0)


def write_manifest(
    args: argparse.Namespace,
    *,
    model,
    smoke_wav_path: Path,
    hidden_path: Path,
    chunk_path: Path,
    final_path: Path,
    vocoder_path: Path,
    frontend_paths: list[Path],
) -> Path:
    manifest = {
        "manifest_version": 1,
        "task": "tts",
        "model_id": args.model_id,
        "version": args.version,
        "model_type": "multilingual_lits_streaming_proto",
        "model_lang": "zh-en/en-US",
        "sample_rate": args.sample_rate,
        "mel_bins": args.mel_bins,
        "hop_length": args.hop_length,
        "speaker_count": int(getattr(model, "n_spks", 1)),
        "default_speaker_id": args.speaker_id,
        "supports_streaming": True,
        "default_language": "zh-en",
        "supported_languages": ["zh-en", "en-US"],
        "runtime_format": "onnx",
        "vocoder_type": "hifigan",
        "streaming_chunk_size": args.chunk_size,
        "streaming_pre_lookahead_len": args.pre_lookahead_len,
        "streaming_mel_cache_len": args.mel_cache_len,
        "hidden_encoder_model": {
            "file": hidden_path.name,
            "format": "onnx",
        },
        "stream_decoder_chunk_model": {
            "file": chunk_path.name,
            "format": "onnx",
        },
        "stream_decoder_final_model": {
            "file": final_path.name,
            "format": "onnx",
        },
        "vocoder_model": {
            "file": vocoder_path.name,
            "format": "onnx",
        },
        "notes": (
            "Prototype streaming export for Android integration. "
            "This package splits hidden encoder and stream decoder into separate ONNX assets."
        ),
        "files": [
            {"name": hidden_path.name, "size_bytes": hidden_path.stat().st_size},
            {"name": chunk_path.name, "size_bytes": chunk_path.stat().st_size},
            {"name": final_path.name, "size_bytes": final_path.stat().st_size},
            {"name": vocoder_path.name, "size_bytes": vocoder_path.stat().st_size},
            {"name": smoke_wav_path.name, "size_bytes": smoke_wav_path.stat().st_size},
        ] + [{"name": path.name, "size_bytes": path.stat().st_size} for path in frontend_paths],
    }
    out = args.model_dir / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def write_report(
    args: argparse.Namespace,
    *,
    smoke_phonemes: list[str],
    hidden_validation: dict[str, object],
    decoder_validation: dict[str, object],
    vocoder_validation: dict[str, object],
    stubbed_monotonic_align: bool,
) -> Path:
    out = args.model_dir / "export_report.json"
    payload = {
        "model_id": args.model_id,
        "version": args.version,
        "speaker_id": args.speaker_id,
        "chunk_size": args.chunk_size,
        "pre_lookahead_len": args.pre_lookahead_len,
        "mel_cache_len": args.mel_cache_len,
        "smoke_case": {
            "label": "hello world",
            "phonemes": smoke_phonemes,
        },
        "stubbed_monotonic_align_core": stubbed_monotonic_align,
        "validation": {
            "hidden_encoder": hidden_validation,
            "stream_decoder": decoder_validation,
            "vocoder": vocoder_validation,
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def copy_frontend_assets(args: argparse.Namespace) -> list[Path]:
    asset_root = (
        args.lits_root
        / "LitsTtsSdk"
        / "android"
        / "AmphionRuntime"
        / "sdk"
        / "src"
        / "main"
        / "assets"
        / "lits-models"
        / "tts"
        / "lits_delivery_16k_hifigan"
        / "1.0.0"
    )
    names = [
        "frontend_golden.json",
        "chinese_lexicon.txt",
        "cmudict.txt",
        "pinyin_2_bpmf.txt",
        "polychar.txt",
        "zh_en_symbols.json",
        "pinyin_to_tokens.json",
        "arpabet_to_tokens.json",
    ]
    outputs = []
    for name in names:
        source = asset_root / name
        target = args.model_dir / name
        shutil.copyfile(source, target)
        outputs.append(target)
    return outputs


def main() -> int:
    args = parse_args()
    args.lits_root = args.lits_root.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.hifigan_checkpoint = args.hifigan_checkpoint.resolve()
    args.model_dir = args.model_dir.resolve()
    args.model_dir.mkdir(parents=True, exist_ok=True)

    ensure_lits_imports(args.lits_root)
    stubbed_monotonic_align = install_monotonic_align_stub()

    model = load_model(args)
    vocoder = load_hifigan(args)
    smoke_phonemes, tokens_np, lengths_np, speakers_np = smoke_inputs(args.lits_root, args.speaker_id)

    hidden_path, reference_hidden = export_hidden_encoder(args, model, tokens_np, lengths_np, speakers_np)
    chunk_path, final_path, decoder_inputs, reference_decoder = export_stream_decoder(args, model, reference_hidden)
    vocoder_path, reference_waveform = export_vocoder(args, vocoder, reference_decoder[1])

    hidden_validation = validate_hidden_encoder(
        hidden_path,
        (tokens_np, lengths_np, speakers_np),
        reference_hidden,
    )
    decoder_validation, final_mel = validate_stream_decoder(
        chunk_path,
        final_path,
        decoder_inputs,
        reference_decoder,
    )
    vocoder_validation, waveform = validate_vocoder(vocoder_path, final_mel, reference_waveform)
    frontend_paths = copy_frontend_assets(args)

    smoke_wav_path = args.model_dir / "onnx_streaming_smoke_hello_world.wav"
    sf.write(str(smoke_wav_path), waveform, args.sample_rate, subtype=args.wav_subtype)

    manifest_path = write_manifest(
        args,
        model=model,
        smoke_wav_path=smoke_wav_path,
        hidden_path=hidden_path,
        chunk_path=chunk_path,
        final_path=final_path,
        vocoder_path=vocoder_path,
        frontend_paths=frontend_paths,
    )
    report_path = write_report(
        args,
        smoke_phonemes=smoke_phonemes,
        hidden_validation=hidden_validation,
        decoder_validation=decoder_validation,
        vocoder_validation=vocoder_validation,
        stubbed_monotonic_align=stubbed_monotonic_align,
    )

    print(f"model_dir={args.model_dir}")
    print(f"hidden_encoder_onnx={hidden_path}")
    print(f"stream_decoder_chunk_onnx={chunk_path}")
    print(f"stream_decoder_final_onnx={final_path}")
    print(f"vocoder_onnx={vocoder_path}")
    print(f"manifest={manifest_path}")
    print(f"report={report_path}")
    print(f"smoke_wav={smoke_wav_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
