#!/usr/bin/env python3
"""Create a deterministic gzip-compressed TAR without workstation metadata."""

from __future__ import annotations

import argparse
import gzip
import os
from pathlib import Path
import tarfile


class NormalizedTarError(RuntimeError):
    pass


def _archive_name(root: Path, path: Path) -> str:
    if path == root:
        return "package"
    return f"package/{path.relative_to(root).as_posix()}"


def create_archive(root: Path, output: Path) -> None:
    if not root.is_dir() or root.is_symlink():
        raise NormalizedTarError(f"archive root must be a real directory: {root}")
    paths = [root] + sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in paths:
        if path.is_symlink():
            raise NormalizedTarError(f"archive payload must not contain symlink: {path}")
        if not path.is_dir() and not path.is_file():
            raise NormalizedTarError(f"archive payload contains special file: {path}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT
                ) as archive:
                    for path in paths:
                        info = archive.gettarinfo(str(path), arcname=_archive_name(root, path))
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = 0
                        info.pax_headers = {}
                        if info.isdir():
                            info.mode = 0o755
                            archive.addfile(info)
                        else:
                            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                            with path.open("rb") as stream:
                                archive.addfile(info, stream)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        create_archive(args.root, args.output)
    except NormalizedTarError as error:
        parser.error(str(error))
    print(f"[OK] normalized archive created: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
