#!/usr/bin/env python3
"""Shared Dingqiao LITS ONNX export helpers for Android SDK assets.

The external-loop exporter imports this module for model loading, raw-text
``en-zh-dict`` tokenization, hidden-encoder export, and ONNX validation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch


SDK_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SDK_ROOT.parent
DEFAULT_DINGQIAO_ROOT = WORKSPACE_ROOT / "dingqiao_lits"
DEFAULT_MODEL_ID = "dingqiao_lits_en_zh_vocos24k_streaming_proto"
DEFAULT_VERSION = "0.1.0"
DEFAULT_MODEL_DIR = SDK_ROOT / "tools" / "trial-export" / DEFAULT_MODEL_ID / DEFAULT_VERSION
DEFAULT_SMOKE_TEXT = "Hello world."
TONES = {"0": "˙", "5": "˙", "6": "ˊ", "1": "ˉ", "2": "ˊ", "3": "ˇ", "4": "ˋ"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dingqiao-root", type=Path, default=DEFAULT_DINGQIAO_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_DINGQIAO_ROOT / "lits-en-zh.ckpt")
    parser.add_argument(
        "--reference-checkpoint",
        type=Path,
        default=None,
        help="Lightning checkpoint used to instantiate a raw mean-flow student .pt payload.",
    )
    parser.add_argument("--hifigan-checkpoint", type=Path, default=DEFAULT_DINGQIAO_ROOT / "hifigan" / "hifigan.ckpt")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-lang", default="en-zh-dict", choices=["en-zh-dict", "en-zh"])
    parser.add_argument("--smoke-text", default=DEFAULT_SMOKE_TEXT)
    parser.add_argument("--speaker-id", type=int, default=0)
    parser.add_argument("--n-timesteps", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.667)
    parser.add_argument("--length-scale", type=float, default=1.0)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--pre-lookahead-len", type=int, default=3)
    parser.add_argument("--mel-cache-len", type=int, default=8)
    parser.add_argument("--num-decoding-left-chunks", type=int, default=1)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--wav-subtype", default="PCM_24")
    return parser.parse_args()


def ensure_imports(dingqiao_root: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(dingqiao_root / ".cache" / "matplotlib"))
    (dingqiao_root / ".cache" / "matplotlib").mkdir(parents=True, exist_ok=True)
    if str(dingqiao_root) not in sys.path:
        sys.path.insert(0, str(dingqiao_root))


def install_monotonic_align_stub() -> bool:
    try:
        import lits.utils.monotonic_align.core  # type: ignore # noqa: F401

        return False
    except Exception:
        stub = types.ModuleType("lits.utils.monotonic_align.core")

        def _missing(*_args, **_kwargs):
            raise RuntimeError("lits.utils.monotonic_align.core is unavailable in this export environment.")

        stub.maximum_path_c = _missing
        sys.modules["lits.utils.monotonic_align.core"] = stub
        return True


def reset_rotary_caches(module: torch.nn.Module) -> None:
    for child in module.modules():
        if hasattr(child, "cos_cached"):
            child.cos_cached = None
        if hasattr(child, "sin_cached"):
            child.sin_cached = None


def export_onnx(*args, **kwargs) -> None:
    kwargs.setdefault("dynamo", False)
    torch.onnx.export(*args, **kwargs)


def load_lits(
    checkpoint: Path,
    device: str,
    num_decoding_left_chunks: int,
    reference_checkpoint: Path | None = None,
):
    from lits.models.lits import LITS

    payload = torch.load(str(checkpoint), map_location="cpu", weights_only=False)
    is_raw_student = isinstance(payload, dict) and "state_dict" in payload and "pytorch-lightning_version" not in payload
    if is_raw_student:
        if reference_checkpoint is None:
            raise ValueError(
                "Raw mean-flow student checkpoints need --reference-checkpoint to provide the LITS architecture."
            )
        model = LITS.load_from_checkpoint(
            str(reference_checkpoint), map_location=device, weights_only=False
        ).eval().to(device)
        model.load_state_dict(payload["state_dict"], strict=True)
    else:
        model = LITS.load_from_checkpoint(str(checkpoint), map_location=device, weights_only=False).eval().to(device)
    if hasattr(model, "decoder") and hasattr(model.decoder, "num_decoding_left_chunks"):
        model.decoder.num_decoding_left_chunks = num_decoding_left_chunks
    return model


def load_hifigan(checkpoint: Path, device: str):
    from hifigan.env import AttrDict
    from hifigan.models import Generator

    config_path = checkpoint.parent / "config.json"
    hparams = AttrDict(json.loads(config_path.read_text(encoding="utf-8")))
    generator = Generator(hparams).to(device)
    state = torch.load(str(checkpoint), map_location=device, weights_only=False)
    generator.load_state_dict(state["generator"])
    generator.eval()
    generator.remove_weight_norm()
    return generator, hparams


def process_text(text: str, model_lang: str, device: str) -> tuple[np.ndarray, np.ndarray, str, list[int]]:
    from lits.text import text_to_sequence

    cleaner = "en_zh_dict_mixed_cleaners" if model_lang == "en-zh-dict" else "pinyin_direct_mixed_cleaners"
    token_ids, cleaned_text = text_to_sequence(text, [cleaner])
    if not token_ids:
        raise ValueError("smoke text produced an empty token sequence")
    tokens = np.asarray([token_ids], dtype=np.int64)
    lengths = np.asarray([len(token_ids)], dtype=np.int64)
    return tokens, lengths, cleaned_text, token_ids


class HiddenEncoderWrapper(torch.nn.Module):
    def __init__(self, model, *, length_scale: float):
        super().__init__()
        self.model = model
        self.length_scale = length_scale

    def forward(self, token_ids, token_lengths, speaker_id, length_scale):
        spks = speaker_id.long() if getattr(self.model, "n_spks", 1) > 1 else None
        clamped_length_scale = torch.clamp(length_scale.reshape(()).to(dtype=torch.float32), 0.5, 2.0)
        hidden = self.model.get_hidden_mel(token_ids, token_lengths, spks=spks, length_scale=clamped_length_scale)
        mel_length = hidden["y_mask"].sum(dim=2).to(dtype=torch.int64)
        speaker_embedding = hidden.get("spks")
        if speaker_embedding is None:
            speaker_embedding = torch.zeros((token_ids.size(0), 0), dtype=torch.float32, device=token_ids.device)
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
        return self.model.get_mel(
            mu_y=mu_y,
            y_mask=y_mask,
            spks=spks,
            n_timesteps=self.n_timesteps,
            temperature=self.temperature,
            finalize=self.finalize,
            streaming=True,
        )


def export_hidden_encoder(args: argparse.Namespace, model, tokens_np, lengths_np, speakers_np):
    wrapper = HiddenEncoderWrapper(model, length_scale=args.length_scale).eval()
    token_ids = torch.from_numpy(tokens_np).to(args.device)
    token_lengths = torch.from_numpy(lengths_np).to(args.device)
    speaker_id = torch.from_numpy(speakers_np).to(args.device)
    length_scale = torch.tensor([args.length_scale], dtype=torch.float32, device=args.device)
    with torch.inference_mode():
        reset_rotary_caches(wrapper)
        reference = wrapper(token_ids, token_lengths, speaker_id, length_scale)
    out_path = args.model_dir / "lits_hidden_encoder.onnx"
    reset_rotary_caches(wrapper)
    export_onnx(
        wrapper,
        (token_ids, token_lengths, speaker_id, length_scale),
        str(out_path),
        input_names=["token_ids", "token_lengths", "speaker_id", "length_scale"],
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


def export_stream_decoder(args: argparse.Namespace, model, reference_hidden):
    mu_y, y_mask, mel_length, speaker_embedding = reference_hidden
    frames = int(mel_length[0].item())
    chunk_frames = min(frames, args.chunk_size + args.pre_lookahead_len)
    final_frames = frames
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


def export_vocoder(args: argparse.Namespace, vocoder, reference_mel: torch.Tensor):
    out_path = args.model_dir / "hifigan_vocoder.onnx"
    export_mel = torch.from_numpy(reference_mel.detach().cpu().numpy()).to(args.device)
    with torch.inference_mode():
        reference_waveform = vocoder(export_mel).detach().cpu().numpy().astype(np.float32)
    export_onnx(
        vocoder,
        (export_mel,),
        str(out_path),
        input_names=["mel"],
        output_names=["waveform"],
        dynamic_axes={"mel": {2: "mel_frames"}, "waveform": {2: "audio_samples"}},
        opset_version=args.opset,
    )
    return out_path, reference_waveform


def validate_hidden(hidden_path: Path, inputs, reference_hidden) -> dict[str, object]:
    session = ort.InferenceSession(str(hidden_path), providers=["CPUExecutionProvider"])
    outputs = session.run(
        ["mu_y", "y_mask", "mel_length", "speaker_embedding"],
        {
            "token_ids": inputs[0],
            "token_lengths": inputs[1],
            "speaker_id": inputs[2],
            "length_scale": inputs[3],
        },
    )
    mu_y_ref, y_mask_ref, mel_length_ref, spk_ref = reference_hidden
    return {
        "mu_y_shape": list(outputs[0].shape),
        "y_mask_shape": list(outputs[1].shape),
        "mel_length": outputs[2].astype(np.int64).tolist(),
        "speaker_embedding_shape": list(outputs[3].shape),
        "mu_y_max_abs": float(np.abs(outputs[0] - mu_y_ref.detach().cpu().numpy()).max()),
        "y_mask_max_abs": float(np.abs(outputs[1] - y_mask_ref.detach().cpu().numpy()).max()),
        "mel_length_match": bool(np.array_equal(outputs[2], mel_length_ref.detach().cpu().numpy())),
        "speaker_embedding_max_abs": float(np.abs(outputs[3] - spk_ref.detach().cpu().numpy()).max()),
    }


def run_decoder_onnx(decoder_path: Path, mu_y: torch.Tensor, y_mask: torch.Tensor, speaker_embedding: torch.Tensor) -> np.ndarray:
    session = ort.InferenceSession(str(decoder_path), providers=["CPUExecutionProvider"])
    mel = session.run(
        ["mel"],
        {
            "mu_y": mu_y.detach().cpu().numpy(),
            "y_mask": y_mask.detach().cpu().numpy(),
            "speaker_embedding": speaker_embedding.detach().cpu().numpy(),
        },
    )[0].astype(np.float32)
    return mel


def validate_decoder(chunk_path: Path, final_path: Path, decoder_inputs, reference_decoder) -> tuple[dict[str, object], np.ndarray]:
    mu_y_chunk, y_mask_chunk, mu_y_final, y_mask_final, speaker_embedding = decoder_inputs
    reference_chunk_mel, reference_final_mel = reference_decoder
    chunk_mel = run_decoder_onnx(chunk_path, mu_y_chunk, y_mask_chunk, speaker_embedding)
    final_mel = run_decoder_onnx(final_path, mu_y_final, y_mask_final, speaker_embedding)
    return {
        "chunk_mel_shape": list(chunk_mel.shape),
        "chunk_mel_reference_mean_abs": float(np.abs(chunk_mel - reference_chunk_mel.detach().cpu().numpy()).mean()),
        "final_mel_shape": list(final_mel.shape),
        "final_mel_reference_mean_abs": float(np.abs(final_mel - reference_final_mel.detach().cpu().numpy()).mean()),
    }, final_mel


def validate_vocoder(vocoder_path: Path, mel: np.ndarray, reference_waveform: np.ndarray) -> tuple[dict[str, object], np.ndarray]:
    session = ort.InferenceSession(str(vocoder_path), providers=["CPUExecutionProvider"])
    waveform = session.run(["waveform"], {"mel": mel.astype(np.float32)})[0].astype(np.float32)
    squeezed = np.squeeze(waveform).astype(np.float32)
    return {
        "shape": list(waveform.shape),
        "reference_mean_abs": float(np.abs(waveform - reference_waveform).mean()),
        "waveform_min": float(squeezed.min()),
        "waveform_max": float(squeezed.max()),
        "waveform_rms": float(np.sqrt(np.mean(np.square(squeezed)))),
    }, np.clip(squeezed, -1.0, 1.0)


def generate_frontend_assets(dingqiao_root: Path, model_dir: Path) -> list[Path]:
    from lits.text import text_to_sequence
    from lits.text.char_symbols.symbol_inventories import lang2inventory

    sources = dingqiao_root / "lits" / "text" / "sources"
    outputs: list[Path] = []
    for name in ["chinese_lexicon.txt", "cmudict.txt", "pinyin_2_bpmf.txt"]:
        target = model_dir / name
        shutil.copyfile(sources / name, target)
        outputs.append(target)

    poly_source = sources / "g2p_chinese_model" / "polychar.txt"
    poly_target = model_dir / "polychar.txt"
    shutil.copyfile(poly_source if poly_source.is_file() else sources / "polychar.txt", poly_target)
    outputs.append(poly_target)

    symbols_path = model_dir / "zh_en_symbols.json"
    symbols_path.write_text(
        json.dumps({"symbols": lang2inventory["zh-en-direct"]["symbols"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    outputs.append(symbols_path)

    pinyin_map = {}
    pinyin_rows = {}
    for line in (sources / "pinyin_2_bpmf.txt").read_text(encoding="utf-8").splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 2:
            pinyin_rows[parts[0]] = list(parts[1])
    for base, bpmf in pinyin_rows.items():
        for tone, tone_token in TONES.items():
            pinyin_map[f"{base}{tone}"] = bpmf + [tone_token, "_"]

    pinyin_path = model_dir / "pinyin_to_tokens.json"
    pinyin_path.write_text(json.dumps({"pinyin_to_tokens": pinyin_map}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outputs.append(pinyin_path)

    arpabet_tokens = [token for token in lang2inventory["zh-en-direct"]["symbols"] if token.isupper() or any(ch.isdigit() for ch in token)]
    arpabet_path = model_dir / "arpabet_to_tokens.json"
    arpabet_path.write_text(
        json.dumps({"arpabet_to_tokens": {token: [token] for token in arpabet_tokens}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    outputs.append(arpabet_path)

    golden_cases = []
    for label, text in [
        ("hello_world", "Hello world."),
        ("zh_welcome", "你好，欢迎使用语音合成系统。"),
        ("english_digits", "Room 204 is ready."),
    ]:
        token_ids, cleaned_text = text_to_sequence(text, ["en_zh_dict_mixed_cleaners"])
        golden_cases.append(
            {
                "label": label,
                "text": text,
                "cleaned_text": cleaned_text,
                "token_ids": token_ids,
                "token_length": len(token_ids),
            }
        )
    golden_path = model_dir / "frontend_golden.json"
    golden_path.write_text(json.dumps({"cases": golden_cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outputs.append(golden_path)
    return outputs


def write_manifest(args: argparse.Namespace, *, model, hparams, hidden_path, decoder_path, final_decoder_path, vocoder_path, smoke_wav, frontend_paths):
    manifest = {
        "manifest_version": 1,
        "task": "tts",
        "model_id": args.model_id,
        "version": args.version,
        "model_type": "dingqiao_multilingual_lits_streaming_proto",
        "model_lang": "zh-en/en-US",
        "sample_rate": int(hparams.sampling_rate),
        "mel_bins": int(hparams.num_mels),
        "hop_length": int(hparams.hop_size),
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
        "num_decoding_left_chunks": args.num_decoding_left_chunks,
        "hidden_encoder_model": {"file": hidden_path.name, "format": "onnx"},
        "stream_decoder_chunk_model": {"file": decoder_path.name, "format": "onnx"},
        "stream_decoder_final_model": {"file": final_decoder_path.name, "format": "onnx"},
        "vocoder_model": {"file": vocoder_path.name, "format": "onnx"},
        "notes": "Dingqiao LITS en-zh checkpoint exported for Android streaming ONNX Runtime.",
        "files": [
            {"name": hidden_path.name, "size_bytes": hidden_path.stat().st_size},
            {"name": decoder_path.name, "size_bytes": decoder_path.stat().st_size},
            {"name": final_decoder_path.name, "size_bytes": final_decoder_path.stat().st_size},
            {"name": vocoder_path.name, "size_bytes": vocoder_path.stat().st_size},
            {"name": smoke_wav.name, "size_bytes": smoke_wav.stat().st_size},
        ] + [{"name": path.name, "size_bytes": path.stat().st_size} for path in frontend_paths],
    }
    out = args.model_dir / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    args = parse_args()
    args.dingqiao_root = args.dingqiao_root.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.hifigan_checkpoint = args.hifigan_checkpoint.resolve()
    args.model_dir = args.model_dir.resolve()
    args.model_dir.mkdir(parents=True, exist_ok=True)
    ensure_imports(args.dingqiao_root)
    stubbed_monotonic_align = install_monotonic_align_stub()

    model = load_lits(args.checkpoint, args.device, args.num_decoding_left_chunks)
    vocoder, hparams = load_hifigan(args.hifigan_checkpoint, args.device)
    tokens_np, lengths_np, cleaned_text, token_ids = process_text(args.smoke_text, args.model_lang, args.device)
    speakers_np = np.asarray([args.speaker_id], dtype=np.int64)
    if int(max(token_ids)) >= int(getattr(model, "n_vocab", 0)):
        raise ValueError(f"smoke token id exceeds n_vocab={model.n_vocab}: {max(token_ids)}")

    hidden_path, reference_hidden = export_hidden_encoder(args, model, tokens_np, lengths_np, speakers_np)
    decoder_path, final_decoder_path, decoder_inputs, reference_decoder = export_stream_decoder(args, model, reference_hidden)
    _, reference_final_mel = reference_decoder
    vocoder_path, reference_waveform = export_vocoder(args, vocoder, reference_final_mel)

    length_scale_np = np.asarray([args.length_scale], dtype=np.float32)
    hidden_validation = validate_hidden(hidden_path, (tokens_np, lengths_np, speakers_np, length_scale_np), reference_hidden)
    decoder_validation, mel = validate_decoder(decoder_path, final_decoder_path, decoder_inputs, reference_decoder)
    vocoder_validation, waveform = validate_vocoder(vocoder_path, mel, reference_waveform)
    frontend_paths = generate_frontend_assets(args.dingqiao_root, args.model_dir)

    smoke_wav = args.model_dir / "onnx_streaming_smoke_hello_world.wav"
    sf.write(str(smoke_wav), waveform, int(hparams.sampling_rate), subtype=args.wav_subtype)
    manifest_path = write_manifest(
        args,
        model=model,
        hparams=hparams,
        hidden_path=hidden_path,
        decoder_path=decoder_path,
        final_decoder_path=final_decoder_path,
        vocoder_path=vocoder_path,
        smoke_wav=smoke_wav,
        frontend_paths=frontend_paths,
    )
    report_path = args.model_dir / "export_report.json"
    report_path.write_text(
        json.dumps(
            {
                "model_id": args.model_id,
                "version": args.version,
                "checkpoint": str(args.checkpoint),
                "hifigan_checkpoint": str(args.hifigan_checkpoint),
                "smoke_text": args.smoke_text,
                "cleaned_text": cleaned_text,
                "token_ids": token_ids,
                "speaker_id": args.speaker_id,
                "chunk_size": args.chunk_size,
                "pre_lookahead_len": args.pre_lookahead_len,
                "mel_cache_len": args.mel_cache_len,
                "num_decoding_left_chunks": args.num_decoding_left_chunks,
                "stubbed_monotonic_align_core": stubbed_monotonic_align,
                "validation": {
                    "hidden_encoder": hidden_validation,
                    "stream_decoder": decoder_validation,
                    "vocoder": vocoder_validation,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"model_dir={args.model_dir}")
    print(f"hidden_encoder_onnx={hidden_path}")
    print(f"stream_decoder_chunk_onnx={decoder_path}")
    print(f"stream_decoder_final_onnx={final_decoder_path}")
    print(f"vocoder_onnx={vocoder_path}")
    print(f"manifest={manifest_path}")
    print(f"report={report_path}")
    print(f"smoke_wav={smoke_wav}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
