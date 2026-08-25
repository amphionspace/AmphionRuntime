#!/usr/bin/env python3
"""Verify Harmony sherpa C-API exports required by the ArkTS/N-API wrapper."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REQUIRED_SYMBOLS = (
    "SherpaOnnxOnlineStreamGetEndpointReason",
    "SherpaOnnxOnlineStreamCommitRule3Segment",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--nm", type=Path, required=True)
    args = parser.parse_args()

    if not args.library.is_file():
        print(f"[ERROR] missing Harmony sherpa C-API library: {args.library}", file=sys.stderr)
        return 2
    if not args.nm.is_file():
        print(f"[ERROR] missing llvm-nm: {args.nm}", file=sys.stderr)
        return 2

    completed = subprocess.run(
        [str(args.nm), "-D", "--defined-only", str(args.library)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        print(completed.stderr.rstrip(), file=sys.stderr)
        return 2

    missing = [symbol for symbol in REQUIRED_SYMBOLS if symbol not in completed.stdout]
    if missing:
        print(
            "[ERROR] Harmony sherpa C-API library is stale; missing exports: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    print(f"[OK] Harmony sherpa C-API exports verified: {args.library}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
