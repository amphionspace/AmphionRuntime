#!/usr/bin/env python3
"""Verify Dingqiao ZH_EN model identity from stable ONNX source hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import BinaryIO
import zipfile


DEFAULT_POLICY_PATH = Path(__file__).with_name("dingqiao_zh_en_model_md5.json")
RUNTIME_TO_SOURCE = {
    "encoder.int8.ort": "encoder.int8.onnx",
    "decoder.ort": "decoder.onnx",
    "joiner.int8.ort": "joiner.onnx",
    "tokens.txt": "tokens.txt",
    "bbpe.vocab": "bbpe.vocab",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ModelIdentityError(RuntimeError):
    pass


def _validate_expected(expected: dict[str, str]) -> dict[str, str]:
    if set(expected) != set(RUNTIME_TO_SOURCE.values()):
        missing = sorted(set(RUNTIME_TO_SOURCE.values()) - set(expected))
        extra = sorted(set(expected) - set(RUNTIME_TO_SOURCE.values()))
        detail = missing[0] if missing else extra[0]
        raise ModelIdentityError(f"model source SHA-256 file set mismatch: {detail}")
    for name, digest in expected.items():
        if PurePosixPath(name).name != name or SHA256_RE.fullmatch(digest) is None:
            raise ModelIdentityError(f"invalid model source SHA-256 entry: {name}")
    return dict(expected)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> tuple[str, dict[str, str]]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelIdentityError(f"cannot read model identity policy: {path}") from error
    if not isinstance(policy, dict) or policy.get("schema_version") != 2:
        raise ModelIdentityError(f"unsupported model identity policy: {path}")
    model_id = policy.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ModelIdentityError(f"model identity policy has no model_id: {path}")
    expected = policy.get("source_files_sha256")
    if not isinstance(expected, dict):
        raise ModelIdentityError(f"model identity policy has no source_files_sha256: {path}")
    return model_id, _validate_expected(expected)


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _validated_entries(manifest: object, expected: dict[str, str]) -> dict[str, dict]:
    if not isinstance(manifest, dict) or manifest.get("manifest_version") != 2:
        raise ModelIdentityError("invalid model manifest")
    bundles = manifest.get("bundles")
    entries = bundles.get("zh-en/v1") if isinstance(bundles, dict) else None
    if not isinstance(entries, list):
        raise ModelIdentityError("model manifest has no zh-en/v1 bundle")
    by_name = {
        entry.get("name"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    if set(by_name) != set(RUNTIME_TO_SOURCE):
        raise ModelIdentityError("ZH_EN runtime file set mismatch")
    for runtime_name, source_name in RUNTIME_TO_SOURCE.items():
        entry = by_name[runtime_name]
        if entry.get("source_name") != source_name:
            raise ModelIdentityError(f"model source name mismatch: {runtime_name}")
        actual_source = entry.get("source_sha256")
        if actual_source != expected[source_name]:
            raise ModelIdentityError(
                f"model source SHA-256 mismatch: {source_name}: "
                f"{actual_source} != {expected[source_name]}"
            )
        if SHA256_RE.fullmatch(str(entry.get("output_sha256"))) is None:
            raise ModelIdentityError(f"invalid runtime SHA-256: {runtime_name}")
    return by_name


def verify_root(root: Path, expected_sha256: dict[str, str] | None = None) -> None:
    if expected_sha256 is None:
        _, expected_sha256 = load_policy()
    expected = _validate_expected(expected_sha256)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelIdentityError("cannot read model manifest") from error
    entries = _validated_entries(manifest, expected)
    for runtime_name, entry in entries.items():
        path = root / "zh-en/v1" / runtime_name
        if not path.is_file():
            raise ModelIdentityError(f"missing model runtime file: {path}")
        with path.open("rb") as stream:
            actual = _sha256_stream(stream)
        if actual != entry["output_sha256"]:
            raise ModelIdentityError(f"runtime SHA-256 mismatch: {runtime_name}")


def _is_model_member(name: str, relative: str) -> bool:
    normalized = PurePosixPath(name).as_posix()
    expected = f"amphion-models/{relative}"
    return normalized == expected or normalized.endswith(f"/{expected}")


def _verify_archive_members(
    members: list[tuple[str, BinaryIO]], expected: dict[str, str]
) -> None:
    manifest_matches = [stream for name, stream in members if _is_model_member(name, "manifest.json")]
    if len(manifest_matches) != 1:
        raise ModelIdentityError("archive must contain exactly one model manifest")
    try:
        manifest = json.load(manifest_matches[0])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelIdentityError("invalid archive model manifest") from error
    entries = _validated_entries(manifest, expected)
    for runtime_name, entry in entries.items():
        relative = f"zh-en/v1/{runtime_name}"
        matches = [stream for name, stream in members if _is_model_member(name, relative)]
        if len(matches) != 1:
            raise ModelIdentityError(
                f"archive must contain exactly one model runtime file: {relative}"
            )
        if _sha256_stream(matches[0]) != entry["output_sha256"]:
            raise ModelIdentityError(f"runtime SHA-256 mismatch: {runtime_name}")


def verify_archive(path: Path, expected_sha256: dict[str, str] | None = None) -> None:
    if expected_sha256 is None:
        _, expected_sha256 = load_policy()
    expected = _validate_expected(expected_sha256)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            opened = [
                (member.filename, archive.open(member))
                for member in archive.infolist()
                if not member.is_dir()
            ]
            try:
                _verify_archive_members(opened, expected)
            finally:
                for _, stream in opened:
                    stream.close()
        return
    try:
        archive = tarfile.open(path, "r:*")
    except (OSError, tarfile.TarError) as error:
        raise ModelIdentityError(f"invalid model archive: {path}") from error
    with archive:
        opened = []
        for member in archive.getmembers():
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is not None:
                    opened.append((member.name, stream))
        try:
            _verify_archive_members(opened, expected)
        finally:
            for _, stream in opened:
                stream.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--root", type=Path)
    target.add_argument("--archive", type=Path)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    args = parser.parse_args()
    try:
        model_id, expected = load_policy(args.policy)
        if args.root is not None:
            verify_root(args.root, expected)
            location = args.root
        else:
            verify_archive(args.archive, expected)
            location = args.archive
    except ModelIdentityError as error:
        parser.error(str(error))
    print(f"[OK] pinned Dingqiao ZH_EN ONNX identity verified: {model_id}: {location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
