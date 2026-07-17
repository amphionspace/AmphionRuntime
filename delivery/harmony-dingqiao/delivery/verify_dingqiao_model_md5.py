#!/usr/bin/env python3
"""Verify that a Dingqiao delivery contains the approved ZH_EN model bytes."""

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
REQUIRED_RUNTIME_FILES = {
    "zh-en/v1/bbpe.vocab",
    "zh-en/v1/decoder.ort",
    "zh-en/v1/encoder.int8.ort",
    "zh-en/v1/joiner.int8.ort",
    "zh-en/v1/tokens.txt",
}
MD5_RE = re.compile(r"[0-9a-f]{32}")


class ModelIdentityError(RuntimeError):
    pass


def _validate_expected(expected: dict[str, str]) -> dict[str, str]:
    if not expected:
        raise ModelIdentityError("model MD5 policy is empty")
    normalized = {}
    for relative, digest in expected.items():
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or not relative.startswith("zh-en/v1/"):
            raise ModelIdentityError(f"unsafe model MD5 path: {relative}")
        if not isinstance(digest, str) or MD5_RE.fullmatch(digest) is None:
            raise ModelIdentityError(f"invalid model MD5 value: {relative}")
        normalized[relative] = digest
    return normalized


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> tuple[str, dict[str, str]]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelIdentityError(f"cannot read model MD5 policy: {path}") from error
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise ModelIdentityError(f"unsupported model MD5 policy: {path}")
    model_id = policy.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ModelIdentityError(f"model MD5 policy has no model_id: {path}")
    runtime = policy.get("runtime_files_md5")
    if not isinstance(runtime, dict):
        raise ModelIdentityError(f"model MD5 policy has no runtime_files_md5: {path}")
    expected = _validate_expected(runtime)
    if set(expected) != REQUIRED_RUNTIME_FILES:
        missing = sorted(REQUIRED_RUNTIME_FILES - set(expected))
        extra = sorted(set(expected) - REQUIRED_RUNTIME_FILES)
        detail = missing[0] if missing else extra[0]
        raise ModelIdentityError(f"model MD5 policy file set mismatch: {detail}")
    return model_id, expected


def _md5_stream(stream: BinaryIO) -> str:
    digest = hashlib.md5()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def verify_root(root: Path, expected_md5: dict[str, str] | None = None) -> None:
    if expected_md5 is None:
        _, expected_md5 = load_policy()
    expected = _validate_expected(expected_md5)
    for relative, approved_md5 in sorted(expected.items()):
        path = root / relative
        if not path.is_file():
            raise ModelIdentityError(f"missing pinned model file: {path}")
        with path.open("rb") as stream:
            actual_md5 = _md5_stream(stream)
        if actual_md5 != approved_md5:
            raise ModelIdentityError(
                f"model MD5 mismatch: {relative}: {actual_md5} != {approved_md5}"
            )


def _is_model_member(name: str, relative: str) -> bool:
    normalized = PurePosixPath(name).as_posix()
    expected = f"amphion-models/{relative}"
    return normalized == expected or normalized.endswith(f"/{expected}")


def _verify_tar(path: Path, expected: dict[str, str]) -> None:
    try:
        archive = tarfile.open(path, "r:*")
    except (OSError, tarfile.TarError) as error:
        raise ModelIdentityError(f"invalid model archive: {path}") from error
    with archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        for relative, approved_md5 in sorted(expected.items()):
            matches = [member for member in members if _is_model_member(member.name, relative)]
            if not matches:
                raise ModelIdentityError(f"archive missing pinned model file: {relative}")
            if len(matches) != 1:
                raise ModelIdentityError(
                    f"multiple archive members for pinned model file: {relative}"
                )
            stream = archive.extractfile(matches[0])
            if stream is None:
                raise ModelIdentityError(f"archive model member is not readable: {relative}")
            with stream:
                actual_md5 = _md5_stream(stream)
            if actual_md5 != approved_md5:
                raise ModelIdentityError(
                    f"model MD5 mismatch: {relative}: {actual_md5} != {approved_md5}"
                )


def _verify_zip(path: Path, expected: dict[str, str]) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise ModelIdentityError(f"invalid model archive: {path}") from error
    with archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        for relative, approved_md5 in sorted(expected.items()):
            matches = [member for member in members if _is_model_member(member.filename, relative)]
            if not matches:
                raise ModelIdentityError(f"archive missing pinned model file: {relative}")
            if len(matches) != 1:
                raise ModelIdentityError(
                    f"multiple archive members for pinned model file: {relative}"
                )
            with archive.open(matches[0]) as stream:
                actual_md5 = _md5_stream(stream)
            if actual_md5 != approved_md5:
                raise ModelIdentityError(
                    f"model MD5 mismatch: {relative}: {actual_md5} != {approved_md5}"
                )


def verify_archive(path: Path, expected_md5: dict[str, str] | None = None) -> None:
    if expected_md5 is None:
        _, expected_md5 = load_policy()
    expected = _validate_expected(expected_md5)
    if zipfile.is_zipfile(path):
        _verify_zip(path, expected)
    else:
        _verify_tar(path, expected)


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
    print(f"[OK] pinned Dingqiao ZH_EN model MD5 verified: {model_id}: {location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
