#!/usr/bin/env python3
"""Evaluate the Harmony Dingqiao ASR police pipeline on a labelled WAV corpus."""

from __future__ import annotations

import argparse
import csv
import json
import re
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from run_device_stress import PROJECT_ROOT, REPO_ROOT, run_stress


THEMES = ("plate_number", "police_terms", "police_station")
POLICE_ASSET_ROOT = (
    REPO_ROOT / "asr" / "harmony" / "sdk-police" / "src" / "main" / "resources" /
    "rawfile" / "amphion-police"
)
PLATE_PATTERN = re.compile(r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--device", default="")
    parser.add_argument("--limit-per-category", type=int, default=0)
    parser.add_argument(
        "--pace-ms",
        type=int,
        default=20,
        help="Delay after each 20 ms PCM frame; 20 preserves realtime streaming semantics.",
    )
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--skip-build-install", action="store_true")
    args = parser.parse_args()
    if args.limit_per_category < 0 or args.pace_ms < 0:
        parser.error("--limit-per-category and --pace-ms must be non-negative")
    return args


def read_cases(root: Path) -> dict[str, dict[str, str]]:
    cases: dict[str, dict[str, str]] = {}
    for theme in THEMES:
        path = root / theme / "cases.tsv"
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                source = f"{theme}/{row['audio_path']}"
                cases[source] = {
                    "utt_id": row["utt_id"],
                    "category": theme,
                    "reference": row["ref_text"],
                    "source": source,
                }
    return cases


def select_cases(cases: dict[str, dict[str, str]], limit: int) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for case in cases.values():
        grouped[case["category"]].append(case)
    selected: list[dict[str, str]] = []
    for theme in THEMES:
        items = sorted(grouped[theme], key=lambda item: item["source"])
        if 0 < limit < len(items):
            if limit == 1:
                items = [items[len(items) // 2]]
            else:
                indexes = [round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)]
                items = [items[index] for index in indexes]
        selected.extend(items)
    return selected


def stage_cases(root: Path, selected: list[dict[str, str]], stage: Path) -> None:
    for case in selected:
        source = root / case["source"]
        destination = stage / case["source"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source)


def decode_utf16_hex(value: str) -> str:
    if not value:
        return ""
    if len(value) % 4 != 0:
        raise ValueError(f"invalid UTF-16 hex length: {len(value)}")
    data = bytearray()
    for index in range(0, len(value), 4):
        unit = int(value[index:index + 4], 16)
        data.extend((unit & 0xFF, unit >> 8))
    return data.decode("utf-16-le")


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).upper()
    return "".join(character for character in normalized if character.isalnum())


def edit_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        for column, right_character in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_character != right_character),
            ))
        previous = current
    return previous[-1]


def read_gazetteer(path: Path) -> list[str]:
    return [
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def annotate_entities(rows: list[dict[str, object]]) -> None:
    stations = read_gazetteer(POLICE_ASSET_ROOT / "police_station" / "station_gazetteer.txt")
    terms = read_gazetteer(POLICE_ASSET_ROOT / "police_terms" / "term_gazetteer.txt")
    for row in rows:
        reference = str(row["normalized_reference"])
        hypothesis = str(row["normalized_hypothesis"])
        category = str(row["category"])
        expected: list[str] = []
        if category == "plate_number":
            expected = PLATE_PATTERN.findall(reference)
        elif category == "police_station":
            matches = [station for station in stations if normalize(station) in reference]
            expected = [max(matches, key=len)] if matches else []
        elif category == "police_terms":
            expected = [term for term in terms if normalize(term) in reference]
        matched = [entity for entity in expected if normalize(entity) in hypothesis]
        row["expected_entities"] = ";".join(expected)
        row["matched_entities"] = ";".join(matched)
        row["expected_entity_count"] = len(expected)
        row["matched_entity_count"] = len(matched)


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    summaries: dict[str, object] = {}
    groups = [("overall", rows)] + [
        (theme, [row for row in rows if row["category"] == theme]) for theme in THEMES
    ]
    for name, group in groups:
        reference_chars = sum(len(str(row["normalized_reference"])) for row in group)
        edits = sum(int(row["edit_distance"]) for row in group)
        exact = sum(bool(row["exact_match"]) for row in group)
        successful = sum(row["status"] == "PASS" for row in group)
        expected_entities = sum(int(row["expected_entity_count"]) for row in group)
        matched_entities = sum(int(row["matched_entity_count"]) for row in group)
        summaries[name] = {
            "cases": len(group),
            "successful_sessions": successful,
            "exact_matches": exact,
            "sentence_accuracy": round(exact / len(group), 6) if group else 0.0,
            "character_error_rate": round(edits / reference_chars, 6) if reference_chars else 0.0,
            "reference_characters": reference_chars,
            "edit_distance": edits,
            "expected_entities": expected_entities,
            "matched_entities": matched_entities,
            "entity_recall": round(matched_entities / expected_entities, 6) if expected_entities else None,
        }
    return summaries


def evaluate(args: argparse.Namespace) -> Path:
    root = args.data_dir.expanduser().resolve()
    cases = read_cases(root)
    selected = select_cases(cases, args.limit_per_category)
    output_root = PROJECT_ROOT / "build" / "police-eval" / "device-runs"
    with tempfile.TemporaryDirectory(prefix="harmony-police-eval-") as temporary:
        stage = Path(temporary)
        stage_cases(root, selected, stage)
        stress_args = SimpleNamespace(
            data_dir=stage,
            target_speaker_manifest=None,
            expected_tail_manifest=None,
            mode="paced" if args.pace_ms > 0 else "burst",
            cycles=len(selected),
            files=0,
            settle_ms=0,
            pace_ms=args.pace_ms,
            timeout=args.timeout,
            sample_interval=1.0,
            post_run_observe=0.0,
            speaker_vad_threshold=None,
            skip_target_content_check=False,
            max_rss_growth_mb=1024.0,
            max_thread_growth=32,
            max_empty_final_rate=1.0,
            skip_build_install=args.skip_build_install,
            installed_package=False,
            device=args.device,
            output_root=output_root,
        )
        artifact_dir = run_stress(stress_args)

    mapping = {
        item["id"]: item for item in json.loads((artifact_dir / "payload" / "corpus.json").read_text())
    }
    stress_report = json.loads((artifact_dir / "report.json").read_text())
    rows: list[dict[str, object]] = []
    for cycle in stress_report["cycles"]:
        source = str(mapping[cycle["id"]]["source"])
        case = cases[source]
        hypothesis = decode_utf16_hex(cycle.get("resultHex", ""))
        normalized_reference = normalize(case["reference"])
        normalized_hypothesis = normalize(hypothesis)
        distance = edit_distance(normalized_reference, normalized_hypothesis)
        rows.append({
            **case,
            "status": cycle["status"],
            "hypothesis": hypothesis,
            "normalized_reference": normalized_reference,
            "normalized_hypothesis": normalized_hypothesis,
            "edit_distance": distance,
            "exact_match": normalized_reference == normalized_hypothesis,
            "elapsed_ms": int(cycle["elapsedMs"]),
        })

    annotate_entities(rows)
    summary = summarize(rows)
    report = {
        "device_run_id": stress_report["run_id"],
        "corpus_root": str(root),
        "selection": {
            "limit_per_category": args.limit_per_category,
            "selected_cases": len(selected),
            "available_cases": len(cases),
        },
        "metrics": summary,
        "rows": rows,
    }
    report_path = artifact_dir / "police-evaluation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (artifact_dir / "police-results.tsv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(rows[0])
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    for name, metrics in summary.items():
        entity_recall = metrics["entity_recall"]
        entity_text = f" entityRecall={entity_recall:.2%}" if entity_recall is not None else ""
        print(
            f"[{name}] cases={metrics['cases']} sessions={metrics['successful_sessions']} "
            f"sentenceAccuracy={metrics['sentence_accuracy']:.2%} "
            f"CER={metrics['character_error_rate']:.2%}{entity_text}"
        )
    print(f"[INFO] police evaluation: {report_path}")
    return report_path


if __name__ == "__main__":
    evaluate(parse_args())
