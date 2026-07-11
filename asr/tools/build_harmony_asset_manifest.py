#!/usr/bin/env python3
"""Build the Harmony model asset manifest from staged files and source metadata."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from convert_harmony_ort import CONVERTER_CONFIG, CONVERTER_ID, sha256_file


HARMONY_BUNDLES = {
    "zh-en/v1": [
        "encoder.int8.ort",
        "decoder.int8.ort",
        "joiner.int8.ort",
        "tokens.txt",
        "bbpe.vocab",
    ],
    "yue-en/v1": [
        "encoder.int8.onnx",
        "decoder.onnx",
        "joiner.int8.onnx",
        "tokens.txt",
        "bbpe.vocab",
    ],
    "punct-zhen/v1": ["model.int8.ort"],
    "itn-zh/v1": ["zh_itn_tagger.fst", "zh_itn_verbalizer.fst"],
    "vad/v1": ["silero_vad.onnx"],
}


def file_format(name: str) -> str:
    suffix = Path(name).suffix.lower()
    formats = {
        ".ort": "ort",
        ".onnx": "onnx",
        ".fst": "fst",
        ".txt": "text",
        ".vocab": "text",
    }
    try:
        return formats[suffix]
    except KeyError as error:
        raise ValueError(f"unsupported model asset format: {name}") from error


def parse_mapping(value: str) -> tuple[str, Path]:
    target, separator, source = value.partition("=")
    if not separator or not target or not source:
        raise argparse.ArgumentTypeError("mapping must be TARGET=SOURCE")
    return target, Path(source)


def _atomic_write_json(payload: dict[str, Any], destination: Path) -> None:
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def build_manifest(
    root: Path,
    copied_sources: dict[str, Path],
    converted_metadata: dict[str, Path],
) -> dict[str, Any]:
    expected_targets = {
        f"{bundle}/{name}" for bundle, names in HARMONY_BUNDLES.items() for name in names
    }
    provided_targets = set(copied_sources) | set(converted_metadata)
    if provided_targets != expected_targets:
        missing = sorted(expected_targets - provided_targets)
        extra = sorted(provided_targets - expected_targets)
        raise ValueError(f"manifest input mismatch: missing={missing} extra={extra}")
    overlap = set(copied_sources) & set(converted_metadata)
    if overlap:
        raise ValueError(f"manifest targets provided twice: {sorted(overlap)}")

    bundles: dict[str, list[dict[str, Any]]] = {}
    for bundle, names in HARMONY_BUNDLES.items():
        entries: list[dict[str, Any]] = []
        for name in names:
            target = f"{bundle}/{name}"
            output_path = root / target
            if not output_path.is_file():
                raise FileNotFoundError(f"missing staged asset: {output_path}")
            output_sha256 = sha256_file(output_path)
            output_size = output_path.stat().st_size

            if target in converted_metadata:
                metadata_path = converted_metadata[target]
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    raise ValueError(f"conversion metadata must be an object for {target}")
                if metadata.get("converter_id") != CONVERTER_ID:
                    raise ValueError(f"unexpected converter for {target}")
                if metadata.get("converter") != CONVERTER_CONFIG:
                    raise ValueError(f"converter configuration mismatch for {target}")
                if metadata.get("format") != "ort":
                    raise ValueError(f"unexpected converted format for {target}")
                if metadata.get("output_sha256") != output_sha256:
                    raise ValueError(f"converted output hash mismatch for {target}")
                if metadata.get("output_size_bytes") != output_size:
                    raise ValueError(f"converted output size mismatch for {target}")
                source_name = metadata.get("source_name")
                source_sha256 = metadata.get("source_sha256")
                converter = CONVERTER_ID
            else:
                source_path = copied_sources[target]
                if not source_path.is_file():
                    raise FileNotFoundError(f"missing source asset: {source_path}")
                source_name = source_path.name
                source_sha256 = sha256_file(source_path)
                if source_sha256 != output_sha256:
                    raise ValueError(f"copied output differs from source for {target}")
                converter = "copy"

            entries.append(
                {
                    "name": name,
                    "size_bytes": output_size,
                    "source_name": source_name,
                    "source_sha256": source_sha256,
                    "output_sha256": output_sha256,
                    "format": file_format(name),
                    "converter": converter,
                }
            )
        bundles[bundle] = entries

    return {
        "manifest_version": 2,
        "target": {
            "platform": "HarmonyOS",
            "architecture": "arm64",
            "execution_provider": "CPUExecutionProvider",
        },
        "converters": {
            "copy": {"mode": "byte-for-byte"},
            CONVERTER_ID: CONVERTER_CONFIG,
        },
        "bundles": bundles,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="staged amphion-models root")
    parser.add_argument(
        "--copy", action="append", default=[], type=parse_mapping, metavar="TARGET=SOURCE"
    )
    parser.add_argument(
        "--converted",
        action="append",
        default=[],
        type=parse_mapping,
        metavar="TARGET=METADATA",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        copied_sources = dict(args.copy)
        converted_metadata = dict(args.converted)
        if len(copied_sources) != len(args.copy) or len(converted_metadata) != len(args.converted):
            raise ValueError("duplicate manifest target")
        manifest = build_manifest(args.root, copied_sources, converted_metadata)
        destination = args.root / "manifest.json"
        _atomic_write_json(manifest, destination)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"[OK] Harmony manifest v2 -> {destination}")


if __name__ == "__main__":
    main()
