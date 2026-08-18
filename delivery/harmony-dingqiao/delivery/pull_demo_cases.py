#!/usr/bin/env python3
"""Pull tester-saved ASR demo cases from a Harmony app sandbox."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess


BUNDLE = "com.amphion.asr.harmony.demo"
CASE_ROOT = "/data/storage/el2/base/files/asr-cases"


def locate_hdc() -> Path:
    deveco = Path(os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents"))
    hdc = deveco / "sdk/default/openharmony/toolchains/hdc"
    if not hdc.is_file():
        raise RuntimeError(f"missing hdc: {hdc}")
    return hdc


def list_targets(hdc: Path) -> list[str]:
    result = subprocess.run(
        [str(hdc), "list", "targets"], check=True, text=True, capture_output=True
    )
    return [line.strip() for line in result.stdout.replace("\r", "").splitlines() if line.strip()]


def select_target(hdc: Path, requested: str) -> str:
    targets = list_targets(hdc)
    if requested:
        if requested not in targets:
            raise RuntimeError(f"device is not connected: {requested}")
        return requested
    if len(targets) != 1:
        raise RuntimeError(f"expected one connected device, found {len(targets)}; pass --device")
    return targets[0]


def build_recv_command(hdc: Path, device: str, output: Path) -> list[str]:
    return [str(hdc), "-t", device, "file", "recv", "-b", BUNDLE, CASE_ROOT, str(output)]


def validate_case_tree(root: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for metadata_path in sorted(root.rglob("metadata.json")):
        case_dir = metadata_path.parent
        audio_path = case_dir / "audio.wav"
        note_path = case_dir / "note.txt"
        if not audio_path.is_file():
            raise RuntimeError(f"{case_dir.name}: missing audio.wav")
        if not note_path.is_file():
            raise RuntimeError(f"{case_dir.name}: missing note.txt")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"{case_dir.name}: invalid metadata.json: {error}") from error
        if not isinstance(metadata, dict) or not isinstance(metadata.get("caseId"), str):
            raise RuntimeError(f"{case_dir.name}: metadata.json is missing caseId")
        if metadata["caseId"] != case_dir.name:
            raise RuntimeError(f"{case_dir.name}: caseId does not match directory name")
        note = note_path.read_text(encoding="utf-8").strip()
        if metadata.get("note") != note:
            raise RuntimeError(f"{case_dir.name}: note does not match metadata.json")
        metadata["localDir"] = str(case_dir.resolve())
        metadata["audioBytes"] = audio_path.stat().st_size
        cases.append(metadata)
    if not cases:
        raise RuntimeError("no complete demo cases were pulled")
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="", help="HDC device serial; required when multiple are connected")
    parser.add_argument(
        "--output-root", type=Path, default=Path.cwd() / "demo-case-artifacts",
        help="Local parent directory for timestamped pulls",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hdc = locate_hdc()
    device = select_target(hdc, args.device)
    destination = args.output_root.expanduser().resolve() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination.mkdir(parents=True)
    result = subprocess.run(build_recv_command(hdc, device, destination), text=True, capture_output=True)
    output = result.stdout + result.stderr
    if result.returncode != 0 or "[Fail]" in output:
        raise RuntimeError(f"failed to pull demo cases: {output.strip()}")
    cases = validate_case_tree(destination)
    manifest = {
        "device": device,
        "bundle": BUNDLE,
        "remoteRoot": CASE_ROOT,
        "caseCount": len(cases),
        "cases": cases,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] pulled {len(cases)} case(s) to {destination}")
    print(f"[OK] manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
