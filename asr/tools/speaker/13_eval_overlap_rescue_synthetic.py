#!/usr/bin/env python3
"""Evaluate the 16 kHz Conv-TasNet overlap rescue on frozen synthetic trials.

This is the L2 synthetic-data diagnostic from
``CONVTASNET_LINUX_NEXT_EXPERIMENT_20260804.md``. It consumes a completed
three-enrollment AISHELL-2 pilot, selects speaker-disjoint dev/test target and
interferer pairs, and evaluates target-only, other-only, and full-duration
two-speaker mixtures at fixed SIRs. Raw ASR and rescued ASR use identical PCM.

The separator is blind: every 2-second output pair is re-scored against the
target's three-enrollment ERes2Net embedding. This tool does not change SDK
behavior and does not claim Harmony lifecycle or ARM resource parity.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

RESCUE_SPEC = importlib.util.spec_from_file_location(
    "overlap_rescue_shared", SCRIPT_DIR / "12_eval_overlap_rescue.py"
)
assert RESCUE_SPEC is not None and RESCUE_SPEC.loader is not None
rescue = importlib.util.module_from_spec(RESCUE_SPEC)
sys.modules[RESCUE_SPEC.name] = rescue
RESCUE_SPEC.loader.exec_module(rescue)

PILOT_SPEC = importlib.util.spec_from_file_location(
    "voiceprint_pilot_shared_l2", SCRIPT_DIR / "07_eval_voiceprint_verification.py"
)
assert PILOT_SPEC is not None and PILOT_SPEC.loader is not None
pilot = importlib.util.module_from_spec(PILOT_SPEC)
sys.modules[PILOT_SPEC.name] = pilot
PILOT_SPEC.loader.exec_module(pilot)

from ts_asr import (  # noqa: E402
    asr_decode_full_segment,
    build_recognizer,
    build_speaker,
    enroll,
    load_audio_mono16k,
)


SAMPLE_RATE = 16_000
EXPECTED_HARMONY_SEPARATOR_SHA256 = rescue.EXPECTED_SEPARATOR_SHA256
EXPECTED_EXPORT_VARIANT_SHA256 = (
    "861a476ecce029e44ef3e0b5d37971a27ad8207fefe4e07e4ecf5b0d6dc80599"
)
EXPECTED_CHECKPOINT_SHA256 = (
    "8d97f012f7b2f22bb79cb0d0983a7ba27a52c1796ee3f63cbf25b4d28630adce"
)


def stable_offset(size: int, seed: int) -> int:
    if size < 2:
        raise ValueError("at least two speakers are required")
    digest = hashlib.sha256(str(seed).encode("ascii")).digest()
    return 1 + int.from_bytes(digest[:8], "big") % (size - 1)


def choose_speaker_pairs(
    rows: Sequence[dict], split: str, max_speakers: int | None, seed: int
) -> list[tuple[dict, dict]]:
    """Pair each target probe with a different same-split speaker bijectively."""
    candidates: dict[str, list[dict]] = {}
    for row in rows:
        if (
            str(row.get("split")) == split
            and str(row.get("condition")) == "clean"
            and int(row.get("label", -1)) == 1
        ):
            candidates.setdefault(str(row["target_speaker"]), []).append(row)
    selected = [
        sorted(bucket, key=lambda row: str(row["probe_recording_id"]))[0]
        for _, bucket in sorted(candidates.items())
    ]
    if max_speakers is not None:
        if max_speakers <= 0:
            raise ValueError("speaker limit must be positive")
        selected = selected[:max_speakers]
    if len(selected) < 2:
        raise RuntimeError(f"split {split} does not contain two usable speakers")
    offset = stable_offset(len(selected), seed)
    pairs = [(row, selected[(index + offset) % len(selected)]) for index, row in enumerate(selected)]
    if any(target["target_speaker"] == other["target_speaker"] for target, other in pairs):
        raise AssertionError("target and interferer speakers must differ")
    return pairs


def mix_sources_at_sir(
    target: np.ndarray, other: np.ndarray, sir_db: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return mixture and its aligned target/other components at a fixed SIR."""
    target = np.asarray(target, dtype=np.float32)
    other = np.asarray(other, dtype=np.float32)
    if not len(target) or not len(other):
        raise ValueError("target and other speech must be non-empty")
    if len(other) < len(target):
        other = np.tile(other, math.ceil(len(target) / len(other)))
    other = other[: len(target)]
    target_rms = float(np.sqrt(np.mean(np.square(target), dtype=np.float64)))
    other_rms = float(np.sqrt(np.mean(np.square(other), dtype=np.float64)))
    if target_rms <= 1e-9 or other_rms <= 1e-9:
        raise ValueError("target or other speech has zero RMS")
    other_scale = target_rms / (10.0 ** (sir_db / 20.0) * other_rms)
    target_component = target.copy()
    other_component = other * other_scale
    mixture = target_component + other_component
    peak = float(np.max(np.abs(mixture)))
    if peak > 0.99:
        peak_scale = 0.99 / peak
        target_component *= peak_scale
        other_component *= peak_scale
        mixture *= peak_scale
    return tuple(
        np.ascontiguousarray(value, dtype=np.float32)
        for value in (mixture, target_component, other_component)
    )


def mix_at_sir(target: np.ndarray, other: np.ndarray, sir_db: float) -> np.ndarray:
    """Repeat/truncate the interferer to target duration and mix at target/other SIR."""
    mixture, _, _ = mix_sources_at_sir(target, other, sir_db)
    return mixture


def lcs_matched_hypothesis_indices(reference: Sequence[str], hypothesis: Sequence[str]) -> set[int]:
    """Return hypothesis indices consumed by one deterministic LCS alignment."""
    rows = len(reference) + 1
    cols = len(hypothesis) + 1
    table = [[0] * cols for _ in range(rows)]
    for i, left in enumerate(reference, 1):
        for j, right in enumerate(hypothesis, 1):
            if left == right:
                table[i][j] = table[i - 1][j - 1] + 1
            else:
                table[i][j] = max(table[i - 1][j], table[i][j - 1])
    matched: set[int] = set()
    i, j = len(reference), len(hypothesis)
    while i and j:
        if reference[i - 1] == hypothesis[j - 1]:
            matched.add(j - 1)
            i -= 1
            j -= 1
        elif table[i - 1][j] >= table[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return matched


def attributed_other_characters(target_text: str, other_text: str, hypothesis: str) -> int:
    """Conservatively count other-reference characters not explained by target LCS."""
    target = pilot.normalize_characters(target_text)
    other = pilot.normalize_characters(other_text)
    output = pilot.normalize_characters(hypothesis)
    target_indices = lcs_matched_hypothesis_indices(target, output)
    residual = [character for index, character in enumerate(output) if index not in target_indices]
    return len(lcs_matched_hypothesis_indices(other, residual))


def trial_metrics(rows: Sequence[dict], split: str, condition: str) -> dict:
    selected = [row for row in rows if row["split"] == split and row["condition"] == condition]
    target_characters = 0
    other_characters = 0
    raw_target_edits = 0
    rescued_target_edits = 0
    raw_other_attributed = 0
    rescued_other_attributed = 0
    false_rescues = 0
    false_rejections = 0
    selection_accept_trials = 0
    nonempty_output_trials = 0
    accepted_blocks = 0
    total_blocks = 0
    for row in selected:
        target = pilot.normalize_characters(str(row["target_reference_text"]))
        other = pilot.normalize_characters(str(row["other_reference_text"]))
        if target:
            target_characters += len(target)
            raw_target_edits += pilot.edit_distance(
                target, pilot.normalize_characters(str(row["raw_text"]))
            )
            rescued_target_edits += pilot.edit_distance(
                target, pilot.normalize_characters(str(row["rescued_text"]))
            )
        other_characters += len(other)
        raw_other_attributed += attributed_other_characters(
            str(row["target_reference_text"]),
            str(row["other_reference_text"]),
            str(row["raw_text"]),
        )
        rescued_other_attributed += attributed_other_characters(
            str(row["target_reference_text"]),
            str(row["other_reference_text"]),
            str(row["rescued_text"]),
        )
        selected_sources = [int(value) for value in row["selected"]]
        accepted = sum(value >= 0 for value in selected_sources)
        nonempty_output = bool(pilot.normalize_characters(str(row["rescued_text"])))
        accepted_blocks += accepted
        total_blocks += len(selected_sources)
        selection_accept_trials += accepted > 0
        nonempty_output_trials += nonempty_output
        if condition == "other_only" and accepted > 0 and nonempty_output:
            false_rescues += 1
        if condition != "other_only" and (
            accepted == 0 or not nonempty_output
        ):
            false_rejections += 1
    return {
        "trials": len(selected),
        "target_reference_characters": target_characters,
        "raw_target_cer": raw_target_edits / target_characters if target_characters else None,
        "rescued_target_cer": rescued_target_edits / target_characters if target_characters else None,
        "other_reference_characters": other_characters,
        "raw_attributed_other_recall": (
            raw_other_attributed / other_characters if other_characters else None
        ),
        "rescued_attributed_other_recall": (
            rescued_other_attributed / other_characters if other_characters else None
        ),
        "false_rescues": false_rescues,
        "false_rejections": false_rejections,
        "selection_accept_trials": selection_accept_trials,
        "nonempty_output_trials": nonempty_output_trials,
        "accepted_blocks": accepted_blocks,
        "total_blocks": total_blocks,
        "accepted_block_rate": accepted_blocks / total_blocks if total_blocks else None,
    }


def render_report(summary: dict) -> str:
    def percent(value: float | None) -> str:
        return "-" if value is None else f"{value:.2%}"

    test = summary["metrics"]["test"]
    lines = [
        "# 16 kHz Conv-TasNet 合成重叠救援 L2",
        "",
        "> 本结果使用正确的 Libri2Mix 16 kHz checkpoint，但 ONNX 序列化 SHA 与 Mate 80 文件不同，",
        "> 因此是 export-variant L2 diagnostic，不是 exact L1 parity。",
        "",
        "| test 条件 | trials | raw target CER | rescued target CER | raw other recall | rescued other recall | false rescue | false reject |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    conditions = ["target_only", "other_only"] + [
        f"overlap_sir_{sir:g}db" for sir in summary["configuration"]["sir_db"]
    ]
    for condition in conditions:
        row = test[condition]
        lines.append(
            f"| {condition} | {row['trials']} | {percent(row['raw_target_cer'])} | "
            f"{percent(row['rescued_target_cer'])} | {percent(row['raw_attributed_other_recall'])} | "
            f"{percent(row['rescued_attributed_other_recall'])} | {row['false_rescues']} | "
            f"{row['false_rejections']} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- dev/test speaker 隔离；每个 target 使用三段 enrollment 和独立 probe。",
            "- other leakage 是保守归因：先用 LCS 从 hypothesis 去掉可由 target 解释的字符，再与 other reference 做 LCS。",
            "- 固定阈值 0.25，没有用 test 重选；本轮只跑文档 L3 的 A 基线，不扫描 B/C。",
            "- AISHELL-2 全时合成重叠不代表真实设备、混响、距离或开放世界分布。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--separator-model", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--speaker-model", type=Path)
    parser.add_argument("--asr-model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sir-db", type=float, nargs="+", default=[-5.0, 0.0, 5.0])
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--dev-speakers", type=int)
    parser.add_argument("--test-speakers", type=int)
    parser.add_argument("--separator-threads", type=int, default=4)
    parser.add_argument("--speaker-threads", type=int, default=2)
    parser.add_argument("--asr-threads", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rescue.ensure_output_dir(args.output_dir)
    summary_path = args.baseline_dir / "summary.json"
    trials_path = args.baseline_dir / "trials.jsonl"
    for path in (
        summary_path,
        trials_path,
        args.separator_model,
        args.checkpoint,
        args.asr_model_dir,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    baseline_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    config = baseline_summary["config"]
    if int(config.get("enroll_utterances", 0)) != 3:
        raise ValueError("L2 experiment requires exactly three enrollment utterances")
    rows = [json.loads(line) for line in trials_path.read_text(encoding="utf-8").splitlines() if line]

    checkpoint_hash = rescue.sha256(args.checkpoint)
    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(f"wrong Libri2Mix checkpoint: {checkpoint_hash}")
    separator_hash = rescue.sha256(args.separator_model)
    allowed_separator_hashes = {
        EXPECTED_HARMONY_SEPARATOR_SHA256: "exact_harmony_onnx",
        EXPECTED_EXPORT_VARIANT_SHA256: "local_export_variant",
    }
    if separator_hash not in allowed_separator_hashes:
        raise RuntimeError(f"unrecognized separator ONNX: {separator_hash}")

    artifacts = baseline_summary["artifacts"]
    speaker_model = args.speaker_model or Path(artifacts["speaker_model"])
    rescue.require_sha256(speaker_model, rescue.EXPECTED_SPEAKER_SHA256, "speaker model")
    asr_artifacts = rescue.asr_model_artifacts(args.asr_model_dir)
    for artifact in asr_artifacts:
        rescue.require_sha256(
            Path(artifact["path"]), rescue.EXPECTED_ASR_SHA256[artifact["name"]], artifact["name"]
        )

    pairs = {
        "dev": choose_speaker_pairs(rows, "dev", args.dev_speakers, args.seed),
        "test": choose_speaker_pairs(rows, "test", args.test_speakers, args.seed),
    }
    if args.test_speakers is None and len({other["target_speaker"] for _, other in pairs["test"]}) < 20:
        raise RuntimeError("full L2 test requires at least 20 distinct non-target identities")

    extractor = build_speaker(speaker_model, num_threads=args.speaker_threads, provider="cpu")
    recognizer = build_recognizer(
        args.asr_model_dir,
        num_threads=args.asr_threads,
        provider="cpu",
        enable_endpoint_detection=True,
    )
    separator, create_ms, warm_ms = rescue.create_separator(
        args.separator_model, args.separator_threads
    )
    audio_cache: dict[str, np.ndarray] = {}
    enrollment_cache: dict[tuple[str, ...], np.ndarray] = {}
    raw_asr_cache: dict[str, str] = {}

    def audio(path: str) -> np.ndarray:
        if path not in audio_cache:
            samples, _ = load_audio_mono16k(Path(path))
            audio_cache[path] = np.ascontiguousarray(samples, dtype=np.float32)
        return audio_cache[path]

    def target_embedding(row: dict) -> np.ndarray:
        paths = tuple(str(path) for path in row["enrollment_audio_paths"])
        if len(paths) != 3:
            raise RuntimeError("trial does not contain three enrollment paths")
        if paths not in enrollment_cache:
            enrollment_cache[paths] = enroll(
                extractor, [(audio(path), SAMPLE_RATE) for path in paths]
            )
        return enrollment_cache[paths]

    output_rows: list[dict] = []
    all_inference_ms: list[float] = []
    started = time.perf_counter()
    total_pairs = sum(len(value) for value in pairs.values())
    completed_pairs = 0
    for split in ("dev", "test"):
        for target_row, other_row in pairs[split]:
            target_audio = audio(str(target_row["probe_audio_path"]))
            other_audio = audio(str(other_row["probe_audio_path"]))
            embedding_value = target_embedding(target_row)
            variants = [
                ("target_only", target_audio, str(target_row["reference_text"]), ""),
                ("other_only", other_audio, "", str(other_row["reference_text"])),
            ]
            variants.extend(
                (
                    f"overlap_sir_{sir:g}db",
                    mix_at_sir(target_audio, other_audio, sir),
                    str(target_row["reference_text"]),
                    str(other_row["reference_text"]),
                )
                for sir in args.sir_db
            )
            for condition, samples, target_text, other_text in variants:
                waveform_hash = hashlib.sha256(samples.tobytes()).hexdigest()
                if waveform_hash not in raw_asr_cache:
                    raw_asr_cache[waveform_hash] = asr_decode_full_segment(
                        recognizer, samples, SAMPLE_RATE
                    )
                rescued, detail = rescue.run_rescue(
                    separator, extractor, embedding_value, samples, args.threshold
                )
                rescued_text = asr_decode_full_segment(recognizer, rescued, SAMPLE_RATE)
                all_inference_ms.extend(float(value) for value in detail["inference_ms"])
                output_rows.append(
                    {
                        "split": split,
                        "condition": condition,
                        "target_speaker": target_row["target_speaker"],
                        "other_speaker": other_row["target_speaker"],
                        "target_recording_id": target_row["probe_recording_id"],
                        "other_recording_id": other_row["probe_recording_id"],
                        "target_audio_path": target_row["probe_audio_path"],
                        "other_audio_path": other_row["probe_audio_path"],
                        "target_audio_sha256": rescue.sha256(Path(target_row["probe_audio_path"])),
                        "other_audio_sha256": rescue.sha256(Path(other_row["probe_audio_path"])),
                        "enrollment_audio_paths": target_row["enrollment_audio_paths"],
                        "target_reference_text": target_text,
                        "other_reference_text": other_text,
                        "mixture_pcm_sha256": waveform_hash,
                        "duration_seconds": len(samples) / SAMPLE_RATE,
                        "raw_text": raw_asr_cache[waveform_hash],
                        "rescued_text": rescued_text,
                        "selected": detail["selected"],
                        "score0": detail["score0"],
                        "score1": detail["score1"],
                        "inference_ms": detail["inference_ms"],
                        "speaker_ms": detail["speaker_ms"],
                    }
                )
            completed_pairs += 1
            if args.progress_every > 0 and completed_pairs % args.progress_every == 0:
                print(
                    f"processed speaker pairs {completed_pairs}/{total_pairs}; trials={len(output_rows)}",
                    file=sys.stderr,
                    flush=True,
                )

    conditions = ["target_only", "other_only"] + [
        f"overlap_sir_{sir:g}db" for sir in args.sir_db
    ]
    metrics = {
        split: {condition: trial_metrics(output_rows, split, condition) for condition in conditions}
        for split in ("dev", "test")
    }
    inference_rtf = [value / 2000.0 for value in all_inference_ms]
    summary = {
        "study": "convtasnet-libri2mix-16k-overlap-rescue-synthetic-l2",
        "status": "diagnostic_only",
        "configuration": {
            "seed": args.seed,
            "sir_db": args.sir_db,
            "threshold": args.threshold,
            "chunk_samples": rescue.CHUNK_SAMPLES,
            "overlap_samples": rescue.OVERLAP_SAMPLES,
            "hop_samples": rescue.HOP_SAMPLES,
            "source_selection": "per_chunk_max_eres2net_with_absolute_threshold",
            "speaker_pairing": "same_split_bijective_rotation",
            "baseline_config": config,
        },
        "artifacts": {
            "baseline_dir": str(args.baseline_dir),
            "baseline_summary_sha256": rescue.sha256(summary_path),
            "baseline_trials_sha256": rescue.sha256(trials_path),
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256": checkpoint_hash,
            "separator_model": str(args.separator_model),
            "separator_sha256": separator_hash,
            "separator_identity": allowed_separator_hashes[separator_hash],
            "speaker_model": str(speaker_model),
            "speaker_model_sha256": rescue.sha256(speaker_model),
            "asr_model_dir": str(args.asr_model_dir),
            "asr_model_files": asr_artifacts,
        },
        "trial_counts": {
            "total": len(output_rows),
            "dev_speakers": len(pairs["dev"]),
            "test_speakers": len(pairs["test"]),
            "test_distinct_other_speakers": len(
                {str(other["target_speaker"]) for _, other in pairs["test"]}
            ),
        },
        "metrics": metrics,
        "runtime": {
            "total_seconds": time.perf_counter() - started,
            "separator_create_ms": create_ms,
            "separator_warm_ms": warm_ms,
            "separator_chunks": len(inference_rtf),
            "separator_p50_rtf": statistics.median(inference_rtf),
            "separator_p95_rtf": rescue.nearest_rank_percentile(inference_rtf, 0.95),
            "onnxruntime_version": rescue.package_versions()["onnxruntime"],
        },
        "leakage_definition": (
            "remove target-explainable LCS characters from hypothesis, then divide the LCS length "
            "between residual hypothesis and other reference by other reference length"
        ),
        "limitations": [
            "AISHELL-2 source speech and deterministic full-duration synthetic overlap",
            "one target probe and one bijectively paired other identity per enrolled target",
            "no room impulse response, device capture, distance, codec, or partial overlap",
            "other identities are non-enrolled relative to each trial but also serve as targets in another trial",
            "local ONNX serialization differs from the frozen Mate 80 ONNX and is not exact L1 parity",
            "Linux CPU results do not prove Harmony lifecycle or ARM resource gates",
        ],
    }
    with (args.output_dir / "trials.jsonl").open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
