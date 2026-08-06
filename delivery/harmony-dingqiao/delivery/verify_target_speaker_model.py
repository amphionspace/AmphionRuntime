#!/usr/bin/env python3
"""Verify the formal Harmony target-speaker ORT asset and its conversion provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_CONVERTER = "onnxruntime-1.16.3-fixed-arm-cpu-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(model: Path, metadata_path: Path) -> dict[str, object]:
    if not model.is_file() or model.stat().st_size == 0:
        raise ValueError(f"missing target-speaker ORT model: {model}")
    if model.suffix != ".ort":
        raise ValueError(f"target-speaker model must use ORT format: {model}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid target-speaker conversion metadata: {error}") from error
    if metadata.get("format") != "ort":
        raise ValueError("target-speaker conversion metadata format must be ort")
    if metadata.get("converter_id") != EXPECTED_CONVERTER:
        raise ValueError("target-speaker model was not converted with Harmony ORT 1.16.3")
    if metadata.get("output_size_bytes") != model.stat().st_size:
        raise ValueError("target-speaker model size differs from conversion metadata")
    if metadata.get("output_sha256") != sha256_file(model):
        raise ValueError("target-speaker model SHA-256 differs from conversion metadata")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    try:
        metadata = verify(args.model, args.metadata)
    except ValueError as error:
        print(f"[ERROR] {error}")
        return 1
    print(
        "[OK] verified target-speaker ORT "
        f"sha256={metadata['output_sha256']} size={metadata['output_size_bytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
