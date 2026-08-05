#!/usr/bin/env python3
"""Evaluate the frozen C1 Speaker VAD on speaker-disjoint synthetic turns.

The experiment reuses the three-enrollment AISHELL-2 verification pilot and
constructs target-to-other sessions with controlled overlap/gap, other-tail
duration, gain, and caller PCM partitioning. By default it mirrors the fixed Android and
Harmony scheduling rule: score deadlines are anchored to absolute PCM sample positions.
The historical one-score-per-public-call behavior remains available for before/after replay.

This is a local synthetic diagnostic. It freezes threshold=0.35, win=1.0 s,
hop=0.3 s, and consecutiveBelow=2. The optional buffered_tail_commit publication
policy holds two hops (600 ms), drops that tail when departure is confirmed, and
re-decodes only the committed prefix. It neither tunes SDK parameters nor changes
SDK behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import shlex
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SV_SPEC = importlib.util.spec_from_file_location(
    "speaker_vad_aidatatang_shared", SCRIPT_DIR / "06_eval_speaker_vad_aidatatang.py"
)
assert SV_SPEC is not None and SV_SPEC.loader is not None
speaker_vad = importlib.util.module_from_spec(SV_SPEC)
sys.modules[SV_SPEC.name] = speaker_vad
SV_SPEC.loader.exec_module(speaker_vad)

L2_SPEC = importlib.util.spec_from_file_location(
    "overlap_rescue_synthetic_shared_c1", SCRIPT_DIR / "13_eval_overlap_rescue_synthetic.py"
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
FROZEN_THRESHOLD = 0.35
WIN_SEC = 1.0
HOP_SEC = 0.3
CONSECUTIVE_BELOW = 2
WIN_SAMPLES = int(WIN_SEC * SAMPLE_RATE)
HOP_SAMPLES = int(HOP_SEC * SAMPLE_RATE)
TAIL_HOLDBACK_SAMPLES = CONSECUTIVE_BELOW * HOP_SAMPLES
REALTIME_SAMPLES = int(0.02 * SAMPLE_RATE)
TEMPORAL_GAPS_SEC = (-0.3, 0.0, 0.3, 0.6)
OTHER_TAILS_SEC = (0.3, 0.6, 1.0, 2.0)
TARGET_GAINS_DB = (-12.0, 0.0)
OTHER_GAINS_DB = (-6.0, 0.0, 6.0)
FRAME_TAILS_SEC = (0.6, 2.0)
IRREGULAR_CHUNKS = (160, 2720, 640, 8000, 480, 3680)
SHORT_TARGET_MAX_SEC = 2.5
LONG_TARGET_MIN_SEC = 4.0


@dataclass(frozen=True)
class TailCommitDecision:
    publish_samples: int
    rollback_samples: int
    reason: str


def buffered_commit_decision(result: Any, *, total_samples: int) -> TailCommitDecision:
    """Choose the public PCM prefix for the frozen 600 ms tail-commit prototype.

    The recognizer may inspect all input privately, but public partial/final results are decoded only
    from this committed prefix. A confirmed departure or an unresolved low score at explicit finish
    discards the entire two-hop tail. Clean explicit finish commits it; an unconfirmed segment is
    rejected. This is an experiment policy, not a new SDK default.
    """
    total = max(0, int(total_samples))
    if result.target_confirm_sec is None:
        return TailCommitDecision(0, 0, "target_not_confirmed")
    if result.state == "endpoint":
        endpoint = min(
            total,
            max(0, int(round(float(result.endpoint_sec or 0.0) * SAMPLE_RATE))),
        )
        published = max(0, endpoint - TAIL_HOLDBACK_SAMPLES)
        return TailCommitDecision(published, endpoint - published, "confirmed_departure")
    if int(result.below_count) > 0:
        published = max(0, total - TAIL_HOLDBACK_SAMPLES)
        return TailCommitDecision(
            published,
            total - published,
            "unresolved_departure_at_finish",
        )
    return TailCommitDecision(total, 0, "clean_finish")


def publication_decision(
    result: Any,
    *,
    total_samples: int,
    policy: str,
) -> TailCommitDecision:
    if policy == "buffered_tail_commit":
        return buffered_commit_decision(result, total_samples=total_samples)
    if policy != "direct_endpoint":
        raise ValueError(f"unsupported publication policy: {policy}")
    total = max(0, int(total_samples))
    if result.target_confirm_sec is None:
        return TailCommitDecision(0, 0, "target_not_confirmed")
    endpoint = min(
        total,
        max(0, int(round(float(result.endpoint_sec or total / SAMPLE_RATE) * SAMPLE_RATE))),
    )
    return TailCommitDecision(endpoint, 0, "direct_endpoint")


def db_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def compose_transition(
    target: np.ndarray,
    other: np.ndarray,
    *,
    gap_sec: float,
    other_tail_sec: float,
    target_gain_db: float = 0.0,
    other_gain_db: float = 0.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Place target then other on one timeline; negative gap means overlap."""
    target_value = np.asarray(target, dtype=np.float32) * db_gain(target_gain_db)
    requested_other = max(1, int(round(other_tail_sec * SAMPLE_RATE)))
    other_value = np.asarray(other, dtype=np.float32)[:requested_other] * db_gain(other_gain_db)
    if not len(target_value) or not len(other_value):
        raise ValueError("target and other sources must be non-empty")
    other_start = len(target_value) + int(round(gap_sec * SAMPLE_RATE))
    if other_start < 0:
        raise ValueError("negative gap starts other before session zero")
    total = max(len(target_value), other_start + len(other_value))
    target_component = np.zeros(total, dtype=np.float32)
    other_component = np.zeros(total, dtype=np.float32)
    target_component[: len(target_value)] = target_value
    other_component[other_start : other_start + len(other_value)] = other_value
    session = target_component + other_component
    peak = float(np.max(np.abs(session)))
    peak_scale = 1.0
    if peak > 0.99:
        peak_scale = 0.99 / peak
        session *= peak_scale
    return np.ascontiguousarray(session, dtype=np.float32), {
        "target_end_sample": len(target_value),
        "other_start_sample": other_start,
        "other_end_sample": other_start + len(other_value),
        "requested_other_samples": requested_other,
        "actual_other_samples": len(other_value),
        "peak_scale": peak_scale,
    }


def partition_sizes(total_samples: int, pattern: str) -> list[int]:
    if total_samples <= 0:
        return []
    if pattern == "realtime_20ms":
        cycle = (REALTIME_SAMPLES,)
    elif pattern == "irregular":
        cycle = IRREGULAR_CHUNKS
    elif pattern == "single_block":
        return [total_samples]
    else:
        raise ValueError(f"unsupported chunk pattern: {pattern}")
    result: list[int] = []
    remaining = total_samples
    index = 0
    while remaining > 0:
        size = min(remaining, cycle[index % len(cycle)])
        result.append(size)
        remaining -= size
        index += 1
    return result


def build_sdk_timeline(
    session: np.ndarray,
    *,
    chunk_pattern: str,
    score_schedule: str = "absolute_samples",
    target_end_sample: int,
    other_start_sample: int,
    score_window: Callable[[np.ndarray], float | None],
) -> list[speaker_vad.TimelinePoint]:
    """Mirror the selected SDK Speaker VAD score schedule."""
    points: list[speaker_vad.TimelinePoint] = []
    if score_schedule == "absolute_samples":
        score_ends: list[int] = []
        consumed = WIN_SAMPLES
        if consumed <= len(session):
            score_ends.append(consumed)
            remainder = WIN_SAMPLES % HOP_SAMPLES
            consumed += HOP_SAMPLES if remainder == 0 else HOP_SAMPLES - remainder
        while consumed <= len(session):
            score_ends.append(consumed)
            consumed += HOP_SAMPLES
    elif score_schedule == "legacy_per_call":
        score_ends = []
        consumed = 0
        samples_since_score = 0
        for size in partition_sizes(len(session), chunk_pattern):
            consumed += size
            samples_since_score += size
            if consumed < WIN_SAMPLES or samples_since_score < HOP_SAMPLES:
                continue
            samples_since_score %= HOP_SAMPLES
            score_ends.append(consumed)
    else:
        raise ValueError(f"unsupported score schedule: {score_schedule}")

    for consumed in score_ends:
        start = consumed - WIN_SAMPLES
        score = score_window(np.ascontiguousarray(session[start:consumed], dtype=np.float32))
        if score is None:
            continue
        if consumed <= other_start_sample:
            region = "target"
        elif start >= target_end_sample:
            region = "other"
        else:
            region = "transition"
        points.append(speaker_vad.TimelinePoint(consumed / SAMPLE_RATE, score, region))
    return points


def normalized_text(value: Any) -> list[str]:
    return pilot.normalize_characters(str(value))


def describe(values: Sequence[float]) -> dict[str, Any]:
    return speaker_vad.describe([float(value) for value in values])


def target_duration_bucket(duration_sec: float) -> str:
    if duration_sec < SHORT_TARGET_MAX_SEC:
        return "short_lt_2.5s"
    if duration_sec < LONG_TARGET_MIN_SEC:
        return "medium_2.5_to_4s"
    return "long_ge_4s"


def decision_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"trials": 0}
    states: dict[str, int] = {}
    for row in rows:
        states[row["state"]] = states.get(row["state"], 0) + 1
    leaks = [float(row["other_leak_sec"]) for row in rows]
    baseline_leaks = [float(row["other_actual_sec"]) for row in rows]
    truncations = [float(row["target_truncated_sec"]) for row in rows]
    endpoint_delays = [float(row["endpoint_sec"]) - float(row["target_end_sec"]) for row in rows]
    publication_delays = [
        float(row.get("publication_cutoff_sec", row["endpoint_sec"]))
        - float(row["target_end_sec"])
        for row in rows
    ]
    total_baseline = sum(baseline_leaks)
    return {
        "trials": len(rows),
        "states": states,
        "target_confirm_rate": sum(row["target_confirmed"] for row in rows) / len(rows),
        "speaker_endpoint_rate": sum(row["state"] == "endpoint" for row in rows) / len(rows),
        "target_truncation_rate": sum(value > 1e-6 for value in truncations) / len(rows),
        "any_other_leak_rate": sum(value > 1e-6 for value in leaks) / len(rows),
        "avg_other_leak_sec": statistics.fmean(leaks),
        "avg_other_actual_sec": statistics.fmean(baseline_leaks),
        "other_leak_reduction_rate": (
            1.0 - sum(leaks) / total_baseline if total_baseline > 0 else None
        ),
        "target_truncated_sec": describe(truncations),
        "endpoint_delay_from_target_end_sec": describe(endpoint_delays),
        "publication_delay_from_target_end_sec": describe(publication_delays),
    }


def asr_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    usable = [row for row in rows if row.get("published_text") is not None]
    if not usable:
        return {"trials": 0}
    target_characters = 0
    other_characters = 0
    target_only_edits = 0
    baseline_edits = 0
    published_edits = 0
    baseline_other = 0
    published_other = 0
    published_other_trials = 0
    published_empty_trials = 0
    target_regression_trials = 0
    for row in usable:
        target = normalized_text(row["target_reference_text"])
        other = normalized_text(row["other_reference_text"])
        target_only = normalized_text(row["target_only_text"])
        baseline = normalized_text(row["baseline_text"])
        published = normalized_text(row["published_text"])
        target_characters += len(target)
        other_characters += len(other)
        target_only_error = pilot.edit_distance(target, target_only)
        published_error = pilot.edit_distance(target, published)
        target_only_edits += target_only_error
        baseline_edits += pilot.edit_distance(target, baseline)
        published_edits += published_error
        baseline_other += l2.attributed_other_characters(
            str(row["target_reference_text"]),
            str(row["other_reference_text"]),
            str(row["baseline_text"]),
        )
        attributed = l2.attributed_other_characters(
            str(row["target_reference_text"]),
            str(row["other_reference_text"]),
            str(row["published_text"]),
        )
        published_other += attributed
        published_other_trials += attributed > 0
        published_empty_trials += not published
        target_regression_trials += published_error > target_only_error
    return {
        "trials": len(usable),
        "target_reference_characters": target_characters,
        "target_only_cer": target_only_edits / target_characters if target_characters else None,
        "baseline_session_cer": baseline_edits / target_characters if target_characters else None,
        "published_cer": published_edits / target_characters if target_characters else None,
        "target_regression_trials": target_regression_trials,
        "published_empty_trials": published_empty_trials,
        "other_reference_characters": other_characters,
        "baseline_other_recall": baseline_other / other_characters if other_characters else None,
        "published_other_recall": published_other / other_characters if other_characters else None,
        "published_other_text_trials": published_other_trials,
    }


def temporal_metrics(rows: Sequence[dict[str, Any]], split: str) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["split"] == split
        and row["family"] == "temporal"
        and row["chunk_pattern"] == "realtime_20ms"
    ]
    grouped: dict[str, Any] = {}
    for gap in TEMPORAL_GAPS_SEC:
        for tail in OTHER_TAILS_SEC:
            bucket = [
                row
                for row in selected
                if row["gap_sec"] == gap and row["requested_other_tail_sec"] == tail
            ]
            key = f"gap_{gap:g}s_tail_{tail:g}s"
            grouped[key] = {**decision_metrics(bucket), "asr": asr_metrics(bucket)}
    by_target_duration = {
        bucket: {
            **decision_metrics(
                [row for row in selected if row["target_duration_bucket"] == bucket]
            ),
            "asr": asr_metrics(
                [row for row in selected if row["target_duration_bucket"] == bucket]
            ),
        }
        for bucket in ("short_lt_2.5s", "medium_2.5_to_4s", "long_ge_4s")
    }
    return {
        "overall": {**decision_metrics(selected), "asr": asr_metrics(selected)},
        "matrix": grouped,
        "by_target_duration": by_target_duration,
    }


def volume_metrics(rows: Sequence[dict[str, Any]], split: str) -> dict[str, Any]:
    selected = [row for row in rows if row["split"] == split and row["family"] == "volume"]
    return {
        f"target_{target_db:g}db_other_{other_db:g}db": decision_metrics(
            [
                row
                for row in selected
                if row["target_gain_db"] == target_db and row["other_gain_db"] == other_db
            ]
        )
        for target_db in TARGET_GAINS_DB
        for other_db in OTHER_GAINS_DB
    }


def framing_metrics(rows: Sequence[dict[str, Any]], split: str) -> dict[str, Any]:
    selected = [row for row in rows if row["split"] == split and row["family"] == "framing"]
    groups: dict[tuple[str, str, float], dict[str, dict[str, Any]]] = {}
    for row in selected:
        key = (str(row["target_speaker"]), str(row["other_speaker"]), float(row["requested_other_tail_sec"]))
        groups.setdefault(key, {})[str(row["chunk_pattern"])] = row
    comparisons: dict[str, Any] = {}
    for pattern in ("irregular", "single_block"):
        deltas: list[float] = []
        state_mismatches = 0
        confirm_mismatches = 0
        missing = 0
        for patterns in groups.values():
            reference = patterns.get("realtime_20ms")
            candidate = patterns.get(pattern)
            if reference is None or candidate is None:
                missing += 1
                continue
            deltas.append(float(candidate["endpoint_sec"]) - float(reference["endpoint_sec"]))
            state_mismatches += candidate["state"] != reference["state"]
            confirm_mismatches += candidate["target_confirmed"] != reference["target_confirmed"]
        comparisons[pattern] = {
            "pairs": len(groups) - missing,
            "missing": missing,
            "state_mismatch_rate": state_mismatches / max(1, len(groups) - missing),
            "target_confirm_mismatch_rate": confirm_mismatches / max(1, len(groups) - missing),
            "endpoint_delta_sec": describe(deltas),
            "exact_endpoint_match_rate": sum(abs(value) <= 1.0 / SAMPLE_RATE for value in deltas)
            / max(1, len(deltas)),
        }
    return {
        "by_pattern": {
            pattern: decision_metrics([row for row in selected if row["chunk_pattern"] == pattern])
            for pattern in ("realtime_20ms", "irregular", "single_block")
        },
        "relative_to_realtime_20ms": comparisons,
    }


def anchor_metrics(rows: Sequence[dict[str, Any]], split: str) -> dict[str, Any]:
    selected = [row for row in rows if row["split"] == split and row["family"] == "anchor"]
    return {
        kind: {
            pattern: decision_metrics(
                [
                    row
                    for row in selected
                    if row["anchor_kind"] == kind and row["chunk_pattern"] == pattern
                ]
            )
            for pattern in ("realtime_20ms", "irregular", "single_block")
        }
        for kind in ("target_only", "other_only")
    }


def strict_gate(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    failures: list[str] = []
    test = metrics.get("test")
    if test is None:
        return "INCONCLUSIVE", ["test split was not executed"]
    temporal = test["temporal"]["overall"]
    temporal_asr = temporal["asr"]
    if temporal["target_confirm_rate"] < 1.0:
        failures.append("target-present session was not always confirmed")
    if temporal["target_truncation_rate"] > 0.0:
        failures.append("target speech was truncated")
    if temporal_asr["published_empty_trials"] > 0:
        failures.append("target-present public output was rejected")
    if temporal_asr["published_other_text_trials"] > 0:
        failures.append("non-target lexical leakage remained")
    for pattern, row in test["framing"]["relative_to_realtime_20ms"].items():
        if row["state_mismatch_rate"] > 0.0 or row["exact_endpoint_match_rate"] < 1.0:
            failures.append(f"{pattern} changed the Speaker VAD decision")
    for name, row in test["volume"].items():
        if row["target_confirm_rate"] < 1.0 or row["target_truncation_rate"] > 0.0:
            failures.append(f"volume stress failed for {name}")
    for pattern in ("realtime_20ms", "irregular", "single_block"):
        target_anchor = test["anchors"]["target_only"][pattern]
        if (
            target_anchor["target_confirm_rate"] < 1.0
            or target_anchor["target_truncation_rate"] > 0.0
        ):
            failures.append(f"target-only protection failed for {pattern}")
        other_anchor = test["anchors"]["other_only"][pattern]
        if other_anchor["target_confirm_rate"] > 0.0:
            failures.append(f"other-only was falsely confirmed for {pattern}")
    return ("PASS" if not failures else "FAIL"), failures


def render_report(summary: dict[str, Any]) -> str:
    def percent(value: float | None) -> str:
        return "-" if value is None else f"{value:.2%}"

    test = summary["metrics"].get("test", {})
    lines = [
        "# C1 target→other 合成 Speaker VAD 评测",
        "",
        f"> 冻结配置：threshold `{FROZEN_THRESHOLD}`，window `{WIN_SEC:.1f}s`，hop `{HOP_SEC:.1f}s`，连续低分 `{CONSECUTIVE_BELOW}`。",
        f"> 发布策略：`{summary['configuration']['publication_policy']}`；最大稳态 partial 延迟 "
        f"`{summary['configuration']['maximum_steady_partial_delay_sec']:.1f}s`。",
        f"> 严格门：**{summary['decision']['status']}**。",
        "",
        "| test gap/tail | target确认率 | target截断率 | 平均 other 泄漏/实际(s) | 泄漏降幅 | 发布空文本 | 发布 other 文本 | published CER |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in test.get("temporal", {}).get("matrix", {}).items():
        asr = row["asr"]
        lines.append(
            f"| {name} | {percent(row['target_confirm_rate'])} | "
            f"{percent(row['target_truncation_rate'])} | {row['avg_other_leak_sec']:.3f}/"
            f"{row['avg_other_actual_sec']:.3f} | {percent(row['other_leak_reduction_rate'])} | "
            f"{asr['published_empty_trials']} | {asr['published_other_text_trials']} | "
            f"{percent(asr['published_cer'])} |"
        )
    lines.extend(["", "## 分帧一致性", ""])
    for pattern, row in test.get("framing", {}).get("relative_to_realtime_20ms", {}).items():
        lines.append(
            f"- `{pattern}`：state mismatch `{row['state_mismatch_rate']:.2%}`，"
            f"exact endpoint match `{row['exact_endpoint_match_rate']:.2%}`。"
        )
    lines.extend(["", "## 严格门失败项", ""])
    if summary["decision"]["failures"]:
        lines.extend(f"- {value}" for value in summary["decision"]["failures"])
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 使用 AISHELL-2 独立 probe 和三段 enrollment；dev/test speaker 隔离。",
            "- 合成直接拼接/重叠不包含真实设备、距离、混响、AGC、codec 或自然对话韵律。",
            "- lexical leakage 使用完整 other 文本做保守 LCS 归因；裁剪尾段没有字级时间戳。",
            "- 只复刻 Speaker VAD 分数调度和两阶段状态，不模拟 Silero/ASR 自身更早 endpoint。",
            "- buffered policy 的 partial 只来自已提交前缀；本工具以提交水位和前缀重解码验证文本，"
            "不模拟 UI 回调时间线。",
            "- 本报告不修改 SDK 默认值，也不验证 isLast/onComplete/cancel 真机契约。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--speaker-model", type=Path)
    parser.add_argument("--asr-model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--dev-speakers", type=int)
    parser.add_argument("--test-speakers", type=int)
    parser.add_argument("--speaker-threads", type=int, default=2)
    parser.add_argument("--asr-threads", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument(
        "--score-schedule",
        choices=("absolute_samples", "legacy_per_call"),
        default="absolute_samples",
        help="fixed SDK behavior or historical per-public-call replay",
    )
    parser.add_argument(
        "--publication-policy",
        choices=("direct_endpoint", "buffered_tail_commit"),
        default="direct_endpoint",
        help="current endpoint publication or frozen two-hop tail holdback prototype",
    )
    args = parser.parse_args()
    if args.dev_speakers is not None and args.dev_speakers < 2:
        parser.error("--dev-speakers must be at least 2")
    if args.test_speakers is not None and args.test_speakers < 2:
        parser.error("--test-speakers must be at least 2")
    if args.speaker_threads <= 0 or args.asr_threads <= 0:
        parser.error("thread counts must be positive")
    return args


def main() -> int:
    args = parse_args()
    rescue.ensure_output_dir(args.output_dir)
    summary_path = args.baseline_dir / "summary.json"
    trials_path = args.baseline_dir / "trials.jsonl"
    for path in (summary_path, trials_path, args.asr_model_dir):
        if not path.exists():
            raise FileNotFoundError(path)
    baseline_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if int(baseline_summary["config"].get("enroll_utterances", 0)) != 3:
        raise ValueError("C1 matrix requires exactly three enrollment utterances")
    baseline_rows = [
        json.loads(line)
        for line in trials_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    pairs = {
        "dev": l2.choose_speaker_pairs(baseline_rows, "dev", args.dev_speakers, args.seed),
        "test": l2.choose_speaker_pairs(baseline_rows, "test", args.test_speakers, args.seed),
    }
    artifacts = baseline_summary["artifacts"]
    speaker_model = args.speaker_model or Path(artifacts["speaker_model"])
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
    audio_cache: dict[str, np.ndarray] = {}
    enrollment_cache: dict[tuple[str, ...], np.ndarray] = {}
    score_cache: dict[tuple[tuple[str, ...], str], float | None] = {}
    asr_cache: dict[str, str] = {}
    cache_counts = {"score_hits": 0, "score_misses": 0, "asr_hits": 0, "asr_misses": 0}

    def audio(path_value: str) -> np.ndarray:
        if path_value not in audio_cache:
            samples, _ = load_audio_mono16k(Path(path_value))
            audio_cache[path_value] = np.ascontiguousarray(samples, dtype=np.float32)
        return audio_cache[path_value]

    def target_embedding(row: dict[str, Any]) -> tuple[tuple[str, ...], np.ndarray]:
        paths = tuple(str(path) for path in row["enrollment_audio_paths"])
        if len(paths) != 3:
            raise ValueError("trial does not contain three enrollment paths")
        if paths not in enrollment_cache:
            enrollment_cache[paths] = enroll(
                extractor, [(audio(path), SAMPLE_RATE) for path in paths]
            )
        return paths, enrollment_cache[paths]

    def score_window(
        enrollment_key: tuple[str, ...], target_value: np.ndarray, window: np.ndarray
    ) -> float | None:
        waveform_hash = hashlib.sha256(window.tobytes()).hexdigest()
        key = (enrollment_key, waveform_hash)
        if key in score_cache:
            cache_counts["score_hits"] += 1
            return score_cache[key]
        cache_counts["score_misses"] += 1
        value = speaker_vad.window_embedding(extractor, window)
        score_cache[key] = None if value is None else float(np.dot(value, target_value))
        return score_cache[key]

    def decode(samples: np.ndarray) -> str:
        waveform_hash = hashlib.sha256(samples.tobytes()).hexdigest()
        if waveform_hash in asr_cache:
            cache_counts["asr_hits"] += 1
            return asr_cache[waveform_hash]
        cache_counts["asr_misses"] += 1
        asr_cache[waveform_hash] = asr_decode_full_segment(recognizer, samples, SAMPLE_RATE)
        return asr_cache[waveform_hash]

    def scenario_specs() -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for gap in TEMPORAL_GAPS_SEC:
            for tail in OTHER_TAILS_SEC:
                specs.append(
                    {
                        "family": "temporal",
                        "gap_sec": gap,
                        "tail_sec": tail,
                        "target_gain_db": 0.0,
                        "other_gain_db": 0.0,
                        "pattern": "realtime_20ms",
                        "run_asr": True,
                    }
                )
        for target_db in TARGET_GAINS_DB:
            for other_db in OTHER_GAINS_DB:
                specs.append(
                    {
                        "family": "volume",
                        "gap_sec": 0.0,
                        "tail_sec": 2.0,
                        "target_gain_db": target_db,
                        "other_gain_db": other_db,
                        "pattern": "realtime_20ms",
                        "run_asr": False,
                    }
                )
        for tail in FRAME_TAILS_SEC:
            for pattern in ("realtime_20ms", "irregular", "single_block"):
                specs.append(
                    {
                        "family": "framing",
                        "gap_sec": 0.0,
                        "tail_sec": tail,
                        "target_gain_db": 0.0,
                        "other_gain_db": 0.0,
                        "pattern": pattern,
                        "run_asr": False,
                    }
                )
        return specs

    output_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    total_pairs = sum(len(value) for value in pairs.values())
    completed_pairs = 0
    specs = scenario_specs()
    for split in ("dev", "test"):
        for target_row, other_row in pairs[split]:
            target_audio = audio(str(target_row["probe_audio_path"]))
            other_audio = audio(str(other_row["probe_audio_path"]))
            target_audio_hash = rescue.sha256(Path(target_row["probe_audio_path"]))
            other_audio_hash = rescue.sha256(Path(other_row["probe_audio_path"]))
            enrollment_key, embedding_value = target_embedding(target_row)
            target_only_text = decode(target_audio)

            def run_one(spec: dict[str, Any]) -> dict[str, Any]:
                session, timing = compose_transition(
                    target_audio,
                    other_audio,
                    gap_sec=float(spec["gap_sec"]),
                    other_tail_sec=float(spec["tail_sec"]),
                    target_gain_db=float(spec["target_gain_db"]),
                    other_gain_db=float(spec["other_gain_db"]),
                )
                points = build_sdk_timeline(
                    session,
                    chunk_pattern=str(spec["pattern"]),
                    score_schedule=args.score_schedule,
                    target_end_sample=int(timing["target_end_sample"]),
                    other_start_sample=int(timing["other_start_sample"]),
                    score_window=lambda window: score_window(
                        enrollment_key, embedding_value, window
                    ),
                )
                result = speaker_vad.simulate(
                    points,
                    threshold=FROZEN_THRESHOLD,
                    consecutive_below=CONSECUTIVE_BELOW,
                    total_sec=len(session) / SAMPLE_RATE,
                )
                endpoint_sec = float(result.endpoint_sec or len(session) / SAMPLE_RATE)
                commit = publication_decision(
                    result,
                    total_samples=len(session),
                    policy=args.publication_policy,
                )
                endpoint_sample = commit.publish_samples
                publication_cutoff_sec = endpoint_sample / SAMPLE_RATE
                public_boundary_sec = (
                    publication_cutoff_sec
                    if args.publication_policy == "buffered_tail_commit"
                    else endpoint_sec
                )
                target_end_sec = int(timing["target_end_sample"]) / SAMPLE_RATE
                other_start_sec = int(timing["other_start_sample"]) / SAMPLE_RATE
                other_end_sec = int(timing["other_end_sample"]) / SAMPLE_RATE
                target_confirmed = result.target_confirm_sec is not None
                row: dict[str, Any] = {
                    "split": split,
                    "family": spec["family"],
                    "anchor_kind": None,
                    "target_speaker": target_row["target_speaker"],
                    "other_speaker": other_row["target_speaker"],
                    "target_recording_id": target_row["probe_recording_id"],
                    "other_recording_id": other_row["probe_recording_id"],
                    "target_audio_path": target_row["probe_audio_path"],
                    "other_audio_path": other_row["probe_audio_path"],
                    "target_audio_sha256": target_audio_hash,
                    "other_audio_sha256": other_audio_hash,
                    "enrollment_audio_paths": list(enrollment_key),
                    "target_reference_text": target_row["reference_text"],
                    "other_reference_text": other_row["reference_text"],
                    "gap_sec": spec["gap_sec"],
                    "requested_other_tail_sec": spec["tail_sec"],
                    "other_actual_sec": int(timing["actual_other_samples"]) / SAMPLE_RATE,
                    "target_gain_db": spec["target_gain_db"],
                    "other_gain_db": spec["other_gain_db"],
                    "peak_scale": timing["peak_scale"],
                    "chunk_pattern": spec["pattern"],
                    "session_pcm_sha256": hashlib.sha256(session.tobytes()).hexdigest(),
                    "session_sec": len(session) / SAMPLE_RATE,
                    "target_end_sec": target_end_sec,
                    "target_duration_bucket": target_duration_bucket(target_end_sec),
                    "other_start_sec": other_start_sec,
                    "other_end_sec": other_end_sec,
                    "state": result.state,
                    "target_confirmed": target_confirmed,
                    "target_confirm_sec": result.target_confirm_sec,
                    "endpoint_sec": endpoint_sec,
                    "publication_cutoff_sec": publication_cutoff_sec,
                    "publication_reason": commit.reason,
                    "tail_rollback_sec": commit.rollback_samples / SAMPLE_RATE,
                    "target_truncated_sec": max(0.0, target_end_sec - public_boundary_sec),
                    "other_leak_sec": max(
                        0.0, min(public_boundary_sec, other_end_sec) - other_start_sec
                    ),
                    "timeline": [asdict(point) for point in points],
                    "target_only_text": None,
                    "baseline_text": None,
                    "endpoint_asr_text": None,
                    "published_text": None,
                }
                if spec["run_asr"]:
                    endpoint_text = decode(session[:endpoint_sample]) if endpoint_sample else ""
                    row["target_only_text"] = target_only_text
                    row["baseline_text"] = decode(session)
                    row["endpoint_asr_text"] = endpoint_text
                    row["published_text"] = endpoint_text if target_confirmed else ""
                return row

            for spec in specs:
                output_rows.append(run_one(spec))

            for kind, source in (("target_only", target_audio), ("other_only", other_audio)):
                for pattern in ("realtime_20ms", "irregular", "single_block"):
                    if kind == "target_only":
                        target_end_sample = len(source)
                        other_start_sample = len(source)
                    else:
                        target_end_sample = 0
                        other_start_sample = 0
                    points = build_sdk_timeline(
                        source,
                        chunk_pattern=pattern,
                        score_schedule=args.score_schedule,
                        target_end_sample=target_end_sample,
                        other_start_sample=other_start_sample,
                        score_window=lambda window: score_window(
                            enrollment_key, embedding_value, window
                        ),
                    )
                    result = speaker_vad.simulate(
                        points,
                        threshold=FROZEN_THRESHOLD,
                        consecutive_below=CONSECUTIVE_BELOW,
                        total_sec=len(source) / SAMPLE_RATE,
                    )
                    endpoint_sec = float(result.endpoint_sec or len(source) / SAMPLE_RATE)
                    commit = publication_decision(
                        result,
                        total_samples=len(source),
                        policy=args.publication_policy,
                    )
                    publication_cutoff_sec = commit.publish_samples / SAMPLE_RATE
                    public_boundary_sec = (
                        publication_cutoff_sec
                        if args.publication_policy == "buffered_tail_commit"
                        else endpoint_sec
                    )
                    output_rows.append(
                        {
                            "split": split,
                            "family": "anchor",
                            "anchor_kind": kind,
                            "target_speaker": target_row["target_speaker"],
                            "other_speaker": other_row["target_speaker"],
                            "target_recording_id": target_row["probe_recording_id"],
                            "other_recording_id": other_row["probe_recording_id"],
                            "requested_other_tail_sec": 0.0,
                            "target_gain_db": 0.0,
                            "other_gain_db": 0.0,
                            "chunk_pattern": pattern,
                            "state": result.state,
                            "target_confirmed": result.target_confirm_sec is not None,
                            "target_confirm_sec": result.target_confirm_sec,
                            "endpoint_sec": endpoint_sec,
                            "publication_cutoff_sec": publication_cutoff_sec,
                            "publication_reason": commit.reason,
                            "tail_rollback_sec": commit.rollback_samples / SAMPLE_RATE,
                            "target_end_sec": len(source) / SAMPLE_RATE if kind == "target_only" else 0.0,
                            "target_truncated_sec": (
                                max(0.0, len(source) / SAMPLE_RATE - public_boundary_sec)
                                if kind == "target_only"
                                else 0.0
                            ),
                            "other_actual_sec": len(source) / SAMPLE_RATE if kind == "other_only" else 0.0,
                            "other_leak_sec": public_boundary_sec if kind == "other_only" else 0.0,
                            "timeline": [asdict(point) for point in points],
                        }
                    )

            completed_pairs += 1
            if args.progress_every > 0 and completed_pairs % args.progress_every == 0:
                print(
                    f"processed pairs {completed_pairs}/{total_pairs}; rows={len(output_rows)}",
                    file=sys.stderr,
                    flush=True,
                )

    metrics = {
        split: {
            "temporal": temporal_metrics(output_rows, split),
            "volume": volume_metrics(output_rows, split),
            "framing": framing_metrics(output_rows, split),
            "anchors": anchor_metrics(output_rows, split),
        }
        for split in ("dev", "test")
        if pairs[split]
    }
    status, failures = strict_gate(metrics)
    summary = {
        "study": "c1-speaker-vad-target-to-other-synthetic",
        "status": "diagnostic_only",
        "configuration": {
            "threshold": FROZEN_THRESHOLD,
            "win_sec": WIN_SEC,
            "hop_sec": HOP_SEC,
            "consecutive_below": CONSECUTIVE_BELOW,
            "temporal_gaps_sec": TEMPORAL_GAPS_SEC,
            "other_tails_sec": OTHER_TAILS_SEC,
            "target_gains_db": TARGET_GAINS_DB,
            "other_gains_db": OTHER_GAINS_DB,
            "frame_tails_sec": FRAME_TAILS_SEC,
            "chunk_patterns": ["realtime_20ms", "irregular", "single_block"],
            "score_schedule": args.score_schedule,
            "publication_policy": args.publication_policy,
            "tail_holdback_sec": TAIL_HOLDBACK_SAMPLES / SAMPLE_RATE,
            "maximum_steady_partial_delay_sec": (
                TAIL_HOLDBACK_SAMPLES / SAMPLE_RATE
                if args.publication_policy == "buffered_tail_commit"
                else 0.0
            ),
            "seed": args.seed,
        },
        "artifacts": {
            "baseline_dir": str(args.baseline_dir),
            "baseline_summary_sha256": rescue.sha256(summary_path),
            "baseline_trials_sha256": rescue.sha256(trials_path),
            "speaker_model": str(speaker_model),
            "speaker_model_sha256": rescue.sha256(speaker_model),
            "asr_model_dir": str(args.asr_model_dir),
            "asr_model_files": asr_artifacts,
        },
        "trial_counts": {
            "total_rows": len(output_rows),
            "dev_speakers": len(pairs["dev"]),
            "test_speakers": len(pairs["test"]),
            "test_distinct_other_speakers": len(
                {str(other["target_speaker"]) for _, other in pairs["test"]}
            ),
        },
        "metrics": metrics,
        "decision": {"status": status, "failures": failures},
        "runtime": {
            "total_seconds": time.perf_counter() - started,
            "cache": cache_counts,
            "packages": rescue.package_versions(),
        },
        "limitations": [
            "AISHELL-2 deterministic synthetic turn transitions only",
            "full other transcript is used for conservative LCS attribution after tail cropping",
            "Silero VAD and ASR native endpoint may end earlier than this isolated Speaker VAD simulation",
            "no real device acoustics or SDK callback lifecycle validation",
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
