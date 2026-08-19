#!/usr/bin/env python3
"""Compare FULL and pruning-candidate outputs on synthetic general-domain collision audio."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
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


def normalize(text: str) -> str:
    return re.sub(r"[\W_]", "", text, flags=re.UNICODE).casefold()


def valid(row: dict[str, str]) -> bool:
    return row["status"] == "OK" and int(row["final_count"]) >= 1 and not row["errors"].strip()


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
    cases: list[dict[str, object]] = []
    for asset in sorted(manifest):
        item = manifest[asset]
        before = full[asset]
        after = prune[asset]
        expected = normalize(item["reference_text"])
        full_exact = valid(before) and normalize(before["text"]) == expected
        prune_exact = valid(after) and normalize(after["text"]) == expected
        changed = (
            before["status"] != after["status"]
            or before["final_count"] != after["final_count"]
            or before["text"] != after["text"]
        )
        category = (
            "regressed"
            if full_exact and not prune_exact
            else "corrected"
            if not full_exact and prune_exact
            else "changed_same_exact_state"
            if changed
            else "unchanged"
        )
        counts["total"] += 1
        counts["full_exact"] += int(full_exact)
        counts["prune_exact"] += int(prune_exact)
        counts[category] += 1
        cases.append(
            {
                "asset_file": asset,
                "id": item["id"],
                "reference_text": item["reference_text"],
                "full_text": before["text"],
                "prune_text": after["text"],
                "full_exact": full_exact,
                "prune_exact": prune_exact,
                "category": category,
            }
        )

    summary = {
        "schema_version": 1,
        "source": "synthetic_tingting_voice_smoke",
        "total": counts["total"],
        "full_exact": counts["full_exact"],
        "prune_exact": counts["prune_exact"],
        "regressed": counts["regressed"],
        "corrected": counts["corrected"],
        "changed_same_exact_state": counts["changed_same_exact_state"],
        "unchanged": counts["unchanged"],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_tsv(
        args.output_dir / "cases.tsv",
        [
            "asset_file",
            "id",
            "reference_text",
            "full_text",
            "prune_text",
            "full_exact",
            "prune_exact",
            "category",
        ],
        cases,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
