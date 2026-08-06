#!/usr/bin/env python3
"""Compare Android frontend batch tokenIds between two device logs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CASE_START_RE = re.compile(r"LitsFrontendBatch.*CASE_START .*case_id=(\S+).* text=(.*)$")
CASE_DONE_RE = re.compile(r"LitsFrontendBatch.*CASE_DONE .*case_id=(\S+)")
CASE_ERROR_RE = re.compile(r"LitsFrontendBatch.*CASE_ERROR .*case_id=(\S+).*message=(.*)$")
SEGMENT_RE = re.compile(r"LitsFrontendRequest.*stream segment .*tokenCount=(\d+) segment=(.*?) tokenIds=([0-9 ]+)$")


def parse_log(path: Path) -> dict[str, dict[str, object]]:
    cases: dict[str, dict[str, object]] = {}
    active_case: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if match := CASE_START_RE.search(raw):
            active_case = match.group(1)
            cases.setdefault(active_case, {"case_id": active_case, "text": match.group(2), "segments": [], "token_ids": []})
            continue
        if active_case and (match := SEGMENT_RE.search(raw)):
            token_ids = [int(value) for value in match.group(3).split() if value]
            row = cases.setdefault(active_case, {"case_id": active_case, "text": "", "segments": [], "token_ids": []})
            row["segments"].append({"segment": match.group(2), "token_count": int(match.group(1)), "token_ids": token_ids})
            row["token_ids"].extend(token_ids)
            continue
        if match := CASE_DONE_RE.search(raw):
            case_id = match.group(1)
            cases.setdefault(case_id, {"case_id": case_id, "text": "", "segments": [], "token_ids": []})["status"] = "done"
            if active_case == case_id:
                active_case = None
            continue
        if match := CASE_ERROR_RE.search(raw):
            case_id = match.group(1)
            row = cases.setdefault(case_id, {"case_id": case_id, "text": "", "segments": [], "token_ids": []})
            row["status"] = "error"
            row["error"] = match.group(2)
            if active_case == case_id:
                active_case = None
    return cases


def first_diff(left: list[int], right: list[int]) -> int | None:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline-log", type=Path, required=True)
    parser.add_argument("--candidate-log", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    manifest_ids = []
    for line in args.manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            manifest_ids.append(json.loads(line)["case_id"])

    baseline = parse_log(args.baseline_log)
    candidate = parse_log(args.candidate_log)

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    compared = missing_baseline = missing_candidate = mismatched = errors = matched = 0
    with args.output_jsonl.open("w", encoding="utf-8") as handle:
        for case_id in manifest_ids:
            left = baseline.get(case_id)
            right = candidate.get(case_id)
            row: dict[str, object] = {"case_id": case_id}
            if not left:
                missing_baseline += 1
                row["status"] = "missing_baseline"
            elif not right:
                missing_candidate += 1
                row["status"] = "missing_candidate"
            elif left.get("status") == "error" or right.get("status") == "error":
                errors += 1
                row["status"] = "error"
                row["baseline_error"] = left.get("error", "")
                row["candidate_error"] = right.get("error", "")
            else:
                compared += 1
                left_ids = left.get("token_ids", [])
                right_ids = right.get("token_ids", [])
                diff_at = first_diff(left_ids, right_ids)
                row.update(
                    {
                        "baseline_token_count": len(left_ids),
                        "candidate_token_count": len(right_ids),
                        "baseline_segments": len(left.get("segments", [])),
                        "candidate_segments": len(right.get("segments", [])),
                    },
                )
                if diff_at is None:
                    matched += 1
                    row["status"] = "match"
                else:
                    mismatched += 1
                    row["status"] = "mismatch"
                    row["first_diff_index"] = diff_at
                    row["baseline_window"] = left_ids[max(0, diff_at - 8): diff_at + 8]
                    row["candidate_window"] = right_ids[max(0, diff_at - 8): diff_at + 8]
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "manifest_cases": len(manifest_ids),
        "compared": compared,
        "matched": matched,
        "mismatched": mismatched,
        "missing_baseline": missing_baseline,
        "missing_candidate": missing_candidate,
        "errors": errors,
        "baseline_log": str(args.baseline_log),
        "candidate_log": str(args.candidate_log),
        "diff_jsonl": str(args.output_jsonl),
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
