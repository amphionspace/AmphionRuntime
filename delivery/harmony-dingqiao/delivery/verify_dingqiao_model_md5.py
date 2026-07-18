#!/usr/bin/env python3
"""Verify Dingqiao ZH_EN model identity from approved ONNX source MD5 values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import BinaryIO
import zipfile


DEFAULT_POLICY_PATH = Path(__file__).with_name("dingqiao_zh_en_model_md5.json")
RUNTIME_TO_ONNX_SOURCE = {
    "encoder.int8.ort": "encoder.int8.onnx",
    "decoder.ort": "decoder.onnx",
    "joiner.int8.ort": "joiner.onnx",
}
MD5_RE = re.compile(r"[0-9a-f]{32}")


class ModelIdentityError(RuntimeError):
    pass


def _validate_expected(expected: dict[str, str]) -> dict[str, str]:
    approved_sources = set(RUNTIME_TO_ONNX_SOURCE.values())
    if set(expected) != approved_sources:
        missing = sorted(approved_sources - set(expected))
        extra = sorted(set(expected) - approved_sources)
        detail = missing[0] if missing else extra[0]
        raise ModelIdentityError(f"model ONNX MD5 file set mismatch: {detail}")
    for name, digest in expected.items():
        if (
            not isinstance(name, str)
            or not isinstance(digest, str)
            or PurePosixPath(name).name != name
            or MD5_RE.fullmatch(digest) is None
        ):
            raise ModelIdentityError(f"invalid model ONNX MD5 entry: {name}")
    return dict(expected)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> tuple[str, dict[str, str]]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelIdentityError(f"cannot read model identity policy: {path}") from error
    if not isinstance(policy, dict) or policy.get("schema_version") != 3:
        raise ModelIdentityError(f"unsupported model identity policy: {path}")
    model_id = policy.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ModelIdentityError(f"model identity policy has no model_id: {path}")
    source_bundle = policy.get("source_bundle")
    if (
        not isinstance(source_bundle, dict)
        or source_bundle.get("name") != "bundle.tar.gz"
        or not isinstance(source_bundle.get("md5"), str)
        or MD5_RE.fullmatch(source_bundle["md5"]) is None
    ):
        raise ModelIdentityError(f"model identity policy has invalid source bundle: {path}")
    expected = policy.get("onnx_files_md5")
    if not isinstance(expected, dict):
        raise ModelIdentityError(f"model identity policy has no onnx_files_md5: {path}")
    return model_id, _validate_expected(expected)


def _validate_manifest(manifest: object, expected: dict[str, str]) -> None:
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
    for runtime_name, source_name in RUNTIME_TO_ONNX_SOURCE.items():
        matches = sum(
            entry.get("name") == runtime_name
            for entry in entries
            if isinstance(entry, dict)
        )
        if matches != 1:
            raise ModelIdentityError(f"duplicate or missing ZH_EN runtime entry: {runtime_name}")
        entry = by_name.get(runtime_name)
        assert entry is not None
        if entry.get("source_name") != source_name:
            raise ModelIdentityError(f"model source name mismatch: {runtime_name}")
        actual_md5 = entry.get("source_md5")
        if actual_md5 != expected[source_name]:
            raise ModelIdentityError(
                f"model ONNX MD5 mismatch: {source_name}: "
                f"{actual_md5} != {expected[source_name]}"
            )


def verify_root(root: Path, expected_md5: dict[str, str] | None = None) -> None:
    if expected_md5 is None:
        _, expected_md5 = load_policy()
    expected = _validate_expected(expected_md5)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelIdentityError("cannot read model manifest") from error
    _validate_manifest(manifest, expected)


def _is_model_manifest(name: str) -> bool:
    normalized = PurePosixPath(name).as_posix()
    return normalized == "amphion-models/manifest.json" or normalized.endswith(
        "/amphion-models/manifest.json"
    )


def _verify_archive_members(
    members: list[tuple[str, BinaryIO]], expected: dict[str, str]
) -> None:
    matches = [stream for name, stream in members if _is_model_manifest(name)]
    if len(matches) != 1:
        raise ModelIdentityError("archive must contain exactly one model manifest")
    try:
        manifest = json.load(matches[0])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelIdentityError("invalid archive model manifest") from error
    _validate_manifest(manifest, expected)


def verify_archive(path: Path, expected_md5: dict[str, str] | None = None) -> None:
    if expected_md5 is None:
        _, expected_md5 = load_policy()
    expected = _validate_expected(expected_md5)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            opened = [
                (member.filename, archive.open(member))
                for member in archive.infolist()
                if not member.is_dir() and _is_model_manifest(member.filename)
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
            if member.isfile() and _is_model_manifest(member.name):
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
    print(f"[OK] pinned Dingqiao ZH_EN ONNX MD5 verified: {model_id}: {location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
