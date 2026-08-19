#!/usr/bin/env python3
"""Compare FULL and pruning-candidate plate/station device reports."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def keyed(path: Path, key: str) -> dict[str, dict[str, str]]:
    rows = read_tsv(path)
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise SystemExit(f"duplicate {key} values in {path}")
    return result


def compact(text: str) -> str:
    return re.sub(r"[\s。！？!?,，、；;：:\-]", "", text).casefold()


def valid(row: dict[str, str]) -> bool:
    return row["status"] == "OK" and row["final_count"] == "1" and not row["errors"].strip()


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--prune", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest = keyed(args.manifest, "asset_file")
    full = keyed(args.full, "file")
    prune = keyed(args.prune, "file")
    if set(manifest) != set(full) or set(manifest) != set(prune):
        raise SystemExit("manifest/FULL/PRUNE asset sets do not match")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    per_group: dict[str, Counter[str]] = defaultdict(Counter)
    cases: list[dict[str, object]] = []

    for asset in sorted(manifest):
        item = manifest[asset]
        before = full[asset]
        after = prune[asset]
        expected = compact(item["expected_term"])
        full_hit = valid(before) and expected in compact(before["text"])
        prune_hit = valid(after) and expected in compact(after["text"])
        changed = before["text"] != after["text"] or before["status"] != after["status"]
        category = (
            "regressed"
            if full_hit and not prune_hit
            else "corrected"
            if not full_hit and prune_hit
            else "changed_same_hit_state"
            if changed
            else "unchanged"
        )
        counts["total"] += 1
        counts["full_hit"] += int(full_hit)
        counts["prune_hit"] += int(prune_hit)
        counts[category] += 1
        group = item["group"]
        per_group[group]["total"] += 1
        per_group[group]["full_hit"] += int(full_hit)
        per_group[group]["prune_hit"] += int(prune_hit)
        per_group[group]["regressed"] += int(category == "regressed")
        cases.append(
            {
                "asset_file": asset,
                "group": group,
                "expected_term": item["expected_term"],
                "full_text": before["text"],
                "prune_text": after["text"],
                "full_hit": full_hit,
                "prune_hit": prune_hit,
                "category": category,
            }
        )

    summary = {
        "schema_version": 1,
        "total": counts["total"],
        "full_hit": counts["full_hit"],
        "prune_hit": counts["prune_hit"],
        "regressed": counts["regressed"],
        "corrected": counts["corrected"],
        "changed_same_hit_state": counts["changed_same_hit_state"],
        "unchanged": counts["unchanged"],
        "per_group": {group: dict(values) for group, values in sorted(per_group.items())},
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_tsv(
        args.output_dir / "cases.tsv",
        ["asset_file", "group", "expected_term", "full_text", "prune_text", "full_hit", "prune_hit", "category"],
        cases,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
