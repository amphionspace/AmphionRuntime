#!/usr/bin/env python3
"""Generate fixed Chinese distractor-hotword cases for false-replacement testing."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
DEFAULT_OUTPUT = SCRIPT_DIR / "fixtures" / "hotword_negative_200.jsonl"
PINYIN = REPO_ROOT / "asr/harmony/sdk-police/src/main/resources/rawfile/amphion-police/lac/v1/pinyin.tsv"
SEED = 20260820
COUNT = 200


def rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def load_pinyin() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in PINYIN.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and len(parts[0]) == 1 and parts[1].strip():
            result.setdefault(parts[0], parts[1].strip().lower())
    return result


def signature(text: str, pinyin: dict[str, str]) -> str | None:
    values = [pinyin.get(char) for char in text]
    if any(value is None for value in values):
        return None
    return "|".join(value for value in values if value is not None)


def artifact_path(entry: dict[str, object], name: str, data_asr: Path) -> Path:
    artifacts = {str(item["name"]): item for item in entry["artifacts"]}
    return data_asr / str(artifacts[name]["relative_path"])


def relative_audio(source: str) -> str:
    prefix = "/ai_sds_wuzz/DATA_ASR/"
    if not source.startswith(prefix):
        raise ValueError(f"unexpected recording source root: {source}")
    return source[len(prefix):]


def hotword_datasets(data_root: Path) -> list[dict[str, object]]:
    catalog = data_root / "bundle-metadata/catalog.jsonl"
    result = []
    for line in catalog.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if "asr_hotwords" in entry.get("tasks", []) and "zh" in entry.get("languages", []):
            split = entry.get("splits", {}).get("test", {})
            if split.get("recordings_artifact") and split.get("supervisions_artifact"):
                result.append(entry)
    return result


def generate(data_root: Path) -> list[dict[str, object]]:
    data_asr = data_root / "DATA_ASR"
    pinyin = load_pinyin()
    datasets = hotword_datasets(data_root)
    targets_by_signature: dict[str, set[str]] = defaultdict(set)
    for dataset in datasets:
        split = dataset["splits"]["test"]
        supervision_path = artifact_path(dataset, str(split["supervisions_artifact"]), data_asr)
        for supervision in rows(supervision_path):
            custom = supervision.get("custom")
            hotwords = custom.get("hotwords", []) if isinstance(custom, dict) else []
            for value in hotwords if isinstance(hotwords, list) else []:
                word = str(value).strip()
                if 3 <= len(word) <= 6:
                    value_signature = signature(word, pinyin)
                    if value_signature is not None:
                        targets_by_signature[value_signature].add(word)

    candidates: list[dict[str, object]] = []
    for dataset in datasets:
        split = dataset["splits"]["test"]
        recording_rel = next(
            str(item["relative_path"]) for item in dataset["artifacts"]
            if item["name"] == split["recordings_artifact"])
        supervision_rel = next(
            str(item["relative_path"]) for item in dataset["artifacts"]
            if item["name"] == split["supervisions_artifact"])
        recording_by_id = {
            str(item["id"]): item for item in rows(data_asr / recording_rel)
        }
        for supervision in rows(data_asr / supervision_rel):
            duration = float(supervision.get("duration", 0))
            start = float(supervision.get("start", 0))
            text = str(supervision.get("text", "")).strip()
            recording_id = str(supervision.get("recording_id", ""))
            recording = recording_by_id.get(recording_id)
            if not (2.0 <= duration <= 12.0 and start == 0.0 and text and recording):
                continue
            sources = recording.get("sources")
            if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
                continue
            source_path = sources[0].get("source")
            if not isinstance(source_path, str):
                continue
            audio_rel = relative_audio(source_path)
            if not (data_asr / audio_rel).is_file():
                continue
            found: list[tuple[int, str, str]] = []
            for width in range(3, 7):
                for offset in range(0, len(text) - width + 1):
                    source = text[offset:offset + width]
                    source_signature = signature(source, pinyin)
                    if source_signature is None:
                        continue
                    for distractor in sorted(targets_by_signature.get(source_signature, set())):
                        if distractor != source and distractor not in text:
                            found.append((offset, source, distractor))
            for offset, source, distractor in found:
                candidates.append({
                    "stratum": f"negative_{dataset['dataset_id']}",
                    "dataset_id": dataset["dataset_id"],
                    "language": "zh-CN",
                    "recording_id": recording_id,
                    "reference": text,
                    "hotwords": [distractor],
                    "expected_source": source,
                    "distractor": distractor,
                    "source_offset": offset,
                    "candidate_length": len(distractor),
                    "duration": duration,
                    "audio": audio_rel,
                    "recordings_manifest": recording_rel,
                    "supervisions_manifest": supervision_rel,
                    "negative_control": True,
                })

    random.Random(SEED).shuffle(candidates)
    selected: list[dict[str, object]] = []
    used_recordings: set[tuple[str, str]] = set()
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for item in candidates:
        recording_key = (str(item["dataset_id"]), str(item["recording_id"]))
        pair = (str(item["expected_source"]), str(item["distractor"]))
        if recording_key in used_recordings or pair_counts[pair] >= 2:
            continue
        selected.append(item)
        used_recordings.add(recording_key)
        pair_counts[pair] += 1
        if len(selected) == COUNT:
            break
    if len(selected) != COUNT:
        raise RuntimeError(f"expected {COUNT} negative controls, found {len(selected)}")
    for index, item in enumerate(selected):
        item["fixture_index"] = index
        item["id"] = f"neg-{index:03d}"
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    entries = generate(args.data_root.expanduser().resolve())
    payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        f"{digest}  {args.output.name}\n", encoding="ascii")
    print(f"wrote {len(entries)} fixed negative controls to {args.output}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
