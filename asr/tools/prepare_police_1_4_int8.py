#!/usr/bin/env python3
"""Reproduce the Police 1.4.0 encoder-only INT8 delivery candidate.

Use the pinned Harmony ORT environment (requirements-harmony-ort.txt).
The upstream FP32 package is retained; this writes a new model directory.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

SOURCE_SHA256 = "cf59b5e889fd4eee8d4af3eb8a39e08f11f55b669c73a1d7a8094384fc8a5932"
ENCODER_SHA256 = "aae296f20c480333103e8b24e7c2466a26173f36f1a9750f236e70302576d691"
MODEL_ROOT = Path(__file__).resolve().parent / "demo-model"
MODEL_PREFIX = "amphion-zh-en-police-179m-1.4.0-chunk32-lc256-transducer-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=MODEL_ROOT / (MODEL_PREFIX + "fp32"))
    parser.add_argument("--output-dir", type=Path, default=MODEL_ROOT / (MODEL_PREFIX + "encoder-int8"))
    args = parser.parse_args()
    source = args.source_dir / "encoder.onnx"
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise SystemExit("Police 1.4.0 FP32 encoder SHA-256 mismatch")

    import numpy
    import onnx
    import onnxruntime
    from onnxruntime.quantization import QuantType, quantize_dynamic

    versions = {"onnxruntime": onnxruntime.__version__, "onnx": onnx.__version__, "numpy": numpy.__version__}
    if versions != {"onnxruntime": "1.16.3", "onnx": "1.15.0", "numpy": "1.26.4"}:
        raise SystemExit(f"Use requirements-harmony-ort.txt; found {versions}")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    encoder = args.output_dir / "encoder.int8.onnx"
    quantize_dynamic(
        str(source), str(encoder), op_types_to_quantize=["MatMul"],
        weight_type=QuantType.QInt8, per_channel=True, reduce_range=False,
        extra_options={"MatMulConstBOnly": True},
    )
    if hashlib.sha256(encoder.read_bytes()).hexdigest() != ENCODER_SHA256:
        raise SystemExit("Derived encoder SHA-256 mismatch; do not package this output")
    for name in ("decoder.onnx", "joiner.onnx", "tokens.txt", "bbpe.vocab"):
        shutil.copyfile(args.source_dir / name, args.output_dir / name)
    (args.output_dir / "quantization.json").write_text(json.dumps({
        "source_encoder_sha256": SOURCE_SHA256,
        "encoder_sha256": ENCODER_SHA256,
        "versions": versions,
        "weight_type": "QInt8", "op_types": ["MatMul"],
        "per_channel": True, "reduce_range": False, "MatMulConstBOnly": True,
        "decoder": "unchanged FP32", "joiner": "unchanged FP32",
    }, indent=2) + "\n")
    print(f"[OK] reproducible encoder-only INT8 model: {args.output_dir}")


if __name__ == "__main__":
    main()
