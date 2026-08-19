#!/usr/bin/env python3
"""Score FULL versus a pruning candidate against the prepared UI30 manifest."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


TRAILING_PUNCTUATION = "。！？!?,，、；;：:"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def keyed(path: Path, key: str) -> dict[str, dict[str, str]]:
    rows = read_tsv(path)
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise SystemExit(f"duplicate {key} values in {path}")
    return result


def normalize_sentence(text: str) -> str:
    return text.strip().rstrip(TRAILING_PUNCTUATION).strip().casefold()


def compact(text: str) -> str:
    return re.sub(r"[\s。！？!?,，、；;：:]", "", text).casefold()


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
    per_term: dict[str, Counter[str]] = defaultdict(Counter)
    cases: list[dict[str, object]] = []

    for asset in sorted(manifest):
        item = manifest[asset]
        before = full[asset]
        after = prune[asset]
        term = item["expected_term"]
        full_valid = valid(before)
        prune_valid = valid(after)
        full_term_hit = full_valid and compact(term) in compact(before["text"])
        prune_term_hit = prune_valid and compact(term) in compact(after["text"])
        full_sentence_exact = full_valid and normalize_sentence(before["text"]) == normalize_sentence(
            item["reference_text"]
        )
        prune_sentence_exact = prune_valid and normalize_sentence(after["text"]) == normalize_sentence(
            item["reference_text"]
        )
        changed = (
            before["status"], before["final_count"], before["text"], before["errors"]
        ) != (
            after["status"], after["final_count"], after["text"], after["errors"]
        )
        if full_term_hit and not prune_term_hit:
            category = "term_regressed"
        elif not full_term_hit and prune_term_hit:
            category = "term_corrected"
        elif full_term_hit and prune_term_hit:
            category = "term_stable_hit"
        else:
            category = "term_stable_miss"
        counts[category] += 1
        counts["changed" if changed else "unchanged"] += 1
        counts["full_sentence_exact"] += int(full_sentence_exact)
        counts["prune_sentence_exact"] += int(prune_sentence_exact)
        term_counts = per_term[term]
        term_counts["total"] += 1
        term_counts["full_hit"] += int(full_term_hit)
        term_counts["prune_hit"] += int(prune_term_hit)

        cases.append(
            {
                "asset_file": asset,
                "expected_term": term,
                "reference_text": item["reference_text"],
                "full_status": before["status"],
                "full_final_count": before["final_count"],
                "full_text": before["text"],
                "full_term_hit": str(bool(full_term_hit)).lower(),
                "full_sentence_exact": str(bool(full_sentence_exact)).lower(),
                "prune_status": after["status"],
                "prune_final_count": after["final_count"],
                "prune_text": after["text"],
                "prune_term_hit": str(bool(prune_term_hit)).lower(),
                "prune_sentence_exact": str(bool(prune_sentence_exact)).lower(),
                "changed": str(changed).lower(),
                "category": category,
            }
        )

    per_term_rows = [
        {
            "expected_term": term,
            "total": values["total"],
            "full_hit": values["full_hit"],
            "prune_hit": values["prune_hit"],
            "delta": values["prune_hit"] - values["full_hit"],
        }
        for term, values in sorted(per_term.items())
    ]
    write_tsv(args.output_dir / "cases.tsv", list(cases[0]), cases)
    write_tsv(
        args.output_dir / "per_term.tsv",
        ["expected_term", "total", "full_hit", "prune_hit", "delta"],
        per_term_rows,
    )
    summary = {
        "schema_version": 1,
        "total": len(cases),
        "full_term_hit": sum(row["full_term_hit"] == "true" for row in cases),
        "prune_term_hit": sum(row["prune_term_hit"] == "true" for row in cases),
        "full_sentence_exact": counts["full_sentence_exact"],
        "prune_sentence_exact": counts["prune_sentence_exact"],
        "changed": counts["changed"],
        "unchanged": counts["unchanged"],
        "term_regressed": counts["term_regressed"],
        "term_corrected": counts["term_corrected"],
        "term_stable_hit": counts["term_stable_hit"],
        "term_stable_miss": counts["term_stable_miss"],
        "terms_with_negative_delta": [
            row["expected_term"] for row in per_term_rows if int(row["delta"]) < 0
        ],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
