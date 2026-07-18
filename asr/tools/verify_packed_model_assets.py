#!/usr/bin/env python3
"""Verify packed ASR model paths, sizes, SHA-256 values, and target format."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import BinaryIO, Callable, Iterable


EXPECTED_BUNDLES_V1 = {
    "zh-en/v1": [
        "encoder.int8.onnx",
        "decoder.onnx",
        "joiner.int8.onnx",
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
    "punct-zhen/v1": ["model.int8.onnx"],
    "itn-zh/v1": ["zh_itn_tagger.fst", "zh_itn_verbalizer.fst"],
    "vad/v1": ["silero_vad.onnx"],
}

EXPECTED_BUNDLES_V2 = {
    "zh-en/v1": [
        "encoder.int8.ort",
        "decoder.ort",
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

EXPECTED_HARMONY_TARGET = {
    "platform": "HarmonyOS",
    "architecture": "arm64",
    "execution_provider": "CPUExecutionProvider",
}
HARMONY_CONVERTER_ID = "onnxruntime-1.16.3-fixed-arm-cpu-v1"
EXPECTED_HARMONY_CONVERTER = {
    "id": HARMONY_CONVERTER_ID,
    "onnxruntime_version": "1.16.3",
    "onnx_version": "1.15.0",
    "numpy_version": "1.26.4",
    "optimization_style": "Fixed",
    "graph_optimization_level": "all",
    "target_platform": "arm",
    "execution_provider": "CPUExecutionProvider",
    "disabled_optimizers": ["NchwcTransformer"],
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MD5_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def fail(message: str) -> None:
    raise ValueError(message)


def sha256_and_size(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _validate_v2_header(manifest: dict) -> None:
    if manifest.get("target") != EXPECTED_HARMONY_TARGET:
        fail("manifest v2 target must be HarmonyOS arm64 CPUExecutionProvider")
    converters = manifest.get("converters")
    if not isinstance(converters, dict):
        fail("manifest v2 converters must be an object")
    if converters.get("copy") != {"mode": "byte-for-byte"}:
        fail("manifest v2 copy converter is invalid")
    if converters.get(HARMONY_CONVERTER_ID) != EXPECTED_HARMONY_CONVERTER:
        fail("manifest v2 ONNX Runtime converter is invalid")
    if set(converters) != {"copy", HARMONY_CONVERTER_ID}:
        fail("manifest v2 converter list is invalid")


def validate_manifest(
    manifest: dict,
    zh_en_only: bool = False,
) -> tuple[int, dict[str, list[dict]], dict[str, list[str]]]:
    version = manifest.get("manifest_version")
    if version == 1:
        expected_bundles = EXPECTED_BUNDLES_V1
    elif version == 2:
        _validate_v2_header(manifest)
        expected_bundles = dict(EXPECTED_BUNDLES_V2)
        if zh_en_only:
            expected_bundles.pop("yue-en/v1")
    else:
        fail("manifest_version must be 1 or 2")

    bundles = manifest.get("bundles")
    if not isinstance(bundles, dict):
        fail("manifest bundles must be an object")
    if set(bundles) != set(expected_bundles):
        missing = sorted(set(expected_bundles) - set(bundles))
        extra = sorted(set(bundles) - set(expected_bundles))
        fail(f"manifest bundle mismatch: missing={missing} extra={extra}")
    return version, bundles, expected_bundles


def _expected_v2_format(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return {
        ".ort": "ort",
        ".onnx": "onnx",
        ".fst": "fst",
        ".txt": "text",
        ".vocab": "text",
    }[suffix]


def _validate_v2_entry(entry: dict, name: str, relative_path: str) -> str:
    source_name = entry.get("source_name")
    if (
        not isinstance(source_name, str)
        or not source_name
        or Path(source_name).name != source_name
    ):
        fail(f"invalid source_name: {relative_path}")
    source_sha256 = entry.get("source_sha256")
    source_md5 = entry.get("source_md5")
    output_sha256 = entry.get("output_sha256")
    if not isinstance(source_md5, str) or not MD5_PATTERN.fullmatch(source_md5):
        fail(f"invalid source_md5: {relative_path}")
    if not isinstance(source_sha256, str) or not SHA256_PATTERN.fullmatch(source_sha256):
        fail(f"invalid source_sha256: {relative_path}")
    if not isinstance(output_sha256, str) or not SHA256_PATTERN.fullmatch(output_sha256):
        fail(f"invalid output_sha256: {relative_path}")
    if entry.get("format") != _expected_v2_format(name):
        fail(f"format mismatch: {relative_path}")

    expected_converter = HARMONY_CONVERTER_ID if name.endswith(".ort") else "copy"
    if entry.get("converter") != expected_converter:
        fail(f"converter mismatch: {relative_path}")
    if expected_converter == "copy" and source_sha256 != output_sha256:
        fail(f"copy source/output sha256 mismatch: {relative_path}")
    return output_sha256


def _validate_exact_v2_assets(
    asset_names: Iterable[str], expected_bundles: dict[str, list[str]]
) -> None:
    expected = {
        f"{bundle}/{name}" for bundle, names in expected_bundles.items() for name in names
    }
    bundle_families = {bundle.split("/", 1)[0] for bundle in expected_bundles}
    actual = {
        name.strip("/")
        for name in asset_names
        if name.strip("/").split("/", 1)[0] in bundle_families
        and Path(name).name != ".gitkeep"
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        fail(f"Harmony target file mismatch: missing={missing} extra={extra}")


def verify_assets(
    manifest_bytes: bytes,
    open_asset: Callable[[str], BinaryIO],
    asset_exists: Callable[[str], bool],
    list_assets: Callable[[], Iterable[str]],
    source_label: str,
    zh_en_only: bool = False,
) -> int:
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    version, bundles, expected_bundles = validate_manifest(manifest, zh_en_only)
    if version == 2:
        _validate_exact_v2_assets(list_assets(), expected_bundles)
    verified = 0

    for bundle, expected_names in expected_bundles.items():
        entries = bundles[bundle]
        if not isinstance(entries, list):
            fail(f"manifest bundle {bundle} must be an array")
        if not all(isinstance(entry, dict) for entry in entries):
            fail(f"manifest bundle {bundle} contains a non-object entry")
        names = [entry.get("name") for entry in entries]
        if not all(isinstance(name, str) for name in names):
            fail(f"manifest bundle {bundle} contains an invalid name")
        if len(set(names)) != len(entries) or set(names) != set(expected_names):
            fail(f"manifest file list mismatch for {bundle}")
        by_name = {entry["name"]: entry for entry in entries}

        for name in expected_names:
            entry = by_name[name]
            relative_path = f"{bundle}/{name}"
            if not asset_exists(relative_path):
                fail(f"missing model asset: {relative_path}")
            with open_asset(relative_path) as stream:
                digest, size = sha256_and_size(stream)
            if size != entry.get("size_bytes"):
                fail(f"size mismatch: {relative_path}")
            expected_digest = (
                str(entry.get("sha256", "")).lower()
                if version == 1
                else _validate_v2_entry(entry, name, relative_path)
            )
            if digest != expected_digest:
                fail(f"sha256 mismatch: {relative_path}")
            verified += 1

            family = bundle.split("/", 1)[0]
            stale_path = f"{family}/{name}"
            if stale_path != relative_path and asset_exists(stale_path):
                fail(f"stale unversioned model asset: {stale_path}")

    print(f"[OK] verified manifest v{version} with {verified} model assets in {source_label}")
    return verified


def verify_directory(root: Path, zh_en_only: bool = False) -> int:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        fail(f"missing manifest: {manifest_path}")

    def open_asset(relative_path: str) -> BinaryIO:
        return (root / relative_path).open("rb")

    def asset_exists(relative_path: str) -> bool:
        return (root / relative_path).is_file()

    def list_assets() -> Iterable[str]:
        return (path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())

    return verify_assets(
        manifest_path.read_bytes(),
        open_asset,
        asset_exists,
        list_assets,
        str(root),
        zh_en_only,
    )


def _verify_zip_archive(archive: Path, prefix: str, zh_en_only: bool) -> int:
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

        def list_assets() -> Iterable[str]:
            prefix_with_separator = f"{normalized_prefix}/"
            return (
                name[len(prefix_with_separator) :]
                for name in names
                if name.startswith(prefix_with_separator) and not name.endswith("/")
            )

        return verify_assets(
            package.read(manifest_name),
            open_asset,
            asset_exists,
            list_assets,
            str(archive),
            zh_en_only,
        )


def _verify_tar_archive(archive: Path, prefix: str, zh_en_only: bool) -> int:
    normalized_prefix = prefix.strip("/")
    with tarfile.open(archive, "r:*") as package:
        file_members = [member for member in package.getmembers() if member.isfile()]
        names = [member.name for member in file_members]
        if len(names) != len(set(names)):
            fail("duplicate file path in model archive")
        members = {member.name: member for member in file_members}
        manifest_name = f"{normalized_prefix}/manifest.json"
        if manifest_name not in members:
            fail(f"missing manifest in archive: {manifest_name}")

        def open_asset(relative_path: str) -> BinaryIO:
            member_name = f"{normalized_prefix}/{relative_path}"
            stream = package.extractfile(members[member_name])
            if stream is None:
                fail(f"model asset is not a file: {member_name}")
            return stream

        def asset_exists(relative_path: str) -> bool:
            return f"{normalized_prefix}/{relative_path}" in members

        def list_assets() -> Iterable[str]:
            prefix_with_separator = f"{normalized_prefix}/"
            return (
                name[len(prefix_with_separator) :]
                for name in members
                if name.startswith(prefix_with_separator)
            )

        manifest_stream = package.extractfile(members[manifest_name])
        if manifest_stream is None:
            fail(f"manifest is not a file: {manifest_name}")
        with manifest_stream:
            manifest_bytes = manifest_stream.read()
        return verify_assets(
            manifest_bytes,
            open_asset,
            asset_exists,
            list_assets,
            str(archive),
            zh_en_only,
        )


def verify_archive(archive: Path, prefix: str, zh_en_only: bool = False) -> int:
    if zipfile.is_zipfile(archive):
        return _verify_zip_archive(archive, prefix, zh_en_only)
    return _verify_tar_archive(archive, prefix, zh_en_only)


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
    parser.add_argument(
        "--zh-en-only",
        action="store_true",
        help="expect the Harmony v2 bundle set without yue-en/v1",
    )
    args = parser.parse_args()

    try:
        if args.root is not None:
            verify_directory(args.root, args.zh_en_only)
        else:
            verify_archive(args.archive, args.prefix, args.zh_en_only)
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        tarfile.TarError,
        zipfile.BadZipFile,
        KeyError,
    ) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
