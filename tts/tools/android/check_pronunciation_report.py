#!/usr/bin/env python3
"""Gate a pronunciation summary; instrumentation OK only means collection finished."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def report_matches_all_cases(summary: dict[str, object], expected_total: int) -> bool:
    return (
        expected_total > 0
        and summary.get("total") == expected_total
        and summary.get("pass") == expected_total
        and summary.get("fail") == 0
        and summary.get("error") == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-total", type=int, required=True)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    passed = report_matches_all_cases(summary, args.expected_total)
    status = "PASS" if passed else "FAIL"
    print(
        f"{status}: expected={args.expected_total} total={summary.get('total')} "
        f"matched={summary.get('pass')} mismatched={summary.get('fail')} errors={summary.get('error')}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
