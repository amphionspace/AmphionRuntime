#!/usr/bin/env python3
"""Evaluate Android-style target speaker VAD on a packaged multi-speaker corpus.

It is meant to quantify the endpoint benefit of target-speaker VAD by
synthesizing sessions:

    target speaker utterance + non-target speaker utterance

Without speaker VAD, a normal speech VAD would keep the whole concatenated
speech as one utterance when there is no silence gap. With speaker VAD, the
state machine should endpoint shortly after the target speaker leaves.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
TEST_DATA_ROOT = Path(
    os.environ.get(
        "AMPHION_TEST_DATA_DIR",
        Path.home() / ".cache/amphion-runtime/test-data/v1",
    )
).expanduser()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ts_asr import build_speaker, enroll, load_audio_mono16k  # noqa: E402


@dataclass(frozen=True)
class Sample:
    recording_id: str
    speaker: str
    audio_path: Path
    duration_sec: float
    text: str


@dataclass(frozen=True)
class TimelinePoint:
    time_sec: float
    score: float
    region: str


@dataclass(frozen=True)
class SimResult:
    state: str
    endpoint_sec: float | None
    target_confirm_sec: float | None
    below_count: int


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(xs[lo])
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def describe(values: list[float]) -> dict:
    clean = [float(v) for v in values if math.isfinite(v)]
    if not clean:
        return {"n": 0}
    return {
        "n": len(clean),
        "min": min(clean),
        "p10": percentile(clean, 0.10),
        "p50": percentile(clean, 0.50),
        "p90": percentile(clean, 0.90),
        "max": max(clean),
        "mean": statistics.fmean(clean),
    }


def load_samples(dataset_dir: Path) -> list[Sample]:
    candidates = (
        (
            "aidatatang_test_spk_balanced_500_recordings_packaged.jsonl.gz",
            "aidatatang_test_spk_balanced_500_supervisions_cleaned_punc.jsonl.gz",
        ),
        (
            "aishell3_test_hotwords_500_recordings_packaged.jsonl.gz",
            "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz",
        ),
    )
    selected = next(
        (
            (dataset_dir / recordings, dataset_dir / supervisions)
            for recordings, supervisions in candidates
            if (dataset_dir / recordings).is_file()
            and (dataset_dir / supervisions).is_file()
        ),
        None,
    )
    if selected is None:
        raise FileNotFoundError(f"no supported packaged corpus manifest under {dataset_dir}")
    recordings_path, supervisions_path = selected
    recordings: dict[str, dict] = {}
    with gzip.open(recordings_path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            recordings[rec["id"]] = rec

    samples: list[Sample] = []
    with gzip.open(supervisions_path, "rt", encoding="utf-8") as f:
        for line in f:
            sup = json.loads(line)
            rec = recordings[sup["recording_id"]]
            rel = rec["sources"][0]["source"]
            samples.append(
                Sample(
                    recording_id=sup["recording_id"],
                    speaker=sup["speaker"],
                    audio_path=dataset_dir / rel,
                    duration_sec=float(sup["duration"]),
                    text=sup.get("text") or "",
                )
            )
    samples.sort(key=lambda s: s.recording_id)
    return samples


def embedding_for_samples(extractor, samples: np.ndarray) -> np.ndarray:
    return enroll(extractor, [(samples, 16000)])


def window_embedding(extractor, samples: np.ndarray) -> np.ndarray | None:
    import sherpa_onnx

    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=16000, waveform=samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        return None
    emb = np.asarray(extractor.compute(stream), dtype=np.float32)
    return emb / (np.linalg.norm(emb) + 1e-9)


def build_timeline(
    extractor,
    target_emb: np.ndarray,
    session: np.ndarray,
    *,
    target_samples: int,
    win_sec: float,
    hop_sec: float,
) -> list[TimelinePoint]:
    win = int(win_sec * 16000)
    hop = int(hop_sec * 16000)
    points: list[TimelinePoint] = []
    for end in range(win, len(session) + 1, hop):
        start = end - win
        emb = window_embedding(extractor, session[start:end])
        if emb is None:
            continue
        score = float(np.dot(emb, target_emb))
        if end <= target_samples:
            region = "target"
        elif start >= target_samples:
            region = "other"
        else:
            region = "transition"
        points.append(TimelinePoint(end / 16000.0, score, region))
    return points


def simulate(
    points: Iterable[TimelinePoint],
    *,
    threshold: float,
    consecutive_below: int,
    total_sec: float,
) -> SimResult:
    target_confirmed = False
    below_count = 0
    target_confirm_sec: float | None = None
    for p in points:
        if not target_confirmed:
            if p.score >= threshold:
                target_confirmed = True
                below_count = 0
                target_confirm_sec = p.time_sec
            else:
                below_count += 1
                if below_count >= consecutive_below:
                    return SimResult("pre_target_endpoint", p.time_sec, None, below_count)
            continue

        if p.score < threshold:
            below_count += 1
            if below_count >= consecutive_below:
                return SimResult("endpoint", p.time_sec, target_confirm_sec, below_count)
        else:
            below_count = 0

    state = "target_confirmed_no_endpoint" if target_confirmed else "target_not_confirmed"
    return SimResult(state, total_sec, target_confirm_sec, below_count)


def row_for_threshold(
    pair_records: list[dict],
    *,
    threshold: float,
    consecutive_below: int,
    truncation_tolerance_sec: float,
) -> dict:
    total_other_sec = 0.0
    leak_without_sec = 0.0
    leak_with_sec = 0.0
    endpoint_delays: list[float] = []
    endpoint_advances: list[float] = []
    target_confirm_times: list[float] = []
    states: dict[str, int] = {}
    truncations = 0
    for rec in pair_records:
        target_sec = rec["target_duration_sec"]
        other_sec = rec["other_duration_sec"]
        total_sec = target_sec + other_sec
        result = simulate(
            rec["timeline"],
            threshold=threshold,
            consecutive_below=consecutive_below,
            total_sec=total_sec,
        )
        states[result.state] = states.get(result.state, 0) + 1
        total_other_sec += other_sec
        leak_without_sec += other_sec
        endpoint_sec = result.endpoint_sec if result.endpoint_sec is not None else total_sec
        leaked = min(max(endpoint_sec - target_sec, 0.0), other_sec)
        leak_with_sec += leaked
        endpoint_advances.append(max(total_sec - endpoint_sec, 0.0))
        if result.target_confirm_sec is not None:
            target_confirm_times.append(result.target_confirm_sec)
        if endpoint_sec < target_sec - truncation_tolerance_sec:
            truncations += 1
        if result.state == "endpoint" and endpoint_sec >= target_sec:
            endpoint_delays.append(endpoint_sec - target_sec)

    n = len(pair_records)
    return {
        "threshold": threshold,
        "n_pairs": n,
        "states": states,
        "target_confirm_rate": 1.0
        - states.get("pre_target_endpoint", 0) / n
        - states.get("target_not_confirmed", 0) / n,
        "speaker_endpoint_rate": states.get("endpoint", 0) / n,
        "target_truncation_rate": truncations / n,
        "non_target_leak_without_sec": leak_without_sec,
        "non_target_leak_with_sec": leak_with_sec,
        "non_target_leak_reduction_rate": (
            1.0 - leak_with_sec / leak_without_sec if leak_without_sec > 0 else None
        ),
        "endpoint_advance_sec": describe(endpoint_advances),
        "endpoint_delay_after_target_sec": describe(endpoint_delays),
        "target_confirm_sec": describe(target_confirm_times),
        "avg_non_target_leak_without_sec": leak_without_sec / n,
        "avg_non_target_leak_with_sec": leak_with_sec / n,
    }


def render_md(summary: dict) -> str:
    lines: list[str] = []
    lines.append("# 主说话人 VAD 评测")
    lines.append("")
    lines.append("## 评测口径")
    lines.append("")
    lines.append(
        "把 500 个说话人样本按顺序组成 500 组 target + other 会话；target 用自身音频注册，other 用下一位说话人的音频。"
    )
    lines.append(
        "无 speaker-VAD 时，假设两段连续语音会被普通 VAD 合成一个 utterance；开启 speaker-VAD 时，复刻 Android 状态机，连续低于阈值后提前 endpoint。"
    )
    lines.append("")
    lines.append("## 数据集")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 样本数 | {summary['dataset']['num_samples']} |")
    lines.append(f"| 说话人数 | {summary['dataset']['num_speakers']} |")
    lines.append(f"| 总时长秒 | {summary['dataset']['total_duration_sec']:.3f} |")
    lines.append(f"| 单条时长 p50 秒 | {summary['dataset']['duration_sec']['p50']:.3f} |")
    lines.append("")
    lines.append("## 阈值扫描")
    lines.append("")
    lines.append("| threshold | target确认率 | speaker endpoint率 | target截断率 | 非目标泄露降幅 | 平均非目标泄露 无/有(s) | endpoint提前 p50/p90(s) | target后endpoint延迟 p50/p90(s) |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in summary["threshold_rows"]:
        advance = row["endpoint_advance_sec"]
        delay = row["endpoint_delay_after_target_sec"]
        lines.append(
            "| "
            f"{row['threshold']:.2f} | "
            f"{row['target_confirm_rate']:.2%} | "
            f"{row['speaker_endpoint_rate']:.2%} | "
            f"{row['target_truncation_rate']:.2%} | "
            f"{row['non_target_leak_reduction_rate']:.2%} | "
            f"{row['avg_non_target_leak_without_sec']:.3f}/{row['avg_non_target_leak_with_sec']:.3f} | "
            f"{(advance.get('p50') or 0):.3f}/{(advance.get('p90') or 0):.3f} | "
            f"{(delay.get('p50') or 0):.3f}/{(delay.get('p90') or 0):.3f} |"
        )
    lines.append("")
    lines.append("## 分数分布")
    lines.append("")
    lines.append("| 窗口区域 | n | p10 | p50 | p90 | mean |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for name, stats in summary["score_distribution"].items():
        lines.append(
            f"| {name} | {stats.get('n', 0)} | "
            f"{(stats.get('p10') or 0):.3f} | "
            f"{(stats.get('p50') or 0):.3f} | "
            f"{(stats.get('p90') or 0):.3f} | "
            f"{(stats.get('mean') or 0):.3f} |"
        )
    lines.append("")
    lines.append("## 限制")
    lines.append("")
    lines.append("- 注册与目标段使用同一条 utterance，target 确认率会偏乐观；该门禁只用于状态机收益复现。")
    lines.append("- 本报告只量 speaker-VAD endpoint 对非目标拖尾的抑制收益，不包含 ASR CER/WER。")
    lines.append("- 合成会话为 target 与 other 无静音拼接，是刻意放大“目标人离场后别人继续说”的压力场景。")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dataset-dir",
        type=Path,
        default=TEST_DATA_ROOT / "aishell3_test_hotwords_500",
    )
    p.add_argument(
        "--speaker-model",
        type=Path,
        default=Path(
            "asr/android/sdk-dingqiao/src/main/assets/amphion-dingqiao/eres2net.onnx"
        ),
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("asr/tools/speaker/results/aidatatang_speaker_vad_eval"),
    )
    p.add_argument("--thresholds", type=float, nargs="+", default=[0.30, 0.35, 0.40, 0.45, 0.50])
    p.add_argument("--win-sec", type=float, default=1.0)
    p.add_argument("--hop-sec", type=float, default=0.3)
    p.add_argument("--consecutive-below", type=int, default=2)
    p.add_argument("--max-pairs", type=int, default=None)
    p.add_argument("--num-threads", type=int, default=1)
    p.add_argument("--print-every", type=int, default=25)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.speaker_model = args.speaker_model.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    samples = load_samples(args.dataset_dir)
    if args.max_pairs is not None:
        samples = samples[: args.max_pairs]
    if len(samples) < 2:
        print("[ERROR] need at least 2 samples", file=sys.stderr)
        return 2

    extractor = build_speaker(args.speaker_model, num_threads=args.num_threads)
    t0 = time.time()
    audio: dict[str, np.ndarray] = {}
    target_embs: dict[str, np.ndarray] = {}
    for i, s in enumerate(samples):
        x, _ = load_audio_mono16k(s.audio_path)
        audio[s.recording_id] = x
        target_embs[s.recording_id] = embedding_for_samples(extractor, x)
        if args.print_every > 0 and (i + 1) % args.print_every == 0:
            print(f"[EMB] {i + 1}/{len(samples)}", file=sys.stderr)

    pair_records: list[dict] = []
    score_by_region: dict[str, list[float]] = {"target": [], "transition": [], "other": []}
    n_pairs = len(samples)
    for i, target in enumerate(samples):
        other = samples[(i + 1) % len(samples)]
        target_audio = audio[target.recording_id]
        other_audio = audio[other.recording_id]
        session = np.concatenate([target_audio, other_audio])
        timeline = build_timeline(
            extractor,
            target_embs[target.recording_id],
            session,
            target_samples=len(target_audio),
            win_sec=args.win_sec,
            hop_sec=args.hop_sec,
        )
        for p in timeline:
            score_by_region[p.region].append(p.score)
        pair_records.append(
            {
                "target_id": target.recording_id,
                "target_speaker": target.speaker,
                "other_id": other.recording_id,
                "other_speaker": other.speaker,
                "target_duration_sec": len(target_audio) / 16000.0,
                "other_duration_sec": len(other_audio) / 16000.0,
                "timeline": timeline,
            }
        )
        if args.print_every > 0 and (i + 1) % args.print_every == 0:
            print(f"[PAIR] {i + 1}/{n_pairs}", file=sys.stderr)

    duration_values = [len(audio[s.recording_id]) / 16000.0 for s in samples]
    threshold_rows = [
        row_for_threshold(
            pair_records,
            threshold=thr,
            consecutive_below=args.consecutive_below,
            truncation_tolerance_sec=args.hop_sec,
        )
        for thr in args.thresholds
    ]
    summary = {
        "config": {
            "dataset_dir": str(args.dataset_dir),
            "speaker_model": str(args.speaker_model),
            "win_sec": args.win_sec,
            "hop_sec": args.hop_sec,
            "consecutive_below": args.consecutive_below,
            "thresholds": args.thresholds,
            "elapsed_sec": time.time() - t0,
        },
        "dataset": {
            "num_samples": len(samples),
            "num_speakers": len({s.speaker for s in samples}),
            "total_duration_sec": sum(duration_values),
            "duration_sec": describe(duration_values),
        },
        "score_distribution": {
            region: describe(values) for region, values in score_by_region.items()
        },
        "threshold_rows": threshold_rows,
    }

    json_path = args.out_dir / "summary.json"
    md_path = args.out_dir / "summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_md(summary), encoding="utf-8")
    print(f"[OK] wrote {json_path}", file=sys.stderr)
    print(f"[OK] wrote {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
