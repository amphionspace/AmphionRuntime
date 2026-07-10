#!/usr/bin/env python3
"""Verify packed ASR model paths, sizes, and SHA-256 values."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import BinaryIO, Callable


EXPECTED_BUNDLES = {
    "zh-en/v1": ["encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt", "bbpe.vocab"],
    "yue-en/v1": ["encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt", "bbpe.vocab"],
    "punct-zhen/v1": ["model.int8.onnx"],
    "itn-zh/v1": ["zh_itn_tagger.fst", "zh_itn_verbalizer.fst"],
    "vad/v1": ["silero_vad.onnx"],
}


def fail(message: str) -> None:
    raise ValueError(message)


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(manifest: dict) -> dict[str, list[dict]]:
    if manifest.get("manifest_version") != 1:
        fail("manifest_version must be 1")
    bundles = manifest.get("bundles")
    if not isinstance(bundles, dict):
        fail("manifest bundles must be an object")
    if set(bundles) != set(EXPECTED_BUNDLES):
        missing = sorted(set(EXPECTED_BUNDLES) - set(bundles))
        extra = sorted(set(bundles) - set(EXPECTED_BUNDLES))
        fail(f"manifest bundle mismatch: missing={missing} extra={extra}")
    return bundles


def verify_assets(
    manifest_bytes: bytes,
    open_asset: Callable[[str], BinaryIO],
    asset_exists: Callable[[str], bool],
    source_label: str,
) -> int:
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    bundles = validate_manifest(manifest)
    verified = 0

    for bundle, expected_names in EXPECTED_BUNDLES.items():
        entries = bundles[bundle]
        if not isinstance(entries, list):
            fail(f"manifest bundle {bundle} must be an array")
        by_name = {entry.get("name"): entry for entry in entries if isinstance(entry, dict)}
        if len(by_name) != len(entries) or set(by_name) != set(expected_names):
            fail(f"manifest file list mismatch for {bundle}")

        for name in expected_names:
            entry = by_name[name]
            relative_path = f"{bundle}/{name}"
            if not asset_exists(relative_path):
                fail(f"missing model asset: {relative_path}")
            with open_asset(relative_path) as stream:
                digest = sha256_stream(stream)
            with open_asset(relative_path) as stream:
                size = 0
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
            if size != entry.get("size_bytes"):
                fail(f"size mismatch: {relative_path}")
            if digest != str(entry.get("sha256", "")).lower():
                fail(f"sha256 mismatch: {relative_path}")
            verified += 1

            family = bundle.split("/", 1)[0]
            stale_path = f"{family}/{name}"
            if stale_path != relative_path and asset_exists(stale_path):
                fail(f"stale unversioned model asset: {stale_path}")

    print(f"[OK] verified {verified} model assets in {source_label}")
    return verified


def verify_directory(root: Path) -> int:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        fail(f"missing manifest: {manifest_path}")

    def open_asset(relative_path: str) -> BinaryIO:
        return (root / relative_path).open("rb")

    def asset_exists(relative_path: str) -> bool:
        return (root / relative_path).is_file()

    return verify_assets(manifest_path.read_bytes(), open_asset, asset_exists, str(root))


def verify_archive(archive: Path, prefix: str) -> int:
    normalized_prefix = prefix.strip("/")
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        manifest_name = f"{normalized_prefix}/manifest.json"
        if manifest_name not in names:
            fail(f"missing manifest in archive: {manifest_name}")

        def open_asset(relative_path: str) -> BinaryIO:
            return package.open(f"{normalized_prefix}/{relative_path}")

        def asset_exists(relative_path: str) -> bool:
            return f"{normalized_prefix}/{relative_path}" in names

        return verify_assets(package.read(manifest_name), open_asset, asset_exists, str(archive))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--root", type=Path, help="amphion-models directory")
    group.add_argument("--archive", type=Path, help="HAP/ZIP archive")
    parser.add_argument(
        "--prefix",
        default="resources/rawfile/amphion-models",
        help="model directory inside --archive",
    )
    args = parser.parse_args()

    try:
        if args.root is not None:
            verify_directory(args.root)
        else:
            verify_archive(args.archive, args.prefix)
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, KeyError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
