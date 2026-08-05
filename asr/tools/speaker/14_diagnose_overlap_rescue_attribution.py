#!/usr/bin/env python3
"""Attribute frozen Conv-TasNet L2 failures to separation, selection, or gain.

The tool deterministically replays an existing synthetic L2 ``trials.jsonl``.
It does not tune a threshold or define a new rescue candidate. Instead it uses
the already available clean target/other sources for two diagnostic-only
counterfactuals:

* an oracle source assignment, which measures the separator ceiling without
  ERes2Net stream-selection errors; and
* one common output gain for both blind streams, which preserves their relative
  energy and reveals whether per-stream RMS normalization is necessary for
  target-absent textual leakage.

The original mixture hashes, ERes2Net scores, and selected streams must replay
exactly (within a small floating-point tolerance) before any result is written.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import platform
import re
import shlex
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

L2_SPEC = importlib.util.spec_from_file_location(
    "overlap_rescue_synthetic_l2", SCRIPT_DIR / "13_eval_overlap_rescue_synthetic.py"
)
assert L2_SPEC is not None and L2_SPEC.loader is not None
l2 = importlib.util.module_from_spec(L2_SPEC)
sys.modules[L2_SPEC.name] = l2
L2_SPEC.loader.exec_module(l2)

rescue = l2.rescue
pilot = l2.pilot

from ts_asr import (  # noqa: E402
    asr_decode_full_segment,
    build_recognizer,
    build_speaker,
    enroll,
    load_audio_mono16k,
)


SAMPLE_RATE = 16_000
SCORE_TOLERANCE = 2e-5
FROZEN_THRESHOLD = 0.25
OVERLAP_CONDITION = re.compile(r"^overlap_sir_(-?\d+(?:\.\d+)?)db$")


def root_mean_square(samples: np.ndarray) -> float:
    value = np.asarray(samples, dtype=np.float32)
    if not len(value):
        return 0.0
    return float(np.sqrt(np.mean(np.square(value), dtype=np.float64)))


def scale_invariant_sdr(estimate: np.ndarray, reference: np.ndarray) -> float | None:
    """Return zero-mean SI-SDR, or None when the reference has no usable energy."""
    estimate64 = np.asarray(estimate, dtype=np.float64)
    reference64 = np.asarray(reference, dtype=np.float64)
    if estimate64.shape != reference64.shape:
        raise ValueError("estimate and reference must have the same shape")
    estimate64 = estimate64 - np.mean(estimate64)
    reference64 = reference64 - np.mean(reference64)
    reference_energy = float(np.dot(reference64, reference64))
    if reference_energy <= 1e-12:
        return None
    projection = reference64 * (float(np.dot(estimate64, reference64)) / reference_energy)
    noise = estimate64 - projection
    ratio = (float(np.dot(projection, projection)) + 1e-12) / (
        float(np.dot(noise, noise)) + 1e-12
    )
    return float(10.0 * math.log10(ratio))


def common_gain_candidates(
    output: np.ndarray, input_rms: float, available: int
) -> tuple[list[np.ndarray], float]:
    """Apply one reconstruction gain to both streams, preserving energy ratio."""
    value = np.asarray(output, dtype=np.float32)
    if value.shape != (2, rescue.CHUNK_SAMPLES):
        raise ValueError(f"expected [2,{rescue.CHUNK_SAMPLES}], got {value.shape}")
    reconstructed = value[0] + value[1]
    reconstructed_rms = root_mean_square(reconstructed[:available])
    gain = input_rms / max(1e-9, reconstructed_rms)
    return [
        np.ascontiguousarray(value[index] * gain, dtype=np.float32) for index in range(2)
    ], gain


def oracle_target_stream(
    candidates: Sequence[np.ndarray],
    target: np.ndarray,
    other: np.ndarray,
    available: int,
) -> tuple[int, list[float | None], list[float | None]]:
    """Choose the target stream using independent-source truth and PIT assignment."""
    target_scores = [
        scale_invariant_sdr(candidate[:available], target[:available])
        for candidate in candidates
    ]
    if any(value is None for value in target_scores):
        raise ValueError("oracle target source has no usable energy")
    other_scores = [
        scale_invariant_sdr(candidate[:available], other[:available])
        for candidate in candidates
    ]
    if all(value is None for value in other_scores):
        selected = 1 if float(target_scores[1]) > float(target_scores[0]) else 0
        return selected, target_scores, other_scores
    if any(value is None for value in other_scores):
        raise ValueError("oracle other source energy is inconsistent")
    direct = float(target_scores[0]) + float(other_scores[1])
    swapped = float(target_scores[1]) + float(other_scores[0])
    return (1 if swapped > direct else 0), target_scores, other_scores


def chunk(samples: np.ndarray, start: int) -> tuple[np.ndarray, int]:
    available = min(rescue.CHUNK_SAMPLES, len(samples) - start)
    value = np.zeros(rescue.CHUNK_SAMPLES, dtype=np.float32)
    value[:available] = samples[start : start + available]
    return value, available


def chunk_weight(index: int, count: int) -> np.ndarray:
    weight = np.ones(rescue.CHUNK_SAMPLES, dtype=np.float32)
    ramp = rescue.cosine_ramp()
    if index > 0:
        weight[: rescue.OVERLAP_SAMPLES] = ramp
    if index + 1 < count:
        weight[-rescue.OVERLAP_SAMPLES :] = ramp[::-1]
    return weight


def finalize_overlap_add(
    accumulator: np.ndarray, weights: np.ndarray, length: int
) -> np.ndarray:
    value = accumulator[:length] / np.maximum(weights[:length], 1e-6)
    if not np.isfinite(value).all():
        raise RuntimeError("diagnostic overlap-add produced non-finite PCM")
    return np.ascontiguousarray(value, dtype=np.float32)


def reconstruct_trial_sources(
    row: dict[str, Any], target_audio: np.ndarray, other_audio: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    condition = str(row["condition"])
    if condition == "target_only":
        mixture = np.ascontiguousarray(target_audio, dtype=np.float32)
        return mixture, mixture.copy(), np.zeros_like(mixture)
    if condition == "other_only":
        mixture = np.ascontiguousarray(other_audio, dtype=np.float32)
        return mixture, np.zeros_like(mixture), mixture.copy()
    match = OVERLAP_CONDITION.fullmatch(condition)
    if match is None:
        raise ValueError(f"unsupported frozen condition: {condition}")
    return l2.mix_sources_at_sir(target_audio, other_audio, float(match.group(1)))


def normalized_text(value: Any) -> list[str]:
    return pilot.normalize_characters(str(value))


def edit_count(reference: Any, hypothesis: Any) -> int:
    return pilot.edit_distance(normalized_text(reference), normalized_text(hypothesis))


def percentile(values: Sequence[float], quantile: float) -> float | None:
    return rescue.nearest_rank_percentile(values, quantile) if values else None


def target_metrics(rows: Sequence[dict[str, Any]], split: str, condition: str) -> dict[str, Any]:
    selected = [
        row for row in rows if row["split"] == split and row["condition"] == condition
    ]
    characters = sum(len(normalized_text(row["target_reference_text"])) for row in selected)
    current_edits = sum(
        edit_count(row["target_reference_text"], row["current_text"]) for row in selected
    )
    oracle_edits = sum(
        edit_count(row["target_reference_text"], row["oracle_text"]) for row in selected
    )
    current_other = sum(
        l2.attributed_other_characters(
            str(row["target_reference_text"]),
            str(row["other_reference_text"]),
            str(row["current_text"]),
        )
        for row in selected
    )
    oracle_other = sum(
        l2.attributed_other_characters(
            str(row["target_reference_text"]),
            str(row["other_reference_text"]),
            str(row["oracle_text"]),
        )
        for row in selected
    )
    other_characters = sum(len(normalized_text(row["other_reference_text"])) for row in selected)
    pairwise = {"oracle_better": 0, "oracle_worse": 0, "equal": 0}
    block_selection = {"correct_stream": 0, "wrong_stream": 0, "rejected": 0}
    sisdri: list[float] = []
    for row in selected:
        current = edit_count(row["target_reference_text"], row["current_text"])
        oracle = edit_count(row["target_reference_text"], row["oracle_text"])
        key = "oracle_better" if oracle < current else "oracle_worse" if oracle > current else "equal"
        pairwise[key] += 1
        for block in row["blocks"]:
            chosen = int(block["selected"])
            oracle_stream = int(block["oracle_target_stream"])
            if chosen < 0:
                block_selection["rejected"] += 1
            elif chosen == oracle_stream:
                block_selection["correct_stream"] += 1
            else:
                block_selection["wrong_stream"] += 1
            if block["oracle_target_sisdri_db"] is not None:
                sisdri.append(float(block["oracle_target_sisdri_db"]))
    return {
        "trials": len(selected),
        "target_reference_characters": characters,
        "current_target_cer": current_edits / characters if characters else None,
        "oracle_target_cer": oracle_edits / characters if characters else None,
        "other_reference_characters": other_characters,
        "current_other_recall": current_other / other_characters if other_characters else None,
        "oracle_other_recall": oracle_other / other_characters if other_characters else None,
        "trial_pairwise": pairwise,
        "block_selection": block_selection,
        "oracle_target_sisdri_db_p50": statistics.median(sisdri) if sisdri else None,
        "oracle_target_sisdri_db_p05": percentile(sisdri, 0.05),
    }


def other_only_metrics(rows: Sequence[dict[str, Any]], split: str) -> dict[str, Any]:
    selected = [
        row for row in rows if row["split"] == split and row["condition"] == "other_only"
    ]
    current_false = [row for row in selected if row["current_false_rescue"]]
    common_false = [row for row in selected if row["common_gain_false_rescue"]]
    false_blocks = [
        block
        for row in current_false
        for block in row["blocks"]
        if int(block["selected"]) >= 0
    ]
    boosts = [float(block["selected_per_stream_rms_boost"]) for block in false_blocks]
    common_energy_ratios = [float(block["selected_common_rms_ratio"]) for block in false_blocks]
    selected_scores = [float(block["selected_score"]) for block in false_blocks]
    raw_input_scores = [float(block["raw_input_score"]) for block in false_blocks]
    lower_energy = sum(not bool(block["selected_is_energy_dominant"]) for block in false_blocks)
    raw_already_accepted = sum(
        float(block["raw_input_score"]) >= FROZEN_THRESHOLD for block in false_blocks
    )
    return {
        "trials": len(selected),
        "selection_accept_trials": sum(
            any(int(value) >= 0 for value in row["selected"]) for row in selected
        ),
        "current_false_rescues": len(current_false),
        "common_gain_false_rescues": len(common_false),
        "false_rescues_removed_by_preserving_energy": sum(
            row["current_false_rescue"] and not row["common_gain_false_rescue"]
            for row in selected
        ),
        "false_rescues_remaining_with_common_gain": sum(
            row["current_false_rescue"] and row["common_gain_false_rescue"]
            for row in selected
        ),
        "accepted_blocks_in_current_false_rescues": len(false_blocks),
        "lower_energy_selected_blocks": lower_energy,
        "energy_dominant_selected_blocks": len(false_blocks) - lower_energy,
        "selected_per_stream_rms_boost_p50": statistics.median(boosts) if boosts else None,
        "selected_per_stream_rms_boost_p95": percentile(boosts, 0.95),
        "selected_per_stream_rms_boost_max": max(boosts) if boosts else None,
        "selected_common_rms_ratio_p50": (
            statistics.median(common_energy_ratios) if common_energy_ratios else None
        ),
        "selected_score_p50": statistics.median(selected_scores) if selected_scores else None,
        "raw_input_score_p50": statistics.median(raw_input_scores) if raw_input_scores else None,
        "raw_input_already_above_threshold_blocks": raw_already_accepted,
        "separator_raised_above_threshold_blocks": len(false_blocks) - raw_already_accepted,
        "false_rescue_trials": [
            {
                "target_speaker": row["target_speaker"],
                "other_speaker": row["other_speaker"],
                "other_recording_id": row["other_recording_id"],
                "current_text": row["current_text"],
                "common_gain_text": row["common_gain_text"],
            }
            for row in current_false
        ],
    }


def render_report(summary: dict[str, Any]) -> str:
    def percent(value: float | None) -> str:
        return "-" if value is None else f"{value:.2%}"

    def decimal(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}"

    test = summary["metrics"].get("test", {})
    lines = [
        "# 16 kHz Conv-TasNet L2 失败归因",
        "",
        "> 本报告只做 oracle 与增益反事实诊断，不改变 0.25 阈值，也不构成新的救援候选。",
        "",
        "| test 条件 | current CER | oracle CER | current other recall | oracle other recall | oracle better/worse/equal | correct/wrong/rejected blocks |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, row in test.get("target_present", {}).items():
        pairwise = row["trial_pairwise"]
        blocks = row["block_selection"]
        lines.append(
            f"| {condition} | {percent(row['current_target_cer'])} | "
            f"{percent(row['oracle_target_cer'])} | {percent(row['current_other_recall'])} | "
            f"{percent(row['oracle_other_recall'])} | "
            f"{pairwise['oracle_better']}/{pairwise['oracle_worse']}/{pairwise['equal']} | "
            f"{blocks['correct_stream']}/{blocks['wrong_stream']}/{blocks['rejected']} |"
        )
    if "other_only" in test:
        other = test["other_only"]
        lines.extend(
            [
                "",
                "## test other-only",
                "",
                f"- 当前 textual false rescue：`{other['current_false_rescues']}/{other['trials']}`。",
                f"- 保持两路相对能量后：`{other['common_gain_false_rescues']}/{other['trials']}`；"
                f"消失 `{other['false_rescues_removed_by_preserving_energy']}`，仍存在 "
                f"`{other['false_rescues_remaining_with_common_gain']}`。",
                f"- 原 false-rescue 的 accepted blocks 中，选择低能残留/主导非目标流："
                f"`{other['lower_energy_selected_blocks']}/{other['energy_dominant_selected_blocks']}`。",
                f"- 原始 other 块已过 0.25 / 经 separator 后才过门："
                f"`{other['raw_input_already_above_threshold_blocks']}/"
                f"{other['separator_raised_above_threshold_blocks']}`。",
                f"- 每路独立 RMS 归一化相对统一增益的 boost：p50 "
                f"`{decimal(other['selected_per_stream_rms_boost_p50'])}x`，p95 "
                f"`{decimal(other['selected_per_stream_rms_boost_p95'])}x`。",
            ]
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- oracle 使用合成独立源，只能分解 separator ceiling 与 ERes2Net 选流误差，生产时不可获得。",
            "- common gain 只用于判断逐路 RMS 是否是文本泄漏的必要条件，不是待调参数或候选规则。",
            "- AISHELL-2 合成全时重叠不代表真实设备、混响、距离、codec 或开放世界分布。",
            "- 本结果不改变 L2 已失败、停止 L3 阈值搜索的冻结决策。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l2-result-dir", type=Path, required=True)
    parser.add_argument("--separator-model", type=Path, required=True)
    parser.add_argument("--speaker-model", type=Path)
    parser.add_argument("--asr-model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--separator-threads", type=int, default=4)
    parser.add_argument("--speaker-threads", type=int, default=2)
    parser.add_argument("--asr-threads", type=int, default=2)
    parser.add_argument("--max-trials", type=int)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    for name in ("separator_threads", "speaker_threads", "asr_threads"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.max_trials is not None and args.max_trials <= 0:
        parser.error("--max-trials must be positive")
    return args


def main() -> int:
    args = parse_args()
    rescue.ensure_output_dir(args.output_dir)
    summary_path = args.l2_result_dir / "summary.json"
    trials_path = args.l2_result_dir / "trials.jsonl"
    for path in (summary_path, trials_path, args.separator_model, args.asr_model_dir):
        if not path.exists():
            raise FileNotFoundError(path)
    l2_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if l2_summary.get("study") != "convtasnet-libri2mix-16k-overlap-rescue-synthetic-l2":
        raise ValueError("input is not a frozen synthetic L2 result")
    threshold = float(l2_summary["configuration"]["threshold"])
    if threshold != FROZEN_THRESHOLD:
        raise ValueError(
            f"attribution requires the frozen {FROZEN_THRESHOLD} threshold, got {threshold}"
        )
    rows = [
        json.loads(line)
        for line in trials_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    expected_trials = int(l2_summary["trial_counts"]["total"])
    if len(rows) != expected_trials:
        raise ValueError(f"L2 trial count mismatch: expected {expected_trials}, got {len(rows)}")
    if args.max_trials is not None:
        rows = rows[: args.max_trials]

    separator_hash = rescue.sha256(args.separator_model)
    if separator_hash != str(l2_summary["artifacts"]["separator_sha256"]):
        raise ValueError("separator does not match the frozen L2 result")
    allowed_separator_hashes = {
        l2.EXPECTED_HARMONY_SEPARATOR_SHA256,
        l2.EXPECTED_EXPORT_VARIANT_SHA256,
    }
    if separator_hash not in allowed_separator_hashes:
        raise ValueError(f"unrecognized separator ONNX: {separator_hash}")
    speaker_model = args.speaker_model or Path(l2_summary["artifacts"]["speaker_model"])
    rescue.require_sha256(speaker_model, rescue.EXPECTED_SPEAKER_SHA256, "speaker model")
    asr_artifacts = rescue.asr_model_artifacts(args.asr_model_dir)
    for artifact in asr_artifacts:
        rescue.require_sha256(
            Path(artifact["path"]),
            rescue.EXPECTED_ASR_SHA256[artifact["name"]],
            artifact["name"],
        )

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
    input_name = separator.get_inputs()[0].name
    output_name = separator.get_outputs()[0].name
    audio_cache: dict[str, np.ndarray] = {}
    enrollment_cache: dict[tuple[str, ...], np.ndarray] = {}

    def audio(path_value: str, expected_hash: str | None = None) -> np.ndarray:
        if path_value not in audio_cache:
            path = Path(path_value)
            if expected_hash is not None:
                rescue.require_sha256(path, expected_hash, path.name)
            samples, _ = load_audio_mono16k(path)
            audio_cache[path_value] = np.ascontiguousarray(samples, dtype=np.float32)
        return audio_cache[path_value]

    def target_embedding(row: dict[str, Any]) -> np.ndarray:
        paths = tuple(str(path) for path in row["enrollment_audio_paths"])
        if len(paths) != 3:
            raise ValueError("frozen L2 trial must contain three enrollment utterances")
        if paths not in enrollment_cache:
            enrollment_cache[paths] = enroll(
                extractor, [(audio(path), SAMPLE_RATE) for path in paths]
            )
        return enrollment_cache[paths]

    output_rows: list[dict[str, Any]] = []
    replay_score_max_abs_diff = 0.0
    inference_ms: list[float] = []
    started = time.perf_counter()
    for trial_index, row in enumerate(rows):
        target_audio = audio(str(row["target_audio_path"]), str(row["target_audio_sha256"]))
        other_audio = audio(str(row["other_audio_path"]), str(row["other_audio_sha256"]))
        mixture, target_source, other_source = reconstruct_trial_sources(
            row, target_audio, other_audio
        )
        mixture_hash = hashlib.sha256(mixture.tobytes()).hexdigest()
        if mixture_hash != row["mixture_pcm_sha256"]:
            raise RuntimeError(
                f"trial {trial_index} mixture replay mismatch: {mixture_hash} != "
                f"{row['mixture_pcm_sha256']}"
            )
        embedding_value = target_embedding(row)
        starts = list(range(0, len(mixture), rescue.HOP_SAMPLES))
        common_accumulator = np.zeros(len(mixture) + rescue.CHUNK_SAMPLES, dtype=np.float32)
        oracle_accumulator = np.zeros_like(common_accumulator)
        weights = np.zeros_like(common_accumulator)
        block_rows: list[dict[str, Any]] = []
        replay_selected: list[int] = []
        for block_index, start in enumerate(starts):
            mixture_chunk, available = chunk(mixture, start)
            target_chunk, _ = chunk(target_source, start)
            other_chunk, _ = chunk(other_source, start)
            input_rms = root_mean_square(mixture_chunk[:available])
            raw_input_score = float(
                np.dot(embedding_value, rescue.embedding(extractor, mixture_chunk))
            )
            inference_started = time.perf_counter()
            output = separator.run([output_name], {input_name: mixture_chunk[None, :]})[0]
            inference_ms.append((time.perf_counter() - inference_started) * 1000.0)
            output = np.asarray(output, dtype=np.float32)
            if output.shape != (1, 2, rescue.CHUNK_SAMPLES) or not np.isfinite(output).all():
                raise RuntimeError(f"unexpected separator output: {output.shape}")
            raw_candidates = output[0]
            common_candidates, common_gain = common_gain_candidates(
                raw_candidates, input_rms, available
            )
            normalized_candidates = [
                rescue.rms_normalize(raw_candidates[index], input_rms, available)
                for index in range(2)
            ]
            scores = [
                float(np.dot(embedding_value, rescue.embedding(extractor, candidate)))
                for candidate in normalized_candidates
            ]
            recorded_scores = [float(row["score0"][block_index]), float(row["score1"][block_index])]
            score_difference = max(abs(scores[index] - recorded_scores[index]) for index in range(2))
            replay_score_max_abs_diff = max(replay_score_max_abs_diff, score_difference)
            if score_difference > SCORE_TOLERANCE:
                raise RuntimeError(
                    f"trial {trial_index} block {block_index} score replay drift: "
                    f"{scores} != {recorded_scores}"
                )
            best_stream = 1 if scores[1] > scores[0] else 0
            selected_stream = best_stream if scores[best_stream] >= threshold else -1
            if selected_stream != int(row["selected"][block_index]):
                raise RuntimeError(
                    f"trial {trial_index} block {block_index} selection replay mismatch"
                )
            replay_selected.append(selected_stream)

            weight = chunk_weight(block_index, len(starts))
            end = start + rescue.CHUNK_SAMPLES
            common_value = (
                common_candidates[selected_stream]
                if selected_stream >= 0
                else np.zeros(rescue.CHUNK_SAMPLES, dtype=np.float32)
            )
            common_accumulator[start:end] += common_value * weight
            weights[start:end] += weight

            common_rms = [
                root_mean_square(candidate[:available]) for candidate in common_candidates
            ]
            raw_rms = [root_mean_square(candidate[:available]) for candidate in raw_candidates]
            target_present = bool(normalized_text(row["target_reference_text"]))
            oracle_stream: int | None = None
            target_sisdr: list[float | None] = [None, None]
            other_sisdr: list[float | None] = [None, None]
            oracle_sisdri: float | None = None
            if target_present:
                oracle_stream, target_sisdr, other_sisdr = oracle_target_stream(
                    common_candidates, target_chunk, other_chunk, available
                )
                oracle_accumulator[start:end] += normalized_candidates[oracle_stream] * weight
                mixture_sisdr = scale_invariant_sdr(
                    mixture_chunk[:available], target_chunk[:available]
                )
                if mixture_sisdr is not None:
                    oracle_sisdri = float(target_sisdr[oracle_stream]) - mixture_sisdr
            else:
                other_sisdr = [
                    scale_invariant_sdr(candidate[:available], other_chunk[:available])
                    for candidate in common_candidates
                ]

            if selected_stream >= 0:
                selected_common_rms = common_rms[selected_stream]
                selected_boost = input_rms / max(1e-9, selected_common_rms)
                selected_common_ratio = selected_common_rms / max(1e-9, input_rms)
                selected_is_dominant = common_rms[selected_stream] >= common_rms[1 - selected_stream]
                selected_score = scores[selected_stream]
            else:
                selected_boost = None
                selected_common_ratio = None
                selected_is_dominant = None
                selected_score = None
            block_rows.append(
                {
                    "start_sample": start,
                    "available_samples": available,
                    "selected": selected_stream,
                    "selected_score": selected_score,
                    "raw_input_score": raw_input_score,
                    "scores": scores,
                    "oracle_target_stream": oracle_stream,
                    "target_sisdr_db": target_sisdr,
                    "other_sisdr_db": other_sisdr,
                    "oracle_target_sisdri_db": oracle_sisdri,
                    "input_rms": input_rms,
                    "raw_output_rms": raw_rms,
                    "common_gain": common_gain,
                    "common_output_rms": common_rms,
                    "selected_common_rms_ratio": selected_common_ratio,
                    "selected_per_stream_rms_boost": selected_boost,
                    "selected_is_energy_dominant": selected_is_dominant,
                }
            )

        if replay_selected != [int(value) for value in row["selected"]]:
            raise RuntimeError(f"trial {trial_index} selected stream sequence drifted")
        common_pcm = finalize_overlap_add(common_accumulator, weights, len(mixture))
        target_present = bool(normalized_text(row["target_reference_text"]))
        if target_present:
            oracle_pcm = finalize_overlap_add(oracle_accumulator, weights, len(mixture))
            oracle_text = asr_decode_full_segment(recognizer, oracle_pcm, SAMPLE_RATE)
            common_gain_text: str | None = None
        else:
            oracle_text = None
            common_gain_text = (
                asr_decode_full_segment(recognizer, common_pcm, SAMPLE_RATE)
                if any(value >= 0 for value in replay_selected)
                else ""
            )
        current_text = str(row["rescued_text"])
        current_false_rescue = (
            row["condition"] == "other_only"
            and any(value >= 0 for value in replay_selected)
            and bool(normalized_text(current_text))
        )
        common_false_rescue = (
            row["condition"] == "other_only"
            and any(value >= 0 for value in replay_selected)
            and bool(normalized_text(common_gain_text))
        )
        output_rows.append(
            {
                "split": row["split"],
                "condition": row["condition"],
                "target_speaker": row["target_speaker"],
                "other_speaker": row["other_speaker"],
                "target_recording_id": row["target_recording_id"],
                "other_recording_id": row["other_recording_id"],
                "mixture_pcm_sha256": mixture_hash,
                "target_reference_text": row["target_reference_text"],
                "other_reference_text": row["other_reference_text"],
                "selected": replay_selected,
                "current_text": current_text,
                "oracle_text": oracle_text,
                "common_gain_text": common_gain_text,
                "current_false_rescue": current_false_rescue,
                "common_gain_false_rescue": common_false_rescue,
                "blocks": block_rows,
            }
        )
        if args.progress_every > 0 and (trial_index + 1) % args.progress_every == 0:
            print(
                f"attributed trials {trial_index + 1}/{len(rows)}",
                file=sys.stderr,
                flush=True,
            )

    conditions = sorted(
        {str(row["condition"]) for row in output_rows if row["condition"] != "other_only"}
    )
    splits = sorted({str(row["split"]) for row in output_rows})
    metrics: dict[str, Any] = {}
    for split in splits:
        metrics[split] = {
            "target_present": {
                condition: target_metrics(output_rows, split, condition)
                for condition in conditions
                if any(
                    row["split"] == split and row["condition"] == condition
                    for row in output_rows
                )
            },
            "other_only": other_only_metrics(output_rows, split),
        }
    inference_rtf = [value / 2000.0 for value in inference_ms]
    summary = {
        "study": "convtasnet-libri2mix-16k-l2-failure-attribution",
        "status": "diagnostic_only",
        "configuration": {
            "threshold": threshold,
            "threshold_source": "frozen_l2_summary",
            "chunk_samples": rescue.CHUNK_SAMPLES,
            "overlap_samples": rescue.OVERLAP_SAMPLES,
            "hop_samples": rescue.HOP_SAMPLES,
            "oracle": "independent_source_PIT_SI-SDR_per_chunk_then_current_RMS_and_crossfade",
            "gain_counterfactual": "one_sum-reconstruction_RMS_gain_for_both_streams",
            "max_trials": args.max_trials,
        },
        "artifacts": {
            "l2_result_dir": str(args.l2_result_dir),
            "l2_summary_sha256": rescue.sha256(summary_path),
            "l2_trials_sha256": rescue.sha256(trials_path),
            "separator_model": str(args.separator_model),
            "separator_sha256": separator_hash,
            "speaker_model": str(speaker_model),
            "speaker_model_sha256": rescue.sha256(speaker_model),
            "asr_model_dir": str(args.asr_model_dir),
            "asr_model_files": asr_artifacts,
        },
        "replay": {
            "trials": len(output_rows),
            "mixture_hash_mismatches": 0,
            "selection_mismatches": 0,
            "score_max_abs_diff": replay_score_max_abs_diff,
            "score_tolerance": SCORE_TOLERANCE,
        },
        "metrics": metrics,
        "runtime": {
            "total_seconds": time.perf_counter() - started,
            "separator_create_ms": create_ms,
            "separator_warm_ms": warm_ms,
            "separator_chunks": len(inference_ms),
            "separator_p50_rtf": statistics.median(inference_rtf),
            "separator_p95_rtf": percentile(inference_rtf, 0.95),
            "packages": rescue.package_versions(),
        },
        "limitations": [
            "oracle independent sources are unavailable in production",
            "common gain is a diagnostic counterfactual, not a proposed selection rule",
            "AISHELL-2 deterministic full-duration synthetic overlap only",
            "local ONNX serialization differs from the frozen Mate 80 ONNX",
            "no Harmony lifecycle or ARM resource validation",
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
    (args.output_dir / "environment.txt").write_text(
        "\n".join(
            [
                f"platform={platform.platform()}",
                f"python={sys.version.split()[0]}",
                *(f"{key}={value}" for key, value in rescue.package_versions().items()),
                f"command={shlex.join(sys.argv)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
