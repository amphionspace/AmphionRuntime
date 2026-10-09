#!/usr/bin/env python3
"""Verify optional Community MindIR provenance and Harmony payload consistency."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import sys
import tarfile
from typing import BinaryIO, Iterable
import zipfile

if __package__:
    from . import convert_community_encoder as converter
else:
    import convert_community_encoder as converter


ROOT = Path(__file__).resolve().parents[2]
MODEL_FILE = "community-wespeaker-encoder.fp16.ms"
SOURCE_FILE = "community-wespeaker-encoder.fp32.onnx"
PROVENANCE_FILE = MODEL_FILE + ".provenance.json"
SHARED_DIR = Path("shared/models/asr/dingqiao")
GENERATED_DIR = Path("asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao")
HAP_MEMBER = "resources/rawfile/amphion-dingqiao/" + MODEL_FILE
ARCHIVE_MEMBERS = {HAP_MEMBER, "package/src/main/" + HAP_MEMBER, "src/main/" + HAP_MEMBER}


class VerificationError(RuntimeError):
    pass


def stream_identity(stream: BinaryIO) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def file_identity(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise VerificationError(f"missing regular MindIR input: {path}")
    with path.open("rb") as stream:
        return stream_identity(stream)


def verify_archive(archive: Path, expected: dict[str, object] | None) -> None:
    def model_member(names: list[str]) -> int | None:
        normalized = [PurePosixPath(name) for name in names]
        if any(name.name == PROVENANCE_FILE for name in normalized):
            raise VerificationError(f"MindIR provenance must not be packaged: {archive}")
        candidates = [index for index, name in enumerate(normalized) if name.name == MODEL_FILE]
        if len(candidates) > 1:
            raise VerificationError(f"duplicate MindIR archive member: {archive}")
        if not candidates:
            if expected is not None:
                raise VerificationError(f"missing MindIR archive member: {archive}")
            return None
        index = candidates[0]
        if normalized[index].as_posix() not in ARCHIVE_MEMBERS:
            raise VerificationError(f"unexpected MindIR archive path: {names[index]}")
        if expected is None:
            raise VerificationError(f"MindIR archive has no verified shared source/provenance: {archive}")
        return index

    def compare(stream: BinaryIO) -> None:
        if stream_identity(stream) != expected:
            raise VerificationError(f"MindIR archive SHA-256/bytes mismatch: {archive}")

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            members = package.infolist()
            index = model_member([member.filename for member in members])
            if index is not None:
                with package.open(members[index]) as stream:
                    compare(stream)
    else:
        with tarfile.open(archive, "r:*") as package:
            members = package.getmembers()
            index = model_member([member.name for member in members])
            if index is not None:
                member = members[index]
                if not member.isfile():
                    raise VerificationError(f"MindIR archive member is not a regular file: {archive}")
                stream = package.extractfile(member)
                if stream is None:
                    raise VerificationError(f"cannot read MindIR archive member: {archive}")
                with stream:
                    compare(stream)


def verify_assets(
    repo_root: Path = ROOT,
    *,
    generated_root: Path | None = None,
    archives: Iterable[Path] = (),
    source_only: bool = False,
    required: bool = False,
) -> dict[str, object] | None:
    shared = repo_root / SHARED_DIR
    output, source = shared / MODEL_FILE, shared / SOURCE_FILE
    provenance = shared / PROVENANCE_FILE
    generated = generated_root if generated_root is not None else repo_root / GENERATED_DIR
    expected = None
    metadata = None
    if output.exists() or output.is_symlink():
        try:
            record = converter.verify_provenance(output, source)
        except converter.ConversionError as error:
            raise VerificationError(f"invalid MindIR source/provenance: {error}") from error
        expected = {"sha256": record["output"]["sha256"], "size_bytes": record["output"]["sizeBytes"]}
        metadata = {
            **expected,
            "source_path": str(SHARED_DIR / SOURCE_FILE),
            "source_sha256": record["source"]["sha256"],
            "source_size_bytes": record["source"]["sizeBytes"],
            "provenance_path": str(SHARED_DIR / PROVENANCE_FILE),
            "provenance_sha256": file_identity(provenance)["sha256"],
        }
    elif provenance.exists() or provenance.is_symlink():
        raise VerificationError(f"orphan MindIR provenance without its model: {provenance}")
    elif required:
        raise VerificationError(f"required Community MindIR model is missing: {output}")

    # Before Hvigor, the generated copy may be absent or still awaiting refresh.
    if not source_only:
        generated_provenance = generated / PROVENANCE_FILE
        if generated_provenance.exists() or generated_provenance.is_symlink():
            raise VerificationError(f"MindIR provenance must not enter generated rawfile: {generated_provenance}")
        target = generated / MODEL_FILE
        if expected is not None:
            if file_identity(target) != expected:
                raise VerificationError(f"stale generated MindIR SHA-256/bytes mismatch: {target}")
        elif target.exists() or target.is_symlink():
            raise VerificationError(f"stale generated MindIR without shared source/provenance: {target}")
    for archive in archives:
        verify_archive(archive, expected)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--generated-root", type=Path)
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument("--source-only", action="store_true", help="verify inputs before Hvigor generates rawfile")
    parser.add_argument("--required", action="store_true", help="fail if the optional NPU model is not prepared")
    args = parser.parse_args()
    try:
        metadata = verify_assets(args.repo_root, generated_root=args.generated_root,
                                 archives=args.archive, source_only=args.source_only, required=args.required)
        if metadata is None:
            print("[OK] Community MindIR absent; CPU model inputs remain available")
        else:
            print(f"[OK] Community MindIR provenance/payload: {metadata}")
        return 0
    except (VerificationError, OSError, tarfile.TarError, zipfile.BadZipFile, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
