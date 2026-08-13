#!/usr/bin/env python3
"""Generate the Android release-test summary consumed by the evidence archiver."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


SUITES = {
    ("sdk", "debug"): "sdk/build/test-results/testDebugUnitTest",
    ("sdk", "release"): "sdk/build/test-results/testReleaseUnitTest",
    ("sdk-dingqiao", "debug"): "sdk-dingqiao/build/test-results/testDebugUnitTest",
    ("sdk-dingqiao", "release"): "sdk-dingqiao/build/test-results/testReleaseUnitTest",
}


def summarize(results_root: Path, source_commit: str, sherpa_commit: str) -> dict:
    suites = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for (module, variant), relative in SUITES.items():
        files = sorted((results_root / relative).glob("TEST-*.xml"))
        if not files:
            raise ValueError(f"missing Android test XML for {module} {variant}")
        current = {field: 0 for field in totals}
        for path in files:
            root = ET.parse(path).getroot()
            if root.tag != "testsuite":
                raise ValueError(f"invalid Android test XML root: {path}")
            for field in current:
                current[field] += int(root.attrib.get(field, "0"))
        suites.append({"module": module, "variant": variant, **current})
        for field, value in current.items():
            totals[field] += value
    return {
        "overall_status": (
            "PASS" if totals["failures"] == totals["errors"] == totals["skipped"] == 0 else "FAIL"
        ),
        "source_commit": source_commit,
        "sherpa_submodule_commit": sherpa_commit,
        "rerun_tasks": True,
        "suites": suites,
        "total_tests": totals["tests"],
        "total_failures": totals["failures"],
        "total_errors": totals["errors"],
        "total_skipped": totals["skipped"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--sherpa-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = summarize(args.results_root, args.source_commit, args.sherpa_commit)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if summary["overall_status"] != "PASS":
        print(f"[ERROR] Android release tests are not clean: {args.output}")
        return 1
    print(f"[OK] Android release test summary: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
