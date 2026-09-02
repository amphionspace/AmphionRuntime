#!/usr/bin/env python3
"""Run Android frontend batch through the real APK/device path and collect logs."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_APK = ROOT / "tts/android/sample/build/outputs/apk/debug/sample-debug.apk"
DEFAULT_PACKAGE = "com.lits.tts.sample"
DEFAULT_ACTIVITY_CLASS = "com.lits.tts.sample.MainActivity"
LOG_PATTERN = re.compile(r"LitsTtsSample|LitsFrontendBatch|LitsFrontendRequest|LitsFrontendMetric|LitsFrontendDetail|LitsTn")


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--apk", default=str(DEFAULT_APK))
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--activity-class", default=DEFAULT_ACTIVITY_CLASS)
    parser.add_argument("--output", default=str(ROOT / "tts/android/build/reports/android_frontend_batch/android_frontend_batch.log"))
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()

    apk = Path(args.apk)
    if not apk.is_file():
        raise SystemExit(f"missing APK: {apk}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    activity = f"{args.package}/{args.activity_class}"

    run([args.adb, "install", "-r", str(apk)])
    run([args.adb, "shell", "am", "force-stop", args.package], check=False)
    run([args.adb, "logcat", "-c"], check=False)
    run([args.adb, "shell", "am", "start", "-n", activity])

    deadline = time.time() + args.timeout
    collected = 0
    completed = False
    with output.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [args.adb, "logcat", "-v", "time"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
        )
        try:
            assert process.stdout is not None
            while time.time() < deadline:
                line = process.stdout.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                if LOG_PATTERN.search(line):
                    handle.write(line)
                    handle.flush()
                    collected += 1
                    print(line.rstrip(), flush=True)
                    if "LitsFrontendBatch" in line and "ALL_DONE" in line:
                        completed = True
                        break
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    if not completed:
        raise SystemExit(f"frontend batch did not complete; collected={collected} log={output}")
    print(f"frontend batch completed; collected={collected} log={output}")


if __name__ == "__main__":
    main()
