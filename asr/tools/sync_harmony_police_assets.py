#!/usr/bin/env python3
"""Synchronize Android police V2 data into the Harmony HAR rawfile bundle."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import argparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_ROOT = REPO_ROOT / "asr/android/sdk-police/src/main"
HARMONY_ROOT = REPO_ROOT / "asr/harmony/sdk-police/src/main/resources/rawfile/amphion-police"

ASSET_DIRS = ("plate", "police_station", "police_terms")
HOTWORD_SOURCES = {
    "plate": ANDROID_ROOT / "java/com/amphion/police/plate/PlateHotwords.kt",
    "station": ANDROID_ROOT / "java/com/amphion/police/station/PoliceStationHotwords.kt",
    "terms": ANDROID_ROOT / "java/com/amphion/police/terms/PoliceTermsHotwords.kt",
}


def extract_preset(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    match = re.search(r"val PRESET: List<String> = listOf\((.*?)\n    \)", source, re.S)
    if match is None:
        raise SystemExit(f"PRESET list not found: {path}")
    return re.findall(r'^\s*"((?:[^"\\]|\\.)*)",?\s*(?://.*)?$', match.group(1), re.M)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_hotwords() -> dict[str, list[str]]:
    return {name: extract_preset(path) for name, path in HOTWORD_SOURCES.items()}


def sync() -> None:
    if HARMONY_ROOT.exists():
        shutil.rmtree(HARMONY_ROOT)
    HARMONY_ROOT.mkdir(parents=True)
    for directory in ASSET_DIRS:
        source_dir = ANDROID_ROOT / "assets" / directory
        destination_dir = HARMONY_ROOT / directory
        shutil.copytree(source_dir, destination_dir)
    hotwords = expected_hotwords()
    hotwords_path = HARMONY_ROOT / "hotwords.json"
    hotwords_path.write_text(
        json.dumps(hotwords, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    write_manifest(hotwords)
    print(f"[OK] synchronized police assets to {HARMONY_ROOT}")


def build_manifest(hotwords: dict[str, list[str]]) -> dict[str, object]:
    files: dict[str, str] = {}
    for path in sorted(HARMONY_ROOT.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files[path.relative_to(HARMONY_ROOT).as_posix()] = sha256(path)

    return {
        "schema_version": 1,
        "source": "asr/android/sdk-police/src/main",
        "files": files,
        "hotword_counts": {name: len(words) for name, words in hotwords.items()},
    }


def write_manifest(hotwords: dict[str, list[str]]) -> None:
    manifest = build_manifest(hotwords)
    (HARMONY_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def check() -> None:
    failures: list[str] = []
    for directory in ASSET_DIRS:
        source_dir = ANDROID_ROOT / "assets" / directory
        destination_dir = HARMONY_ROOT / directory
        source_files = {path.name for path in source_dir.iterdir() if path.is_file()}
        destination_files = {path.name for path in destination_dir.iterdir() if path.is_file()}
        if source_files != destination_files:
            failures.append(f"{directory}: file set differs")
        for name in sorted(source_files & destination_files):
            if (source_dir / name).read_bytes() != (destination_dir / name).read_bytes():
                failures.append(f"{directory}/{name}: content differs")

    hotwords = expected_hotwords()
    expected_json = json.dumps(hotwords, ensure_ascii=False, indent=2) + "\n"
    hotwords_path = HARMONY_ROOT / "hotwords.json"
    if not hotwords_path.is_file() or hotwords_path.read_text(encoding="utf-8") != expected_json:
        failures.append("hotwords.json: generated hotwords differ")
    expected_manifest = build_manifest(hotwords)
    manifest_path = HARMONY_ROOT / "manifest.json"
    actual_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    if actual_manifest != expected_manifest:
        failures.append("manifest.json: hashes or counts differ")
    if failures:
        raise SystemExit("[ERROR] Harmony police assets are stale:\n- " + "\n- ".join(failures))
    print(f"[OK] Harmony police assets match Android ({len(expected_manifest['files'])} files)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail instead of updating stale assets")
    args = parser.parse_args()
    check() if args.check else sync()


if __name__ == "__main__":
    main()
