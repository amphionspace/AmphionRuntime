#!/usr/bin/env python3
"""Select the improved-v3 stability suite from the improved-v2 corpus.

The v2 full corpus is intentionally broad, but it is too expensive for routine
phone runs because repeat/loop and long-text cases dominate wall time.  This
selector keeps category and operation coverage while capping those expensive
families to a small representative set.
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "tts" / "android" / "testdata" / "dingqiao_batch_cases"
SOURCE_JSONL_PATH = OUT_DIR / "android_v3_sdk_stability_1000_cases_improved.jsonl"
V3_JSONL_PATH = OUT_DIR / "android_v3_sdk_stability_424_cases_improved_v3.jsonl"
V3_SUMMARY_PATH = OUT_DIR / "android_v3_sdk_stability_424_cases_improved_v3_summary.json"

CATEGORY_QUOTAS = {
    "smoke-api": 25,
    "engine-create-query": 35,
    "workpath-resource-load": 30,
    "lifecycle-state-machine": 40,
    "listener-callback-contract": 30,
    "request-queue-scheduler": 40,
    "streaming-config-buffering": 35,
    "playback-channel-audio-route": 25,
    "params-boundary-runtime": 30,
    "error-validation-recovery": 40,
    "memory-leak-soak": 24,
    "fd-thread-process-leak": 24,
    "longtext-tn-stability": 16,
    "stress-recovery-regression": 30,
}

EXPENSIVE_OPERATION_CAPS = {
    ("memory-leak-soak", "create-speak-shutdown-loop"): 4,
    ("memory-leak-soak", "same-engine-repeat-speak"): 4,
    ("memory-leak-soak", "longtext-repeat-loop"): 4,
    ("memory-leak-soak", "error-then-valid-loop"): 4,
    ("memory-leak-soak", "playback-repeat-loop"): 4,
    ("memory-leak-soak", "deferred-load-loop"): 4,
    ("fd-thread-process-leak", "tn-fork-loop"): 4,
    ("fd-thread-process-leak", "create-shutdown-fd-loop"): 4,
    ("fd-thread-process-leak", "streaming-pipe-loop"): 4,
    ("fd-thread-process-leak", "stderr-watcher-loop"): 4,
    ("fd-thread-process-leak", "playback-audiotrack-loop"): 4,
    ("fd-thread-process-leak", "error-path-fd-loop"): 4,
    ("longtext-tn-stability", "longtext-speak"): 16,
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def even_sample(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count >= len(rows):
        return list(rows)
    if count <= 0:
        return []
    if count == 1:
        return [rows[0]]
    indices = sorted({round(i * (len(rows) - 1) / (count - 1)) for i in range(count)})
    selected = [rows[index] for index in indices]
    cursor = 0
    while len(selected) < count:
        candidate = rows[cursor]
        if candidate not in selected:
            selected.append(candidate)
        cursor += 1
    return selected[:count]


def longtext_priority(row: dict[str, Any]) -> tuple[int, int]:
    length = len(row["text"])
    # Prefer 600/900-char rows for routine coverage, while retaining a few
    # larger anchors through even sampling after this ordering.
    if length < 1000:
        bucket = 0
    elif length < 1600:
        bucket = 1
    elif length < 2600:
        bucket = 2
    else:
        bucket = 3
    return (bucket, row.get("sourceCaseIndex", 0))


def select_longtext(rows: list[dict[str, Any]], quota: int) -> list[dict[str, Any]]:
    by_bucket: dict[str, list[dict[str, Any]]] = {
        "short": [row for row in rows if len(row["text"]) < 1000],
        "medium": [row for row in rows if 1000 <= len(row["text"]) < 1800],
        "large": [row for row in rows if 1800 <= len(row["text"]) < 3000],
        "max": [row for row in rows if len(row["text"]) >= 3000],
    }
    selected: list[dict[str, Any]] = []
    plan = [("short", 9), ("medium", 4), ("large", 2), ("max", 1)]
    for bucket_name, bucket_count in plan:
        selected.extend(even_sample(sorted(by_bucket[bucket_name], key=longtext_priority), bucket_count))
    if len(selected) != quota:
        raise AssertionError(f"longtext selected {len(selected)} / {quota}")
    return selected


def select_category(rows: list[dict[str, Any]], category: str, quota: int) -> list[dict[str, Any]]:
    if category == "longtext-tn-stability":
        return select_longtext(rows, quota)

    by_operation: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_operation.setdefault(row["operation"], []).append(row)

    operation_names = sorted(by_operation)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for operation in operation_names:
        operation_rows = by_operation[operation]
        cap = EXPENSIVE_OPERATION_CAPS.get((category, operation), len(operation_rows))
        buckets[operation] = even_sample(operation_rows, min(cap, len(operation_rows)))

    selected: list[dict[str, Any]] = []
    offsets = {operation: 0 for operation in operation_names}
    while len(selected) < quota:
        progressed = False
        for operation in operation_names:
            bucket = buckets[operation]
            offset = offsets[operation]
            if offset < len(bucket) and len(selected) < quota:
                selected.append(bucket[offset])
                offsets[operation] += 1
                progressed = True
        if not progressed:
            break

    if len(selected) != quota:
        raise AssertionError(f"{category} selected {len(selected)} / {quota}")
    return selected


def mark_v3(row: dict[str, Any], v3_index: int) -> dict[str, Any]:
    new = deepcopy(row)
    setup = dict(new.get("setup", {}))
    setup["selectedSuite"] = "improved-v3-424"
    setup["selectedSuiteIndex"] = v3_index
    setup["selectedFromCaseVersion"] = new.get("caseVersion", "")
    new["setup"] = setup
    new["caseVersion"] = "dingqiao-stability-improved-v3"
    new["notes"] = "selected-from-improved-v2-capped-repeat-longtext"
    return new


def text_bucket(length: int) -> str:
    if length >= 1000:
        return ">=1000"
    if length >= 600:
        return "600-999"
    if length >= 400:
        return "400-599"
    if length >= 200:
        return "200-399"
    if length >= 100:
        return "100-199"
    return "<100"


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, Any] = {}
    for category in sorted({row["category"] for row in rows}):
        category_rows = [row for row in rows if row["category"] == category]
        lengths = [len(row["text"]) for row in category_rows]
        by_category[category] = {
            "count": len(category_rows),
            "minTextLength": min(lengths),
            "maxTextLength": max(lengths),
            "avgTextLength": round(sum(lengths) / len(lengths), 2),
            "operations": dict(sorted(Counter(row["operation"] for row in category_rows).items())),
            "repeatOrLoopOperations": sum(
                "repeat" in row["operation"].lower() or "loop" in row["operation"].lower()
                for row in category_rows
            ),
            "longTextCases": sum(len(row["text"]) >= 600 for row in category_rows),
        }

    return {
        "total": len(rows),
        "jsonl": V3_JSONL_PATH.name,
        "sourceJsonl": SOURCE_JSONL_PATH.name,
        "caseVersion": "dingqiao-stability-improved-v3",
        "selectionPolicy": "category quotas with operation-balanced sampling; repeat/loop and longtext categories capped",
        "categoryCounts": dict(sorted(Counter(row["category"] for row in rows).items())),
        "statusCounts": dict(sorted(Counter(row["expected_status"] for row in rows).items())),
        "textLengthBuckets": dict(sorted(Counter(text_bucket(len(row["text"])) for row in rows).items())),
        "repeatOrLoopOperationCases": sum(
            "repeat" in row["operation"].lower() or "loop" in row["operation"].lower()
            for row in rows
        ),
        "longTextCasesLengthGte600": sum(len(row["text"]) >= 600 for row in rows),
        "longTextCasesLengthGte1000": sum(len(row["text"]) >= 1000 for row in rows),
        "categorySummary": by_category,
    }


def main() -> None:
    cases = load_jsonl(SOURCE_JSONL_PATH)
    by_category: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_category.setdefault(case["category"], []).append(case)

    selected: list[dict[str, Any]] = []
    for category, quota in CATEGORY_QUOTAS.items():
        selected.extend(select_category(by_category[category], category, quota))

    expected_total = sum(CATEGORY_QUOTAS.values())
    if len(selected) != expected_total:
        raise AssertionError(f"expected {expected_total} cases, got {len(selected)}")
    if len(selected) >= 500:
        raise AssertionError(f"v3 suite must stay under 500 cases, got {len(selected)}")
    ids = [row["id"] for row in selected]
    if len(ids) != len(set(ids)):
        raise AssertionError("selected suite has duplicate ids")

    v3_rows = [mark_v3(row, index) for index, row in enumerate(selected)]
    write_jsonl(V3_JSONL_PATH, v3_rows)
    V3_SUMMARY_PATH.write_text(
        json.dumps(build_summary(v3_rows), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(v3_rows)} cases")
    print(V3_JSONL_PATH)
    print(V3_SUMMARY_PATH)


if __name__ == "__main__":
    main()
