#!/usr/bin/env python3
"""Create and verify identity-bound Android native build caches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence


FINGERPRINT_SCHEMA = "android-native-source-v1"
MANIFEST_SCHEMA = 1
SUPPORTED_ABI = "arm64-v8a"
SOURCE_INPUTS = (
    ".gitmodules",
    "asr/native",
    "third_party/patches/sherpa-amphion",
    "asr/tools/03_build_agc_native.sh",
    "asr/tools/04_build_android_so.sh",
    "asr/tools/05_package_aar_libs.sh",
    "asr/tools/apply_sherpa_patches.sh",
    "asr/tools/prepare_sherpa_source.sh",
    "asr/tools/ensure_agc_build_tools.sh",
    "asr/tools/prefetch_sherpa_cmake_deps.sh",
    "asr/tools/android_native_cache.py",
)
SOURCE_DIRECTORIES = (
    "asr/native",
    "third_party/patches/sherpa-amphion",
)
ARTIFACTS = (
    f"third_party/.derived/sherpa-onnx/build-android-{SUPPORTED_ABI}/install/lib/"
    "libsherpa-onnx-jni.so",
    f"third_party/.derived/sherpa-onnx/build-android-{SUPPORTED_ABI}/install/lib/"
    "libonnxruntime.so",
    f"asr/native/audio-processing/build-android-{SUPPORTED_ABI}/"
    "libamphion_audio_processing.so",
)
CONFIGURATION_KEYS = (
    "abi",
    "android_platform",
    "cmake_version",
    "meson_version",
    "ndk_version",
    "ninja_version",
    "onnxruntime_version",
)


class CacheIdentityError(RuntimeError):
    pass


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8", errors="strict")


def tracked_source_files(root: Path) -> tuple[str, ...]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--", *SOURCE_INPUTS],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    files = tuple(sorted(item.decode("utf-8") for item in output.split(b"\0") if item))
    if not files:
        raise CacheIdentityError("no tracked Android native source inputs found")
    for source in SOURCE_INPUTS:
        matched = (
            any(relative.startswith(f"{source}/") for relative in files)
            if source in SOURCE_DIRECTORIES
            else source in files
        )
        if not matched:
            raise CacheIdentityError(f"native source input is not tracked: {source}")
    missing = [relative for relative in files if not (root / relative).exists()]
    if missing:
        raise CacheIdentityError(f"tracked source input is missing: {missing[0]}")
    return files


def sherpa_gitlink(root: Path) -> str:
    value = _run_git(root, "rev-parse", ":third_party/sherpa-onnx").strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise CacheIdentityError("invalid sherpa-onnx gitlink commit")
    return value


def _configuration(configuration: Mapping[str, str]) -> dict[str, str]:
    missing = [key for key in CONFIGURATION_KEYS if not configuration.get(key)]
    if missing:
        raise CacheIdentityError(f"missing native build configuration: {missing[0]}")
    normalized = {key: configuration[key] for key in CONFIGURATION_KEYS}
    if normalized["abi"] != SUPPORTED_ABI:
        raise CacheIdentityError(
            f"unsupported Android native cache ABI: {normalized['abi']} "
            f"(expected {SUPPORTED_ABI})"
        )
    return normalized


def _source_entry(root: Path, relative: str) -> dict[str, str]:
    path = root / relative
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        payload = os.readlink(path).encode("utf-8")
        kind = "symlink"
    elif stat.S_ISREG(metadata.st_mode):
        payload = path.read_bytes()
        kind = "file"
    else:
        raise CacheIdentityError(f"unsupported source input type: {relative}")
    return {
        "path": relative,
        "kind": kind,
        "executable": "true" if metadata.st_mode & stat.S_IXUSR else "false",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def source_fingerprint(
    root: Path, sherpa_commit: str, configuration: Mapping[str, str]
) -> str:
    identity = {
        "schema": FINGERPRINT_SCHEMA,
        "sherpa_onnx_gitlink": sherpa_commit,
        "configuration": _configuration(configuration),
        "sources": [_source_entry(root, relative) for relative in tracked_source_files(root)],
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_fingerprint(fingerprint: str) -> None:
    if len(fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        raise CacheIdentityError("native cache fingerprint is invalid")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    root: Path,
    manifest_path: Path,
    fingerprint: str,
    configuration: Mapping[str, str],
) -> None:
    _validate_fingerprint(fingerprint)
    artifacts: dict[str, dict[str, object]] = {}
    for relative in ARTIFACTS:
        path = root / relative
        if not path.is_file():
            raise CacheIdentityError(f"native artifact is missing: {relative}")
        artifacts[relative] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    payload = {
        "schema": MANIFEST_SCHEMA,
        "fingerprint": fingerprint,
        "configuration": _configuration(configuration),
        "artifacts": artifacts,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=manifest_path.parent, delete=False
    ) as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, manifest_path)


def verify_manifest(
    root: Path,
    manifest_path: Path,
    fingerprint: str,
    configuration: Mapping[str, str],
) -> None:
    _validate_fingerprint(fingerprint)
    if not manifest_path.is_file():
        raise CacheIdentityError(f"native cache manifest is missing: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CacheIdentityError(f"native cache manifest is invalid: {error}") from error
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise CacheIdentityError("native cache manifest schema mismatch")
    if payload.get("fingerprint") != fingerprint:
        raise CacheIdentityError("native cache fingerprint mismatch")
    if payload.get("configuration") != _configuration(configuration):
        raise CacheIdentityError("native cache configuration mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACTS):
        raise CacheIdentityError("native cache artifact set mismatch")
    for relative in ARTIFACTS:
        path = root / relative
        if not path.is_file():
            raise CacheIdentityError(f"native artifact is missing: {relative}")
        entry = artifacts[relative]
        if not isinstance(entry, dict) or entry.get("sha256") != sha256_file(path):
            raise CacheIdentityError(f"native artifact SHA-256 mismatch: {relative}")
        if entry.get("size") != path.stat().st_size:
            raise CacheIdentityError(f"native artifact size mismatch: {relative}")


def add_configuration_arguments(parser: argparse.ArgumentParser) -> None:
    for key in CONFIGURATION_KEYS:
        parser.add_argument(f"--{key.replace('_', '-')}", required=True)


def configuration_from_args(args: argparse.Namespace) -> dict[str, str]:
    return {key: getattr(args, key) for key in CONFIGURATION_KEYS}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    subparsers = parser.add_subparsers(dest="command", required=True)

    fingerprint = subparsers.add_parser("fingerprint")
    add_configuration_arguments(fingerprint)

    create = subparsers.add_parser("create-manifest")
    create.add_argument("--manifest", type=Path, required=True)
    create.add_argument("--fingerprint", required=True)
    add_configuration_arguments(create)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--fingerprint", required=True)
    add_configuration_arguments(verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "fingerprint":
            print(source_fingerprint(root, sherpa_gitlink(root), configuration_from_args(args)))
        elif args.command == "create-manifest":
            write_manifest(root, args.manifest, args.fingerprint, configuration_from_args(args))
            print(f"[OK] wrote Android native cache manifest: {args.manifest}")
        else:
            verify_manifest(
                root,
                args.manifest,
                args.fingerprint,
                configuration_from_args(args),
            )
            print(f"[OK] verified Android native cache: {args.fingerprint}")
    except (CacheIdentityError, subprocess.CalledProcessError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
