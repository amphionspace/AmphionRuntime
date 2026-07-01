from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import sherpa_onnx

from .manifest import Manifest

LOG = logging.getLogger(__name__)


def normalize_model_type(raw: str) -> str:
    value = (raw or "").lower().replace("-", "_")
    if value in {"zipformer", "zipformer2", "transducer", ""}:
        return "transducer"
    if value == "paraformer":
        return "paraformer"
    if value in {"zipformer2_ctc", "ctc"}:
        return "zipformer2_ctc"
    if value in {"nemo_ctc", "nemo"}:
        return "nemo_ctc"
    return "transducer"


def _require(path: Path | None, label: str) -> str:
    if path is None or not path.is_file():
        raise FileNotFoundError(f"missing {label}: {path}")
    return str(path)


def build_recognizer(manifest: Manifest, *, provider: str, num_threads: int, debug: bool = False):
    files = manifest.files
    if files is None:
        raise ValueError("manifest.files is required")

    common: dict[str, Any] = {
        "tokens": _require(files.tokens, "tokens"),
        "num_threads": num_threads,
        "sample_rate": manifest.sample_rate,
        "feature_dim": manifest.feature_dim,
        "decoding_method": manifest.decoding_method,
        "max_active_paths": manifest.max_active_paths,
        "hotwords_score": manifest.hotwords_score,
        "provider": provider,
        "debug": debug,
    }
    if manifest.hotwords_file:
        common["hotwords_file"] = _require(manifest.hotwords_file, "hotwords_file")
    if manifest.rule_fsts:
        common["rule_fsts"] = ",".join(str(p) for p in manifest.rule_fsts)
    if manifest.lm_model:
        common["lm"] = _require(manifest.lm_model, "lm_model")
        common["lm_scale"] = manifest.lm_scale

    normalized = normalize_model_type(manifest.model_type)
    LOG.info(
        "loading recognizer model_id=%s version=%s model_type=%s provider=%s",
        manifest.model_id,
        manifest.version,
        manifest.model_type,
        provider,
    )

    if normalized == "transducer":
        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            encoder=_require(files.encoder, "encoder"),
            decoder=_require(files.decoder, "decoder"),
            joiner=_require(files.joiner, "joiner"),
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=20.0,
            model_type=manifest.model_type,
            **common,
        )
    elif normalized == "paraformer":
        recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            encoder=_require(files.paraformer_encoder, "paraformer_encoder"),
            decoder=_require(files.paraformer_decoder, "paraformer_decoder"),
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=20.0,
            **common,
        )
    elif normalized == "zipformer2_ctc":
        recognizer = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
            model=_require(files.zipformer2_ctc, "zipformer2_ctc"),
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=20.0,
            **common,
        )
    else:
        raise ValueError(f"unsupported online model_type: {manifest.model_type}")

    LOG.info("recognizer loaded sample_rate=%s feature_dim=%s", manifest.sample_rate, manifest.feature_dim)
    if provider == "cuda":
        LOG.warning("provider=cuda requested; verify CUDA EP with nvidia-smi on the target H20 host")
    return recognizer


def result_to_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, str):
        return {"text": result, "tokens": [], "timestamps": []}
    return {
        "text": getattr(result, "text", "") or "",
        "tokens": list(getattr(result, "tokens", []) or []),
        "timestamps": list(getattr(result, "timestamps", []) or []),
    }
