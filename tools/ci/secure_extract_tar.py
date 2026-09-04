#!/usr/bin/env python3
"""Extract a tar archive without links, special files, or path traversal."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile


MAX_FILES = 100_000
MAX_TOTAL_BYTES = 10 * 1024 * 1024 * 1024


class UnsafeArchiveError(RuntimeError):
    pass


def _relative_parts(name: str) -> tuple[str, ...]:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeArchiveError(f"unsafe archive path: {name!r}")
    return path.parts


def extract_tar(archive_path: Path, destination: Path) -> None:
    if destination.is_symlink():
        raise UnsafeArchiveError(f"destination must not be a symbolic link: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > MAX_FILES:
            raise UnsafeArchiveError(f"archive contains too many entries: {len(members)}")
        total_bytes = sum(member.size for member in members if member.isfile())
        if total_bytes > MAX_TOTAL_BYTES:
            raise UnsafeArchiveError(f"archive expands beyond size limit: {total_bytes}")

        validated: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
        for member in members:
            parts = _relative_parts(member.name)
            if not (member.isdir() or member.isfile()):
                raise UnsafeArchiveError(f"archive entry is not a regular file or directory: {member.name}")
            validated.append((member, parts))

        for member, parts in validated:
            target = destination.joinpath(*parts)
            parent = target if member.isdir() else target.parent
            current = destination
            for part in parent.relative_to(destination).parts:
                current /= part
                if current.is_symlink():
                    raise UnsafeArchiveError(
                        f"destination contains a symbolic link: {current}"
                    )
            if os.path.commonpath((destination_root, target.resolve(strict=False))) != str(
                destination_root
            ):
                raise UnsafeArchiveError(f"archive entry escapes destination: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.is_symlink():
                raise UnsafeArchiveError(f"target is a symbolic link: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise UnsafeArchiveError(f"cannot read archive entry: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    extract_tar(args.archive, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
