#!/usr/bin/env python3
"""Remove non-runtime and internal metadata from an extracted public HAR payload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil


POLICE_RELATIVE_ROOT = Path(
    "_bundled/amphion_police/src/main/resources/rawfile/amphion-police"
)
COMMENTED_POLICE_SUFFIXES = {".csv", ".tsv", ".txt"}


class PayloadSanitizationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_internal_files(package_root: Path) -> None:
    for path in package_root.rglob("*"):
        if path.is_symlink():
            raise PayloadSanitizationError(f"public HAR payload must not contain symlinks: {path}")
    for directory in sorted(
        (path for path in package_root.rglob("tests") if path.is_dir()), reverse=True
    ):
        shutil.rmtree(directory)
    for path in list(package_root.rglob("CONTRACT_TESTS.md")):
        path.unlink()
    for path in list(package_root.rglob("oh-package-lock.json5")):
        path.unlink()
    for path in list(package_root.rglob("README.md")):
        path.unlink()
    for path in list(package_root.rglob("*")):
        if path.is_file() and (path.name == ".DS_Store" or path.name.startswith("._")):
            path.unlink()


def _sanitize_police_assets(package_root: Path) -> None:
    police_root = package_root / POLICE_RELATIVE_ROOT
    manifest_path = police_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PayloadSanitizationError(f"invalid police manifest: {manifest_path}") from error
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise PayloadSanitizationError("police manifest files must be an object")

    for path in list(police_root.rglob("*_meta.json")):
        path.unlink()
    for path in police_root.rglob("*"):
        if not path.is_file() or path.suffix not in COMMENTED_POLICE_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as error:
            raise PayloadSanitizationError(f"police text asset is not UTF-8: {path}") from error
        retained = [line for line in lines if not line.startswith("#")]
        path.write_text("".join(retained), encoding="utf-8")

    public_files = {}
    for relative in files:
        member = PurePosixPath(relative)
        if member.is_absolute() or ".." in member.parts:
            raise PayloadSanitizationError(f"unsafe police manifest path: {relative}")
        if relative.endswith("_meta.json"):
            continue
        path = police_root / relative
        if not path.is_file():
            raise PayloadSanitizationError(f"police manifest asset is missing: {relative}")
        public_files[relative] = _sha256(path)
    manifest["files"] = public_files
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sanitize_payload(package_root: Path) -> None:
    if not package_root.is_dir():
        raise PayloadSanitizationError(f"package root does not exist: {package_root}")
    _remove_internal_files(package_root)
    _sanitize_police_assets(package_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root", type=Path)
    args = parser.parse_args()
    try:
        sanitize_payload(args.package_root)
    except PayloadSanitizationError as error:
        parser.error(str(error))
    print(f"[OK] public HAR payload sanitized: {args.package_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
