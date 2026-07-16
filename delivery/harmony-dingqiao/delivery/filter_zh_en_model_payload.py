#!/usr/bin/env python3
"""Remove non-zh-en ASR bundles from an extracted Harmony HAR model payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil


REQUIRED_BUNDLES = {
    "zh-en/v1",
    "punct-zhen/v1",
    "itn-zh/v1",
    "vad/v1",
}


class PayloadFilterError(RuntimeError):
    pass


def filter_payload(model_root: Path) -> None:
    rawfile_root = model_root.parent
    for sibling in rawfile_root.iterdir():
        if sibling == model_root:
            continue
        if sibling.name.startswith("amphion-models") or _is_metadata(sibling.name):
            if sibling.is_dir():
                shutil.rmtree(sibling)
            else:
                sibling.unlink()

    manifest_path = model_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PayloadFilterError(f"invalid model manifest: {manifest_path}") from error
    bundles = manifest.get("bundles")
    if not isinstance(bundles, dict):
        raise PayloadFilterError("model manifest bundles must be an object")
    missing = sorted(REQUIRED_BUNDLES - set(bundles))
    if missing:
        raise PayloadFilterError(f"missing required bundle: {missing[0]}")

    for bundle in bundles:
        path = PurePosixPath(bundle)
        if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
            raise PayloadFilterError(f"unsafe model bundle path: {bundle}")
    manifest["bundles"] = {
        name: bundles[name]
        for name in bundles
        if name in REQUIRED_BUNDLES
    }

    retained_directories = {PurePosixPath(bundle).parts[0] for bundle in REQUIRED_BUNDLES}
    for child in model_root.iterdir():
        if child.is_dir() and child.name not in retained_directories:
            shutil.rmtree(child)
    for path in sorted(model_root.rglob("*"), reverse=True):
        if path.is_file() and _is_metadata(path.name):
            path.unlink()
    for bundle in REQUIRED_BUNDLES:
        if not (model_root / bundle).is_dir():
            raise PayloadFilterError(f"missing required bundle directory: {bundle}")

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _is_metadata(name: str) -> bool:
    return name in {".DS_Store", ".gitkeep"} or name.startswith("._")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_root", type=Path)
    args = parser.parse_args()
    try:
        filter_payload(args.model_root)
    except PayloadFilterError as error:
        parser.error(str(error))
    print(f"[OK] retained zh-en ASR model payload: {args.model_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
