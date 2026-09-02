#!/usr/bin/env python3
"""Export experimental external-loop decoder ONNX assets for vocos24k.

This script intentionally does not modify the existing v2.4 export/runtime path.
It exports:

- lits_stream_condition_chunk.onnx: condition encoder for non-final chunks
- lits_stream_condition_final.onnx: condition encoder for final chunks
- lits_stream_decoder_step.onnx: one Euler flow step, intended to be called
  n_timesteps times by Android/HarmonyOS runtime code

The goal is to avoid the 10x static unroll in the decoder ONNX graph.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch


SDK_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SDK_ROOT.parent
DEFAULT_DINGQIAO_ROOT = WORKSPACE_ROOT / "tts" / "training" / "dingqiao_lits"
DEFAULT_MODEL_ID = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
DEFAULT_VERSION = "0.1.0"
DEFAULT_MODEL_DIR = SDK_ROOT / "tools" / "trial-export" / DEFAULT_MODEL_ID / DEFAULT_VERSION
DEFAULT_BASE_PACKAGE = (
    SDK_ROOT
    / "android"
    / "AmphionRuntime"
    / "sdk"
    / "src"
    / "main"
    / "assets"
    / "lits-models"
    / "tts"
    / "dingqiao_lits_en_zh_vocos24k_streaming_proto"
    / "0.1.0"
)


def _load_base_export_module():
    path = Path(__file__).with_name("export_dingqiao_lits_streaming_onnx.py")
    spec = importlib.util.spec_from_file_location("dingqiao_lits_streaming_base_export", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load base export module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base_export = _load_base_export_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dingqiao-root", type=Path, default=DEFAULT_DINGQIAO_ROOT)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_DINGQIAO_ROOT / "lits-en-zh.ckpt",
        help="LITS acoustic/decoder checkpoint. Do not pass vocos-24k/last.ckpt here; that is the vocoder checkpoint.",
    )
    parser.add_argument(
        "--reference-checkpoint",
        type=Path,
        default=None,
        help="Lightning LITS checkpoint used only when --checkpoint is a raw mean-flow student .pt payload.",
    )
    parser.add_argument("--base-package-dir", type=Path, default=DEFAULT_BASE_PACKAGE)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-lang", default="en-zh-dict", choices=["en-zh-dict", "en-zh"])
    parser.add_argument("--smoke-text", default="Hello world.")
    parser.add_argument("--speaker-id", type=int, default=0)
    parser.add_argument("--n-timesteps", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.667)
    parser.add_argument("--length-scale", type=float, default=1.0)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--pre-lookahead-len", type=int, default=3)
    parser.add_argument("--mel-cache-len", type=int, default=8)
    parser.add_argument("--num-decoding-left-chunks", type=int, default=1)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--seed", type=int, default=20260624)
    return parser.parse_args()


def reset_decoder_state(model: torch.nn.Module) -> None:
    base_export.reset_rotary_caches(model)
    decoder = getattr(model, "decoder", None)
    if hasattr(decoder, "reset_encoder_cache"):
        decoder.reset_encoder_cache()


def export_onnx(*args, **kwargs) -> None:
    kwargs.setdefault("dynamo", False)
    torch.onnx.export(*args, **kwargs)


class StreamConditionEncoderWrapper(torch.nn.Module):
    def __init__(self, model: torch.nn.Module, *, finalize: bool):
        super().__init__()
        self.model = model
        self.finalize = finalize

    def forward(self, mu_y: torch.Tensor, y_mask: torch.Tensor) -> torch.Tensor:
        encoded = self.model.decoder.encode_mu(
            mu_y,
            y_mask,
            finalize=self.finalize,
            streaming=True,
        )
        return encoded + y_mask.sum() * 0.0


class StreamDecoderStepWrapper(torch.nn.Module):
    def __init__(self, model: torch.nn.Module):
        super().__init__()
        self.model = model

    def forward(
        self,
        x: torch.Tensor,
        encoded_mu: torch.Tensor,
        y_mask: torch.Tensor,
        speaker_embedding: torch.Tensor,
        t: torch.Tensor,
        dt: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        spks = speaker_embedding
        if spks.numel() == 0:
            spks = None
        t_scalar = t.reshape(())
        dt_scalar = dt.reshape(())
        dphi_dt, _cache = self.model.decoder.estimator.forward_streaming(
            x,
            y_mask,
            encoded_mu,
            t_scalar,
            spks,
            None,
            step_cache=None,
        )
        x_next = x + dt_scalar * dphi_dt
        mel = x_next * self.model.mel_std + self.model.mel_mean
        return x_next, mel


@dataclass(frozen=True)
class DecoderCacheLayout:
    """Stable flat ONNX contract for one ODE step's decoder state."""

    att_count: int
    conv_count: int
    ds_count: int
    us_count: int

    @property
    def count(self) -> int:
        return self.att_count + self.conv_count + self.ds_count + self.us_count

    def names(self, prefix: str) -> list[str]:
        return (
            [f"{prefix}_att_{index}" for index in range(self.att_count)]
            + [f"{prefix}_conv_{index}" for index in range(self.conv_count)]
            + [f"{prefix}_ds_{index}" for index in range(self.ds_count)]
            + [f"{prefix}_us_{index}" for index in range(self.us_count)]
        )

    @classmethod
    def from_cache(cls, cache: dict) -> "DecoderCacheLayout":
        return cls(
            att_count=len(cache["att"]),
            conv_count=len(cache["conv"]),
            ds_count=len(cache["ds"]),
            us_count=len(cache["us"]),
        )

    def flatten(self, cache: dict) -> tuple[torch.Tensor, ...]:
        return tuple(cache["att"] + cache["conv"] + cache["ds"] + cache["us"])

    def inflate(self, tensors: tuple[torch.Tensor, ...]) -> dict:
        if len(tensors) != self.count:
            raise ValueError(f"decoder cache tensor count mismatch: {len(tensors)} != {self.count}")
        cursor = 0
        att = list(tensors[cursor:cursor + self.att_count]); cursor += self.att_count
        conv = list(tensors[cursor:cursor + self.conv_count]); cursor += self.conv_count
        ds = list(tensors[cursor:cursor + self.ds_count]); cursor += self.ds_count
        us = list(tensors[cursor:cursor + self.us_count])
        # Explicit ONNX cache state keeps only the bounded left window.  Offset
        # is intentionally absent; relative_cache_mode derives the same mask.
        return {"att": att, "att_offset": [0] * self.att_count, "conv": conv, "ds": ds, "us": us}


class StreamDecoderStepInitCacheWrapper(torch.nn.Module):
    """First chunk decoder step: create explicit cache tensors for Android."""

    def __init__(self, model: torch.nn.Module, cache_layout: DecoderCacheLayout):
        super().__init__()
        self.model = model
        self.cache_layout = cache_layout

    def forward(self, x, encoded_mu, y_mask, speaker_embedding, t, dt):
        spks = speaker_embedding
        if spks.numel() == 0:
            spks = None
        t_scalar = t.reshape(())
        dt_scalar = dt.reshape(())
        dphi_dt, cache = self.model.decoder.estimator.forward_streaming(
            x, y_mask, encoded_mu, t_scalar, spks, None, step_cache=None,
            relative_cache_mode=True,
        )
        x_next = x + dt_scalar * dphi_dt
        mel = x_next * self.model.mel_std + self.model.mel_mean
        return (x_next, mel, *self.cache_layout.flatten(cache))


class StreamDecoderStepCachedWrapper(torch.nn.Module):
    """Subsequent chunk decoder step with explicit ONNX state input/output."""

    def __init__(self, model: torch.nn.Module, cache_layout: DecoderCacheLayout):
        super().__init__()
        self.model = model
        self.cache_layout = cache_layout

    def forward(self, x, encoded_mu, y_mask, speaker_embedding, t, dt, *cache_tensors):
        spks = speaker_embedding
        if spks.numel() == 0:
            spks = None
        t_scalar = t.reshape(())
        dt_scalar = dt.reshape(())
        dphi_dt, cache = self.model.decoder.estimator.forward_streaming(
            x, y_mask, encoded_mu, t_scalar, spks, None,
            step_cache=self.cache_layout.inflate(cache_tensors),
            relative_cache_mode=True,
        )
        x_next = x + dt_scalar * dphi_dt
        mel = x_next * self.model.mel_std + self.model.mel_mean
        return (x_next, mel, *self.cache_layout.flatten(cache))


class FullDecoderWithNoiseWrapper(torch.nn.Module):
    def __init__(self, model: torch.nn.Module, *, n_timesteps: int, finalize: bool):
        super().__init__()
        self.model = model
        self.n_timesteps = n_timesteps
        self.finalize = finalize

    def forward(
        self,
        mu_y: torch.Tensor,
        y_mask: torch.Tensor,
        speaker_embedding: torch.Tensor,
        z: torch.Tensor,
    ) -> torch.Tensor:
        spks = speaker_embedding
        if spks.numel() == 0:
            spks = None
        return self.model.get_mel(
            mu_y=mu_y,
            y_mask=y_mask,
            spks=spks,
            n_timesteps=self.n_timesteps,
            temperature=1.0,
            finalize=self.finalize,
            streaming=True,
            z=z,
        )


def node_count(path: Path) -> int:
    return len(onnx.load(str(path)).graph.node)


def tensor_to_numpy(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().cpu().numpy().astype(np.float32)


def normal_tensor(tensor: torch.Tensor) -> torch.Tensor:
    """Clone inference-mode tensors into regular tensors usable by ONNX trace."""
    return tensor.detach().clone()


def make_decoder_inputs(args: argparse.Namespace, reference_hidden):
    mu_y, y_mask, mel_length, speaker_embedding = reference_hidden
    mu_y = normal_tensor(mu_y)
    y_mask = normal_tensor(y_mask)
    mel_length = normal_tensor(mel_length)
    speaker_embedding = normal_tensor(speaker_embedding)
    frames = int(mel_length[0].item())
    chunk_frames = min(frames, args.chunk_size + args.pre_lookahead_len)
    if chunk_frames <= args.pre_lookahead_len:
        chunk_frames = frames
    mu_y_chunk = mu_y[:, :, :chunk_frames]
    y_mask_chunk = y_mask[:, :, : max(chunk_frames - args.pre_lookahead_len, 1)]
    mu_y_final = mu_y[:, :, :frames]
    y_mask_final = y_mask[:, :, :frames]
    return mu_y_chunk, y_mask_chunk, mu_y_final, y_mask_final, speaker_embedding


def make_noise_like(mu: torch.Tensor, temperature: float, seed: int) -> torch.Tensor:
    generator = torch.Generator(device=mu.device)
    generator.manual_seed(seed)
    return torch.randn(mu.shape, generator=generator, device=mu.device, dtype=mu.dtype) * temperature


def export_condition_encoder(
    args: argparse.Namespace,
    model: torch.nn.Module,
    mu_y: torch.Tensor,
    y_mask: torch.Tensor,
    *,
    finalize: bool,
    out_name: str,
) -> tuple[Path, torch.Tensor]:
    wrapper = StreamConditionEncoderWrapper(model, finalize=finalize).eval()
    reset_decoder_state(model)
    with torch.inference_mode():
        encoded = normal_tensor(wrapper(mu_y, y_mask))
    out_path = args.model_dir / out_name
    reset_decoder_state(model)
    export_onnx(
        wrapper,
        (mu_y, y_mask),
        str(out_path),
        input_names=["mu_y", "y_mask"],
        output_names=["encoded_mu"],
        dynamic_axes={
            "mu_y": {2: "mu_frames"},
            "y_mask": {2: "mask_frames"},
            "encoded_mu": {2: "mel_frames"},
        },
        opset_version=args.opset,
    )
    return out_path, encoded


def export_decoder_step(
    args: argparse.Namespace,
    model: torch.nn.Module,
    encoded_mu: torch.Tensor,
    y_mask: torch.Tensor,
    speaker_embedding: torch.Tensor,
) -> Path:
    wrapper = StreamDecoderStepWrapper(model).eval()
    x = torch.zeros_like(encoded_mu)
    t = torch.tensor([0.0], dtype=torch.float32, device=encoded_mu.device)
    dt = torch.tensor([1.0 / args.n_timesteps], dtype=torch.float32, device=encoded_mu.device)
    out_path = args.model_dir / "lits_stream_decoder_step.onnx"
    reset_decoder_state(model)
    export_onnx(
        wrapper,
        (x, encoded_mu, y_mask, speaker_embedding, t, dt),
        str(out_path),
        input_names=["x", "encoded_mu", "y_mask", "speaker_embedding", "t", "dt"],
        output_names=["x_next", "mel"],
        dynamic_axes={
            "x": {2: "mel_frames"},
            "encoded_mu": {2: "mel_frames"},
            "y_mask": {2: "mel_frames"},
            "speaker_embedding": {0: "batch_size"},
            "x_next": {2: "mel_frames"},
            "mel": {2: "mel_frames"},
        },
        opset_version=args.opset,
    )
    return out_path


def export_decoder_step_cache_models(
    args: argparse.Namespace,
    model: torch.nn.Module,
    encoded_mu: torch.Tensor,
    y_mask: torch.Tensor,
    speaker_embedding: torch.Tensor,
) -> tuple[Path, Path, DecoderCacheLayout]:
    """Export first-chunk and cached decoder-step graphs.

    The cache graphs are intentionally additional assets.  The existing
    ``lits_stream_decoder_step.onnx`` remains the compatibility fallback for
    packages and runtimes that do not opt into the explicit state contract.
    """
    x = torch.zeros_like(encoded_mu)
    t = torch.tensor([0.0], dtype=torch.float32, device=encoded_mu.device)
    dt = torch.tensor([1.0 / args.n_timesteps], dtype=torch.float32, device=encoded_mu.device)
    with torch.inference_mode():
        _, cache = model.decoder.estimator.forward_streaming(
            x, y_mask, encoded_mu, t.reshape(()), speaker_embedding, None,
            step_cache=None, relative_cache_mode=True,
        )
    layout = DecoderCacheLayout.from_cache(cache)
    init_wrapper = StreamDecoderStepInitCacheWrapper(model, layout).eval()
    cached_wrapper = StreamDecoderStepCachedWrapper(model, layout).eval()
    cache_tensors = tuple(tensor.detach().clone() for tensor in layout.flatten(cache))
    input_names = ["x", "encoded_mu", "y_mask", "speaker_embedding", "t", "dt"]
    output_names = ["x_next", "mel"]
    base_dynamic_axes = {
        "x": {2: "mel_frames"},
        "encoded_mu": {2: "mel_frames"},
        "y_mask": {2: "mel_frames"},
        "speaker_embedding": {0: "batch_size"},
        "x_next": {2: "mel_frames"},
        "mel": {2: "mel_frames"},
    }
    init_dynamic_axes = dict(base_dynamic_axes)
    cached_dynamic_axes = dict(base_dynamic_axes)
    for name, tensor in zip(layout.names("cache"), cache_tensors):
        # Attention caches vary along time.  Other state buffers have a fixed
        # tail size, but dynamic time is harmless and keeps the ABI uniform.
        cached_dynamic_axes[name] = {2: f"{name}_frames"} if tensor.ndim >= 3 else {}
    for name, tensor in zip(layout.names("next_cache"), cache_tensors):
        init_dynamic_axes[name] = {2: f"{name}_frames"} if tensor.ndim >= 3 else {}
        cached_dynamic_axes[name] = {2: f"{name}_frames"} if tensor.ndim >= 3 else {}

    init_path = args.model_dir / "lits_stream_decoder_step_init_cache.onnx"
    cached_path = args.model_dir / "lits_stream_decoder_step_cached.onnx"
    export_onnx(
        init_wrapper,
        (x, encoded_mu, y_mask, speaker_embedding, t, dt),
        str(init_path),
        input_names=input_names,
        output_names=output_names + layout.names("next_cache"),
        dynamic_axes=init_dynamic_axes,
        opset_version=args.opset,
    )
    export_onnx(
        cached_wrapper,
        (x, encoded_mu, y_mask, speaker_embedding, t, dt, *cache_tensors),
        str(cached_path),
        input_names=input_names + layout.names("cache"),
        output_names=output_names + layout.names("next_cache"),
        dynamic_axes=cached_dynamic_axes,
        opset_version=args.opset,
    )
    return init_path, cached_path, layout


def run_external_loop(
    condition_path: Path,
    step_path: Path,
    mu_y: torch.Tensor,
    y_mask: torch.Tensor,
    speaker_embedding: torch.Tensor,
    z: torch.Tensor,
    n_timesteps: int,
) -> np.ndarray:
    providers = ["CPUExecutionProvider"]
    condition_session = ort.InferenceSession(str(condition_path), providers=providers)
    step_session = ort.InferenceSession(str(step_path), providers=providers)
    encoded_mu = condition_session.run(
        ["encoded_mu"],
        {"mu_y": tensor_to_numpy(mu_y), "y_mask": tensor_to_numpy(y_mask)},
    )[0].astype(np.float32)
    x = tensor_to_numpy(z[:, :, : encoded_mu.shape[2]])
    mask = tensor_to_numpy(y_mask)
    speaker = tensor_to_numpy(speaker_embedding)
    mel = None
    for step in range(n_timesteps):
        t = np.asarray([step / n_timesteps], dtype=np.float32)
        dt = np.asarray([1.0 / n_timesteps], dtype=np.float32)
        x, mel = step_session.run(
            ["x_next", "mel"],
            {
                "x": x,
                "encoded_mu": encoded_mu,
                "y_mask": mask,
                "speaker_embedding": speaker,
                "t": t,
                "dt": dt,
            },
        )
        x = x.astype(np.float32)
        mel = mel.astype(np.float32)
    if mel is None:
        raise RuntimeError("external loop did not run")
    return mel


def reference_full_decoder(
    model: torch.nn.Module,
    mu_y: torch.Tensor,
    y_mask: torch.Tensor,
    speaker_embedding: torch.Tensor,
    z: torch.Tensor,
    *,
    n_timesteps: int,
    finalize: bool,
) -> np.ndarray:
    wrapper = FullDecoderWithNoiseWrapper(model, n_timesteps=n_timesteps, finalize=finalize).eval()
    reset_decoder_state(model)
    with torch.inference_mode():
        return tensor_to_numpy(wrapper(mu_y, y_mask, speaker_embedding, z))


def diff_metrics(left: np.ndarray, right: np.ndarray) -> dict[str, object]:
    common = min(left.shape[2], right.shape[2])
    diff = left[:, :, :common] - right[:, :, :common]
    return {
        "left_shape": list(left.shape),
        "right_shape": list(right.shape),
        "common_frames": int(common),
        "mean_abs": float(np.mean(np.abs(diff))),
        "max_abs": float(np.max(np.abs(diff))),
        "rms": float(np.sqrt(np.mean(diff * diff))),
    }


def copy_base_runtime_assets(base_package_dir: Path, model_dir: Path) -> list[Path]:
    names = [
        "vocos_vocoder.onnx",
        "vocos_vocoder.export_report.json",
        "frontend_golden.json",
        "chinese_lexicon.txt",
        "chinese_lexicon.bin",
        "cmudict.txt",
        "cmudict.bin",
        "pinyin_2_bpmf.txt",
        "polychar.txt",
        "zh_en_symbols.json",
        "pinyin_to_tokens.json",
        "arpabet_to_tokens.json",
    ]
    outputs = []
    for name in names:
        source = base_package_dir / name
        if not source.is_file():
            continue
        target = model_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        outputs.append(target)
    return outputs


def write_manifest(
    args: argparse.Namespace,
    *,
    model: torch.nn.Module,
    hidden_path: Path,
    condition_chunk_path: Path,
    condition_final_path: Path,
    step_path: Path,
    cache_init_path: Path | None,
    cache_step_path: Path | None,
    cache_layout: DecoderCacheLayout | None,
    copied_assets: list[Path],
) -> Path:
    base_manifest = json.loads((args.base_package_dir / "manifest.json").read_text(encoding="utf-8"))
    vocoder_file = base_manifest["vocoder_model"]["file"]
    manifest = dict(base_manifest)
    manifest.pop("stream_decoder_chunk_model", None)
    manifest.pop("stream_decoder_final_model", None)
    manifest.update(
        {
            "model_id": args.model_id,
            "version": args.version,
            "speaker_count": int(getattr(model, "n_spks", 1)),
            "default_speaker_id": args.speaker_id,
            "streaming_chunk_size": args.chunk_size,
            "streaming_pre_lookahead_len": args.pre_lookahead_len,
            "streaming_mel_cache_len": args.mel_cache_len,
            "num_decoding_left_chunks": args.num_decoding_left_chunks,
            "stream_decoder_external_loop": True,
            "stream_decoder_n_timesteps": args.n_timesteps,
            "stream_decoder_temperature": args.temperature,
            "hidden_encoder_model": {"file": hidden_path.name, "format": "onnx"},
            "stream_condition_chunk_model": {"file": condition_chunk_path.name, "format": "onnx"},
            "stream_condition_final_model": {"file": condition_final_path.name, "format": "onnx"},
            "stream_decoder_step_model": {"file": step_path.name, "format": "onnx"},
            "vocoder_model": {"file": vocoder_file, "format": "onnx"},
            "notes": "Experimental external-loop decoder package for Android/HarmonyOS validation.",
        }
    )
    if cache_init_path is not None and cache_step_path is not None and cache_layout is not None:
        manifest["stream_decoder_cache"] = {
            "init_model": {"file": cache_init_path.name, "format": "onnx"},
            "step_model": {"file": cache_step_path.name, "format": "onnx"},
            "state_count": cache_layout.count,
            "state_names": cache_layout.names("cache"),
            "mode": "relative_left_window_v1",
            "requires_fixed_chunk_size": args.chunk_size,
        }
    files = [
        hidden_path,
        condition_chunk_path,
        condition_final_path,
        step_path,
    ] + copied_assets
    if cache_init_path is not None and cache_step_path is not None:
        files.extend([cache_init_path, cache_step_path])
    manifest["files"] = [{"name": path.name, "size_bytes": path.stat().st_size} for path in files]
    out = args.model_dir / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    args = parse_args()
    args.dingqiao_root = args.dingqiao_root.resolve()
    args.checkpoint = args.checkpoint.resolve()
    if args.reference_checkpoint is not None:
        args.reference_checkpoint = args.reference_checkpoint.resolve()
    args.base_package_dir = args.base_package_dir.resolve()
    args.model_dir = args.model_dir.resolve()
    args.model_dir.mkdir(parents=True, exist_ok=True)

    if not (args.base_package_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"base package manifest not found: {args.base_package_dir / 'manifest.json'}")

    base_export.ensure_imports(args.dingqiao_root)
    stubbed_monotonic_align = base_export.install_monotonic_align_stub()

    model = base_export.load_lits(
        args.checkpoint,
        args.device,
        args.num_decoding_left_chunks,
        args.reference_checkpoint,
    )
    tokens_np, lengths_np, cleaned_text, token_ids = base_export.process_text(args.smoke_text, args.model_lang, args.device)
    speakers_np = np.asarray([args.speaker_id], dtype=np.int64)

    hidden_path, reference_hidden = base_export.export_hidden_encoder(args, model, tokens_np, lengths_np, speakers_np)
    length_scale_np = np.asarray([args.length_scale], dtype=np.float32)
    hidden_validation = base_export.validate_hidden(
        hidden_path,
        (tokens_np, lengths_np, speakers_np, length_scale_np),
        reference_hidden,
    )
    decoder_inputs = make_decoder_inputs(args, reference_hidden)
    mu_y_chunk, y_mask_chunk, mu_y_final, y_mask_final, speaker_embedding = decoder_inputs

    condition_chunk_path, encoded_chunk = export_condition_encoder(
        args,
        model,
        mu_y_chunk,
        y_mask_chunk,
        finalize=False,
        out_name="lits_stream_condition_chunk.onnx",
    )
    condition_final_path, encoded_final = export_condition_encoder(
        args,
        model,
        mu_y_final,
        y_mask_final,
        finalize=True,
        out_name="lits_stream_condition_final.onnx",
    )
    step_path = export_decoder_step(args, model, encoded_chunk, y_mask_chunk, speaker_embedding)
    cache_init_path, cache_step_path, cache_layout = export_decoder_step_cache_models(
        args, model, encoded_chunk, y_mask_chunk, speaker_embedding,
    )

    z_chunk = make_noise_like(encoded_chunk, args.temperature, args.seed)
    z_final = make_noise_like(encoded_final, args.temperature, args.seed)
    reference_chunk = reference_full_decoder(
        model,
        mu_y_chunk,
        y_mask_chunk,
        speaker_embedding,
        z_chunk,
        n_timesteps=args.n_timesteps,
        finalize=False,
    )
    reference_final = reference_full_decoder(
        model,
        mu_y_final,
        y_mask_final,
        speaker_embedding,
        z_final,
        n_timesteps=args.n_timesteps,
        finalize=True,
    )
    external_chunk = run_external_loop(
        condition_chunk_path,
        step_path,
        mu_y_chunk,
        y_mask_chunk,
        speaker_embedding,
        z_chunk,
        args.n_timesteps,
    )
    external_final = run_external_loop(
        condition_final_path,
        step_path,
        mu_y_final,
        y_mask_final,
        speaker_embedding,
        z_final,
        args.n_timesteps,
    )

    copied_assets = copy_base_runtime_assets(args.base_package_dir, args.model_dir)
    manifest_path = write_manifest(
        args,
        model=model,
        hidden_path=hidden_path,
        condition_chunk_path=condition_chunk_path,
        condition_final_path=condition_final_path,
        step_path=step_path,
        cache_init_path=cache_init_path,
        cache_step_path=cache_step_path,
        cache_layout=cache_layout,
        copied_assets=copied_assets,
    )
    report = {
        "model_id": args.model_id,
        "version": args.version,
        "smoke_text": args.smoke_text,
        "cleaned_text": cleaned_text,
        "token_ids": token_ids,
        "stubbed_monotonic_align_core": stubbed_monotonic_align,
        "external_loop": {
            "n_timesteps": args.n_timesteps,
            "temperature": args.temperature,
            "seed": args.seed,
            "assets": {
                "condition_chunk": {
                    "path": condition_chunk_path.name,
                    "size_bytes": condition_chunk_path.stat().st_size,
                    "node_count": node_count(condition_chunk_path),
                },
                "condition_final": {
                    "path": condition_final_path.name,
                    "size_bytes": condition_final_path.stat().st_size,
                    "node_count": node_count(condition_final_path),
                },
                "decoder_step": {
                    "path": step_path.name,
                    "size_bytes": step_path.stat().st_size,
                    "node_count": node_count(step_path),
                },
                "decoder_cache": {
                    "init_path": cache_init_path.name,
                    "step_path": cache_step_path.name,
                    "state_count": cache_layout.count,
                },
            },
        },
        "validation": {
            "hidden_encoder": hidden_validation,
            "chunk_external_vs_full": diff_metrics(external_chunk, reference_chunk),
            "final_external_vs_full": diff_metrics(external_final, reference_final),
        },
    }
    report_path = args.model_dir / "external_loop_export_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"model_dir={args.model_dir}")
    print(f"manifest={manifest_path}")
    print(f"report={report_path}")
    print(f"condition_chunk={condition_chunk_path} nodes={node_count(condition_chunk_path)}")
    print(f"condition_final={condition_final_path} nodes={node_count(condition_final_path)}")
    print(f"decoder_step={step_path} nodes={node_count(step_path)}")
    print(f"chunk_external_vs_full={report['validation']['chunk_external_vs_full']}")
    print(f"final_external_vs_full={report['validation']['final_external_vs_full']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
