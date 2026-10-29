#!/usr/bin/env python3
"""Measure target and non-target voiceprint scores on short segments.

Speaker VAD cannot reach a verdict before winSec + hopSec of audio, so an utterance shorter than
that is published on its final score alone. This measures where that score separates the enrolled
speaker from everybody else at those durations, which is how the floor in
`UNCONFIRMED_SPEAKER_FINAL_MIN_SCORE` (SpeakerTurnFinalizer.ts) was chosen: on device a non-target
1.6 s utterance scored 0.362 against the default 0.35 threshold and was published as the owner's.

Enrolment and test audio come from the same session here, which flatters the target side; see the
same caveat in docs/speaker/AIDATATANG_SPEAKER_VAD_EVAL.md. Cross-session enrolment has to be
re-measured with customer voiceprints before the floor is treated as validated for production.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ts_asr import build_speaker, enroll, load_audio_mono16k  # noqa: E402

SAMPLE_RATE = 16000


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path,
                        default=Path.home() / ".cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500")
    parser.add_argument("--speaker-model", type=Path,
                        default=REPO_ROOT / "shared/models/asr/dingqiao/eres2net.onnx")
    parser.add_argument("--target-speaker", default="SSB0693")
    parser.add_argument("--enrollment", type=int, default=3)
    parser.add_argument("--segment-sec", type=float, nargs="+", default=[1.0, 1.5, 2.0, 3.0])
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.35, 0.40, 0.45, 0.50])
    parser.add_argument("--max-others", type=int, default=120)
    parser.add_argument("--num-threads", type=int, default=2)
    parser.add_argument("--out-dir", type=Path,
                        default=REPO_ROOT / "asr/tools/speaker/results/short_segment_threshold")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    recordings: dict[str, str] = {}
    for line in gzip.open(args.dataset_dir / "aishell3_test_hotwords_500_recordings_packaged.jsonl.gz", "rt"):
        record = json.loads(line)
        recordings[record["id"]] = record["sources"][0]["source"]
    by_speaker: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for line in gzip.open(args.dataset_dir / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz", "rt"):
        sup = json.loads(line)
        by_speaker[sup["speaker"]].append((sup["recording_id"], float(sup["duration"])))

    target_items = sorted(by_speaker[args.target_speaker], key=lambda item: -item[1])
    if len(target_items) <= args.enrollment:
        raise SystemExit(f"{args.target_speaker} has too few utterances to enrol and test")
    enrolled = target_items[:args.enrollment]
    held_out = target_items[args.enrollment:]

    extractor = build_speaker(args.speaker_model.resolve(), num_threads=args.num_threads)
    embedding = enroll(extractor, [
        (load_audio_mono16k(args.dataset_dir / recordings[rid])[0], SAMPLE_RATE) for rid, _ in enrolled
    ])

    def score(samples: np.ndarray) -> float | None:
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=samples)
        stream.input_finished()
        if not extractor.is_ready(stream):
            return None
        value = np.asarray(extractor.compute(stream), dtype=np.float32)
        value /= np.linalg.norm(value) + 1e-9
        return float(np.dot(value, embedding))

    rows = []
    for segment_sec in args.segment_sec:
        width = int(segment_sec * SAMPLE_RATE)
        target_scores: list[float] = []
        for rid, _ in held_out:
            samples, _ = load_audio_mono16k(args.dataset_dir / recordings[rid])
            if samples.size < width:
                continue
            value = score(samples[:width])
            if value is not None:
                target_scores.append(value)
        other_scores: list[float] = []
        for speaker, items in by_speaker.items():
            if speaker == args.target_speaker or len(other_scores) >= args.max_others:
                continue
            for rid, _ in items[:2]:
                samples, _ = load_audio_mono16k(args.dataset_dir / recordings[rid])
                if samples.size < width:
                    continue
                value = score(samples[:width])
                if value is not None:
                    other_scores.append(value)
        if not target_scores or not other_scores:
            continue
        row = {
            "segment_sec": segment_sec,
            "target": {"n": len(target_scores), "min": min(target_scores),
                       "p10": percentile(target_scores, 0.10), "p50": percentile(target_scores, 0.50)},
            "other": {"n": len(other_scores), "p50": percentile(other_scores, 0.50),
                      "p90": percentile(other_scores, 0.90), "p99": percentile(other_scores, 0.99),
                      "max": max(other_scores)},
            "other_above": {f"{t:.2f}": sum(1 for s in other_scores if s >= t) / len(other_scores)
                            for t in args.thresholds},
            "target_below": {f"{t:.2f}": sum(1 for s in target_scores if s < t) / len(target_scores)
                             for t in args.thresholds},
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), file=sys.stderr)

    (args.out_dir / "summary.json").write_text(
        json.dumps({"target_speaker": args.target_speaker, "enrollment": len(enrolled),
                    "same_session_enrollment": True, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    header = "| 段长 | 机主 n / 最低 / p10 | 非机主 n / p90 / 最高 | " + " | ".join(
        f"非机主≥{t:.2f}" for t in args.thresholds) + " |"
    lines = [header, "|---|---|---|" + "---|" * len(args.thresholds)]
    for row in rows:
        lines.append(
            f"| {row['segment_sec']:.1f}s | {row['target']['n']} / {row['target']['min']:.3f} / "
            f"{row['target']['p10']:.3f} | {row['other']['n']} / {row['other']['p90']:.3f} / "
            f"{row['other']['max']:.3f} | " + " | ".join(
                f"{row['other_above'][f'{t:.2f}']:.1%}" for t in args.thresholds) + " |")
    (args.out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
