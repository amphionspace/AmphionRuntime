#!/usr/bin/env python3
"""Archive the complete AGC release matrix and bind it to the delivery ledger."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARCHIVER = ROOT / "delivery/harmony-dingqiao/delivery/archive_release_gate_evidence.py"
TRACKER = ROOT / "tools/delivery/asr_release_tracker.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--release-artifact", type=Path, required=True)
    parser.add_argument("--delivery-har", type=Path, required=True)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--delivered-at", required=True)
    parser.add_argument("--finish-compat-summary", type=Path, required=True)
    parser.add_argument("--build-identity", type=Path, required=True)
    parser.add_argument("--android-results-root", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("release artifact", args.release_artifact),
        ("delivery HAR", args.delivery_har),
        ("Android summary", args.android_results_root / "android-tests.json"),
    ):
        if not path.is_file():
            parser.error(f"{label} does not exist: {path}")
    if args.provenance is None or not args.provenance.is_file():
        parser.error(f"provenance does not exist: {args.provenance}")

    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    command = [
        sys.executable,
        str(ARCHIVER),
        "--raw-root", str(args.raw_root),
        "--output", str(args.output),
        "--release-version", args.release_version,
        "--source-commit", source_commit,
        "--artifact-name", args.release_artifact.name,
        "--artifact-sha256", sha256(args.release_artifact),
        "--artifact-size-bytes", str(args.release_artifact.stat().st_size),
        "--har-sha256", sha256(args.delivery_har),
        "--android-summary", str(args.android_results_root / "android-tests.json"),
        "--android-results-root", str(args.android_results_root),
        "--finish-compat-summary", str(args.finish_compat_summary),
        "--build-identity", str(args.build_identity),
    ]
    command.extend(("--provenance-sha256", sha256(args.provenance)))
    subprocess.run(command, cwd=ROOT, check=True)
    report = args.output / "report.json"
    subprocess.run(
        [
            sys.executable,
            str(TRACKER),
            "record-evidence",
            "--platform", "harmony",
            "--version", args.release_version,
            "--source-commit", source_commit,
            "--delivered-at", args.delivered_at,
            "--artifact", str(args.release_artifact),
            "--report", str(report),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(TRACKER), "verify-evidence"], cwd=ROOT, check=True
    )
    print(f"[OK] immutable AGC release evidence attached and verified: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
