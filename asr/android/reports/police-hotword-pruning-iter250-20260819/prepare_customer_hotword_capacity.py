#!/usr/bin/env python3
"""Prepare real station-name probes plus a deterministic 200-word capacity asset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path


CUSTOMER_PROBES = [
    (1, "zh_kespeech_1028076_police_station_v2_3_ref1"),
    (25, "zh_kespeech_1018898_police_station_v2_149_ref2"),
    (48, "zh_kespeech_1023148_police_station_v2_175_ref2"),
    (49, "zh_kespeech_1028470_police_station_v2_54_ref1"),
    (50, "zh_kespeech_1015079_police_station_v2_55_ref1"),
    (51, "zh_kespeech_1008572_police_station_v2_193_ref1"),
    (52, "zh_kespeech_1024348_police_station_v2_57_ref2"),
    (75, "zh_kespeech_1014342_police_station_v2_80_ref1"),
    (98, "zh_kespeech_1015079_police_station_v2_130_ref2"),
    (99, "zh_kespeech_1028662_police_station_v2_144_ref2"),
    (100, "zh_kespeech_1011876_police_station_v2_166_ref2"),
    (101, "zh_kespeech_1000407_police_station_v2_171_ref2"),
]

FULL_CONTROLS = [
    "zh_kespeech_1013357_police_station_v2_1_ref1",
    "zh_kespeech_1008022_police_station_v2_2_ref1",
]

FULL_DOMAIN_COUNTS = {"terms": 355, "plate": 6, "station": 10}
CUSTOMER_PREFIX_COUNTS = (50, 100, 101, 200)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ordered_lines_sha256(lines: list[str]) -> str:
    """Match the device runner's UTF-8, newline-terminated list fingerprint."""
    payload = "" if not lines else "\n".join(lines) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--station-root", type=Path, required=True)
    parser.add_argument("--gazetteer", type=Path, required=True)
    parser.add_argument("--full-hotwords-json", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    cases_path = args.station_root / "cases.tsv"
    with cases_path.open(encoding="utf-8", newline="") as stream:
        cases = list(csv.DictReader(stream, delimiter="\t"))
    gazetteer = [line.strip() for line in args.gazetteer.read_text(encoding="utf-8").splitlines() if line.strip()]
    hotwords_data = json.loads(args.full_hotwords_json.read_text(encoding="utf-8"))
    actual_domain_counts = {
        domain: len(hotwords_data.get(domain, [])) for domain in FULL_DOMAIN_COUNTS
    }
    if actual_domain_counts != FULL_DOMAIN_COUNTS:
        raise SystemExit(
            f"expected FULL domain counts {FULL_DOMAIN_COUNTS}, got {actual_domain_counts}"
        )
    full_hotwords = {
        word.strip()
        for domain in ("terms", "plate", "station")
        for word in hotwords_data[domain]
        if word.strip()
    }
    if len(full_hotwords) != 370:
        raise SystemExit(f"expected 370 effective FULL hotwords, got {len(full_hotwords)}")

    case_by_utt = {row["utt_id"]: row for row in cases}
    station_by_utt: dict[str, str] = {}
    first_seen: list[str] = []
    seen: set[str] = set()
    for row in cases:
        matches = [station for station in gazetteer if station in row["text"]]
        if not matches:
            raise SystemExit(f"no station match for {row['utt_id']}: {row['text']}")
        longest = max(len(station) for station in matches)
        winners = [station for station in matches if len(station) == longest]
        if len(winners) != 1:
            raise SystemExit(f"ambiguous longest station for {row['utt_id']}: {winners}")
        station = winners[0]
        station_by_utt[row["utt_id"]] = station
        if station not in seen:
            seen.add(station)
            first_seen.append(station)

    customer_words = [station for station in first_seen if station not in full_hotwords]
    if len(customer_words) != 101:
        raise SystemExit(f"expected 101 real customer station words, got {len(customer_words)}")
    for index, utt_id in CUSTOMER_PROBES:
        station = station_by_utt[utt_id]
        if customer_words[index - 1] != station:
            raise SystemExit(
                f"probe mismatch at index={index}: list={customer_words[index - 1]} row={station} utt={utt_id}"
            )

    filler_words = [f"容量占位词{index:03d}" for index in range(1, 100)]
    all_words = customer_words + filler_words
    if len(all_words) != 200 or len(set(all_words)) != 200:
        raise SystemExit("capacity hotword list must contain exactly 200 unique entries")
    if set(all_words) & full_hotwords:
        raise SystemExit("capacity hotword list overlaps FULL built-ins")

    if args.output_root.exists():
        if not args.output_root.is_dir():
            raise SystemExit(f"output root is not a directory: {args.output_root}")
        if any(args.output_root.iterdir()):
            raise SystemExit(f"output root must be empty: {args.output_root}")
    else:
        args.output_root.mkdir(parents=True)
    wav_dir = args.output_root / "wav16k"
    wav_dir.mkdir()
    hotword_asset = wav_dir / "customer_hotwords_200.txt"
    hotword_asset.write_text("\n".join(all_words) + "\n", encoding="utf-8")

    manifest_rows: list[dict[str, str]] = []
    selected: list[tuple[str, str, int | None]] = [
        (utt_id, "customer", index) for index, utt_id in CUSTOMER_PROBES
    ] + [(utt_id, "full_control", None) for utt_id in FULL_CONTROLS]
    for utt_id, role, customer_index in selected:
        if utt_id not in case_by_utt:
            raise SystemExit(f"selected utterance is absent from cases.tsv: {utt_id}")
        row = case_by_utt[utt_id]
        station = station_by_utt[utt_id]
        source = args.station_root / row["audio_path"]
        if not source.is_file():
            raise SystemExit(f"selected source WAV is missing: {source}")
        if role == "full_control" and station not in full_hotwords:
            raise SystemExit(f"FULL control is not a FULL hotword: {station}")
        asset_name = (
            f"capacity_customer_{customer_index:03d}.wav"
            if customer_index is not None
            else f"capacity_control_{len([r for r in manifest_rows if r['role'] == 'full_control']) + 1:02d}.wav"
        )
        output = wav_dir / asset_name
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            check=True,
        )
        duration = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        manifest_rows.append(
            {
                "asset_file": asset_name,
                "role": role,
                "customer_index": "" if customer_index is None else str(customer_index),
                "expected_station": station,
                "reference_text": row["text"],
                "source_file": row["audio_path"],
                "source_sha256": sha256(source),
                "sha256": sha256(output),
                "duration_s": duration,
            }
        )

    manifest_path = args.output_root / "manifest.tsv"
    with manifest_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(manifest_rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(manifest_rows)
    metadata = {
        "schema_version": 2,
        "full_effective_hotword_count": 370,
        "full_domain_counts": actual_domain_counts,
        "real_customer_hotword_count": 101,
        "capacity_filler_count": 99,
        "total_asset_hotword_count": 200,
        "hotword_asset_sha256": sha256(hotword_asset),
        "customer_hotword_prefix_sha256": {
            str(count): ordered_lines_sha256(all_words[:count])
            for count in CUSTOMER_PREFIX_COUNTS
        },
        "probe_count": len(manifest_rows),
        "source_cases_sha256": sha256(cases_path),
        "source_gazetteer_sha256": sha256(args.gazetteer),
        "source_full_hotwords_sha256": sha256(args.full_hotwords_json),
        "manifest_sha256": sha256(manifest_path),
    }
    (args.output_root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
