from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelFiles:
    tokens: Path
    encoder: Path | None = None
    decoder: Path | None = None
    joiner: Path | None = None
    zipformer2_ctc: Path | None = None
    paraformer_encoder: Path | None = None
    paraformer_decoder: Path | None = None


@dataclass(frozen=True)
class Manifest:
    model_id: str
    version: str
    lang: str
    model_type: str
    model_dir: Path
    sample_rate: int = 16000
    feature_dim: int = 80
    decoding_method: str = "greedy_search"
    max_active_paths: int = 4
    hotwords_file: Path | None = None
    hotwords_score: float = 1.5
    rule_fsts: list[Path] = field(default_factory=list)
    lm_model: Path | None = None
    lm_scale: float = 0.5
    files: ModelFiles | None = None


def _as_path(value: str | None, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else base / path


def _pick_first(base: Path, names: list[str]) -> Path | None:
    for name in names:
        path = base / name
        if path.is_file():
            return path
    return None


def _extract_model_dir(data: dict[str, Any], manifest_path: Path) -> Path:
    raw = data.get("model_dir")
    if raw:
        path = Path(str(raw))
        return path if path.is_absolute() else (manifest_path.parent / path).resolve()
    return manifest_path.parent.resolve()


def _resolve_files(data: dict[str, Any], model_dir: Path, prefer_fp32: bool) -> ModelFiles:
    # Keep the rules close to asr/server/src/recognizer_factory.cc, but let GPU
    # manifests prefer fp32 to avoid CUDA EP int8 fallbacks.
    encoder_names = (
        ["encoder.onnx", "encoder.fp16.onnx", "encoder.int8.onnx"]
        if prefer_fp32
        else ["encoder.int8.onnx", "encoder.onnx", "encoder.fp16.onnx"]
    )
    decoder_names = (
        ["decoder.onnx", "decoder.int8.onnx"]
        if prefer_fp32
        else ["decoder.onnx", "decoder.int8.onnx"]
    )
    joiner_names = (
        ["joiner.onnx", "joiner.fp16.onnx", "joiner.int8.onnx"]
        if prefer_fp32
        else ["joiner.int8.onnx", "joiner.onnx", "joiner.fp16.onnx"]
    )

    files_cfg = data.get("local_files") or {}
    return ModelFiles(
        tokens=_as_path(files_cfg.get("tokens"), model_dir)
        or _pick_first(model_dir, ["tokens.txt"])  # type: ignore[arg-type]
        or model_dir / "tokens.txt",
        encoder=_as_path(files_cfg.get("encoder"), model_dir) or _pick_first(model_dir, encoder_names),
        decoder=_as_path(files_cfg.get("decoder"), model_dir) or _pick_first(model_dir, decoder_names),
        joiner=_as_path(files_cfg.get("joiner"), model_dir) or _pick_first(model_dir, joiner_names),
        zipformer2_ctc=_as_path(files_cfg.get("zipformer2_ctc"), model_dir)
        or _pick_first(model_dir, ["model.int8.onnx", "model.onnx"]),
        paraformer_encoder=_as_path(files_cfg.get("paraformer_encoder"), model_dir)
        or _pick_first(model_dir, ["encoder.int8.onnx", "encoder.onnx"]),
        paraformer_decoder=_as_path(files_cfg.get("paraformer_decoder"), model_dir)
        or _pick_first(model_dir, ["decoder.int8.onnx", "decoder.onnx"]),
    )


def load_manifest(path: str | Path, *, prefer_fp32: bool = False) -> Manifest:
    manifest_path = Path(path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_dir = _extract_model_dir(data, manifest_path)
    rule_fsts = [_as_path(v, model_dir) for v in data.get("rule_fsts", [])]

    return Manifest(
        model_id=str(data.get("model_id", "unknown")),
        version=str(data.get("version", "unknown")),
        lang=str(data.get("lang", "")),
        model_type=str(data.get("model_type", "zipformer2")),
        model_dir=model_dir,
        sample_rate=int(data.get("sample_rate", 16000)),
        feature_dim=int(data.get("feature_dim", 80)),
        decoding_method=str(data.get("decoding_method", "greedy_search")),
        max_active_paths=int(data.get("max_active_paths", 4)),
        hotwords_file=_as_path(data.get("hotwords_file"), model_dir),
        hotwords_score=float(data.get("hotwords_score", 1.5)),
        rule_fsts=[p for p in rule_fsts if p is not None],
        lm_model=_as_path(data.get("lm_model"), model_dir),
        lm_scale=float(data.get("lm_scale", 0.5)),
        files=_resolve_files(data, model_dir, prefer_fp32=prefer_fp32),
    )
