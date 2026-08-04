#!/usr/bin/env python3
"""Run a small, reproducible speaker-verification pilot from Lhotse cut shards.

This is a clean-domain diagnostic, not a commercial acceptance gate. Speakers are
disjoint between dev and test. Enrollment and probe utterances are distinct, but
the source manifests may not provide independent session/date metadata.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ts_asr import (  # noqa: E402
    asr_decode_full_segment,
    build_denoiser,
    build_recognizer,
    build_speaker,
    denoise_audio,
    enroll,
    load_audio_mono16k,
    segment_score,
)


@dataclass(frozen=True)
class Utterance:
    recording_id: str
    speaker: str
    audio_path: Path
    duration_sec: float
    text: str
    session_id: str | None = None


@dataclass(frozen=True)
class NoiseSample:
    cut_id: str
    audio_path: Path


def arrange_session_disjoint(
    rows: Sequence[Utterance],
    *,
    enroll_utterances: int,
    probe_start: int,
    target_probes: int,
) -> list[Utterance] | None:
    """Arrange one enrollment session before probes from a different session."""
    if probe_start < enroll_utterances:
        raise ValueError("probe_start must not overlap enrollment utterances")
    by_session: dict[str, list[Utterance]] = {}
    for row in rows:
        if row.session_id is not None:
            by_session.setdefault(row.session_id, []).append(row)
    for enrollment_session, enrollment_rows in by_session.items():
        if len(enrollment_rows) < enroll_utterances:
            continue
        for probe_session, probe_rows in by_session.items():
            if probe_session == enrollment_session or len(probe_rows) < target_probes:
                continue
            selected_enrollment = enrollment_rows[:enroll_utterances]
            selected_probes = probe_rows[:target_probes]
            selected_ids = {row.recording_id for row in selected_enrollment + selected_probes}
            fillers = [row for row in rows if row.recording_id not in selected_ids]
            filler_count = probe_start - enroll_utterances
            if len(fillers) < filler_count:
                continue
            return selected_enrollment + fillers[:filler_count] + selected_probes
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_speakers(
    cut_paths: Sequence[Path],
    *,
    required_utterances: int,
    required_speakers: int,
    min_duration_sec: float,
    max_duration_sec: float,
    stop_when_ready: bool = True,
    session_id_regex: str | None = None,
    enroll_utterances: int | None = None,
    probe_start: int | None = None,
    target_probes: int | None = None,
) -> tuple[dict[str, list[Utterance]], dict[str, int]]:
    """Collect speakers with distinct, readable utterances from streamed shards."""
    session_pattern = re.compile(session_id_regex) if session_id_regex else None
    if session_pattern and None in (enroll_utterances, probe_start, target_probes):
        raise ValueError("session-disjoint collection requires enrollment/probe layout")

    def arranged(bucket: Sequence[Utterance]) -> list[Utterance] | None:
        if session_pattern is None:
            return list(bucket) if len(bucket) >= required_utterances else None
        return arrange_session_disjoint(
            bucket,
            enroll_utterances=int(enroll_utterances),
            probe_start=int(probe_start),
            target_probes=int(target_probes),
        )

    def materialize() -> dict[str, list[Utterance]]:
        selected: dict[str, list[Utterance]] = {}
        for key, bucket in by_speaker.items():
            ordered = arranged(bucket)
            if ordered is not None:
                selected[key] = ordered
        return selected

    by_speaker: dict[str, list[Utterance]] = {}
    seen_recordings: dict[str, set[str]] = {}
    complete_speakers = 0
    counters = {
        "rows_seen": 0,
        "missing_speaker": 0,
        "duration_out_of_range": 0,
        "unsupported_source": 0,
        "missing_audio": 0,
        "duplicate_recording": 0,
        "session_id_mismatch": 0,
    }
    for cut_path in cut_paths:
        opener = gzip.open if cut_path.name.endswith(".gz") else open
        with opener(cut_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                counters["rows_seen"] += 1
                cut = json.loads(line)
                supervisions = cut.get("supervisions") or []
                if not supervisions:
                    counters["missing_speaker"] += 1
                    continue
                supervision = supervisions[0]
                speaker = str(supervision.get("speaker") or "").strip()
                if not speaker or speaker.upper() == "N/A":
                    counters["missing_speaker"] += 1
                    continue
                bucket = by_speaker.setdefault(speaker, [])
                if arranged(bucket) is not None:
                    continue
                duration = float(cut.get("duration") or supervision.get("duration") or 0.0)
                if duration < min_duration_sec or duration > max_duration_sec:
                    counters["duration_out_of_range"] += 1
                    continue
                sources = (cut.get("recording") or {}).get("sources") or []
                if not sources or sources[0].get("type") != "file":
                    counters["unsupported_source"] += 1
                    continue
                audio_path = Path(str(sources[0].get("source") or ""))
                if not audio_path.is_file():
                    counters["missing_audio"] += 1
                    continue
                recording_id = str(supervision.get("recording_id") or cut.get("id") or "")
                session_id = None
                if session_pattern is not None:
                    match = session_pattern.search(recording_id)
                    if match is None:
                        counters["session_id_mismatch"] += 1
                        continue
                    if "session" in match.groupdict():
                        session_id = match.group("session")
                    elif match.lastindex:
                        session_id = match.group(1)
                    else:
                        session_id = match.group(0)
                speaker_seen = seen_recordings.setdefault(speaker, set())
                if recording_id in speaker_seen:
                    counters["duplicate_recording"] += 1
                    continue
                speaker_seen.add(recording_id)
                bucket.append(
                    Utterance(
                        recording_id,
                        speaker,
                        audio_path,
                        duration,
                        str(supervision.get("text") or ""),
                        session_id,
                    )
                )

                if arranged(bucket) is not None:
                    complete_speakers += 1
                if stop_when_ready and complete_speakers >= required_speakers:
                    return materialize(), counters
    return materialize(), counters


def collect_noise_samples(cut_path: Path, *, limit: int = 16) -> list[NoiseSample]:
    samples: list[NoiseSample] = []
    opener = gzip.open if cut_path.name.endswith(".gz") else open
    with opener(cut_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            cut = json.loads(line)
            sources = (cut.get("recording") or {}).get("sources") or []
            if not sources or sources[0].get("type") != "file":
                continue
            path = Path(str(sources[0].get("source") or ""))
            if not path.is_file():
                continue
            samples.append(NoiseSample(str(cut.get("id") or path.name), path))
            if len(samples) >= limit:
                break
    if not samples:
        raise RuntimeError(f"no readable noise samples found in {cut_path}")
    return samples


def mix_at_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """Mix deterministic repeated noise at the requested full-utterance RMS SNR."""
    speech = np.asarray(speech, dtype=np.float32)
    noise = np.asarray(noise, dtype=np.float32)
    if not len(speech) or not len(noise):
        raise ValueError("speech and noise must be non-empty")
    if len(noise) < len(speech):
        noise = np.tile(noise, math.ceil(len(speech) / len(noise)))
    noise = noise[: len(speech)]
    speech_rms = float(np.sqrt(np.mean(np.square(speech), dtype=np.float64)))
    noise_rms = float(np.sqrt(np.mean(np.square(noise), dtype=np.float64)))
    if speech_rms <= 1e-9 or noise_rms <= 1e-9:
        raise ValueError("speech or noise RMS is zero")
    scale = speech_rms / (10.0 ** (snr_db / 20.0) * noise_rms)
    mixed = speech + noise * scale
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.99:
        mixed = mixed * (0.99 / peak)
    return np.ascontiguousarray(mixed, dtype=np.float32)


def scale_waveform_for_extractor(samples: np.ndarray, scale: float) -> np.ndarray:
    """Apply a model-specific PCM scale without changing ASR/noise-mix audio."""
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("waveform scale must be finite and positive")
    return np.ascontiguousarray(np.asarray(samples, dtype=np.float32) * scale)


def augment_enrollment_audio(
    clean_audio: Sequence[tuple[np.ndarray, int]],
    noise_pool: Sequence[tuple[NoiseSample, np.ndarray]],
    snr_db_values: Sequence[float],
) -> list[tuple[np.ndarray, int]]:
    """Keep every clean enrollment and append deterministic noisy copies."""
    result = [(np.asarray(samples, dtype=np.float32), sample_rate) for samples, sample_rate in clean_audio]
    if not snr_db_values:
        return result
    if not noise_pool:
        raise ValueError("enrollment noise augmentation requires a non-empty noise pool")
    for audio_index, (samples, sample_rate) in enumerate(clean_audio):
        for snr_index, snr_db in enumerate(snr_db_values):
            _, noise = noise_pool[
                (audio_index * len(snr_db_values) + snr_index) % len(noise_pool)
            ]
            result.append((mix_at_snr(samples, noise, snr_db), sample_rate))
    return result


def binary_metrics(scores: Sequence[float], labels: Sequence[int], threshold: float) -> dict:
    positives = [score for score, label in zip(scores, labels) if label == 1]
    negatives = [score for score, label in zip(scores, labels) if label == 0]
    false_accepts = sum(score >= threshold for score in negatives)
    false_rejects = sum(score < threshold for score in positives)
    far_ci95 = wilson_interval(false_accepts, len(negatives)) if negatives else None
    frr_ci95 = wilson_interval(false_rejects, len(positives)) if positives else None
    return {
        "threshold": threshold,
        "positive_trials": len(positives),
        "negative_trials": len(negatives),
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "far": false_accepts / len(negatives) if negatives else None,
        "frr": false_rejects / len(positives) if positives else None,
        "far_wilson_95": far_ci95,
        "frr_wilson_95": frr_ci95,
    }


def wilson_interval(errors: int, trials: int) -> list[float]:
    """Two-sided 95% Wilson score interval for a binomial error rate."""
    if trials <= 0:
        raise ValueError("trials must be positive")
    z = 1.959963984540054
    rate = errors / trials
    denominator = 1.0 + z * z / trials
    center = (rate + z * z / (2.0 * trials)) / denominator
    margin = (
        z
        * math.sqrt(rate * (1.0 - rate) / trials + z * z / (4.0 * trials * trials))
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def select_eer_threshold(scores: Sequence[float], labels: Sequence[int]) -> dict:
    """Choose a deterministic dev threshold at the closest FAR/FRR point."""
    unique = sorted(set(float(score) for score in scores))
    if not unique:
        raise ValueError("cannot select a threshold without scores")
    eps = 1e-7
    candidates = [unique[0] - eps]
    candidates.extend((left + right) / 2.0 for left, right in zip(unique, unique[1:]))
    candidates.append(unique[-1] + eps)
    rows = [binary_metrics(scores, labels, threshold) for threshold in candidates]
    best = min(
        rows,
        key=lambda row: (
            abs(float(row["far"]) - float(row["frr"])),
            (float(row["far"]) + float(row["frr"])) / 2.0,
            row["threshold"],
        ),
    )
    return {**best, "eer_approx": (float(best["far"]) + float(best["frr"])) / 2.0}


def choose_operating_threshold(
    scores: Sequence[float], labels: Sequence[int], fixed_threshold: float | None
) -> tuple[dict, dict]:
    """Return a frozen operating point and a separate dev diagnostic EER."""
    diagnostic = select_eer_threshold(scores, labels)
    if fixed_threshold is None:
        return {**diagnostic, "source": "dev_eer"}, diagnostic
    return {
        **binary_metrics(scores, labels, fixed_threshold),
        "source": "cli_fixed",
    }, diagnostic


def describe(values: Sequence[float]) -> dict:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"n": 0}

    def percentile(q: float) -> float:
        position = (len(ordered) - 1) * q
        low = math.floor(position)
        high = math.ceil(position)
        if low == high:
            return ordered[low]
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "n": len(ordered),
        "min": ordered[0],
        "p10": percentile(0.10),
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def normalize_characters(text: str) -> list[str]:
    return [
        character.lower()
        for character in text
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    ]


def edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, reference_item in enumerate(reference, 1):
        current = [row]
        for column, hypothesis_item in enumerate(hypothesis, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (reference_item != hypothesis_item),
                )
            )
        previous = current
    return previous[-1]


def asr_metrics(rows: Sequence[dict], threshold: float) -> dict:
    baseline_edits = 0
    gated_edits = 0
    reference_characters = 0
    negative_trials = 0
    negative_accepted = 0
    negative_leaked_characters = 0
    for row in rows:
        hypothesis = str(row.get("asr_text") or "")
        if row["label"] == 1:
            reference_chars = normalize_characters(str(row.get("reference_text") or ""))
            hypothesis_chars = normalize_characters(hypothesis)
            reference_characters += len(reference_chars)
            baseline_edits += edit_distance(reference_chars, hypothesis_chars)
            gated_hypothesis = hypothesis_chars if row["score"] >= threshold else []
            gated_edits += edit_distance(reference_chars, gated_hypothesis)
        else:
            negative_trials += 1
            if row["score"] >= threshold:
                negative_accepted += 1
                negative_leaked_characters += len(normalize_characters(hypothesis))
    return {
        "target_trials": sum(row["label"] == 1 for row in rows),
        "reference_characters": reference_characters,
        "baseline_target_cer": baseline_edits / reference_characters if reference_characters else None,
        "gated_target_cer": gated_edits / reference_characters if reference_characters else None,
        "negative_trials": negative_trials,
        "negative_accepted": negative_accepted,
        "negative_acceptance_rate": negative_accepted / negative_trials if negative_trials else None,
        "accepted_non_target_hypothesis_characters": negative_leaked_characters,
    }


def run_split(
    extractor,
    split: str,
    speakers: Sequence[str],
    utterances: dict[str, list[Utterance]],
    *,
    enroll_utterances: int,
    probe_start: int,
    target_probes: int,
    negatives_per_target: int,
    win_sec: float,
    hop_sec: float,
    min_duration_sec: float,
    waveform_scale: float,
    score_aggregation: str = "max",
    enrollment_noise_pool: Sequence[tuple[NoiseSample, np.ndarray]] = (),
    enroll_noise_snr_db: Sequence[float] = (),
    noise_pool: Sequence[tuple[NoiseSample, np.ndarray]] = (),
    snr_db: float | None = None,
    denoiser=None,
    denoise_enrollment: bool = True,
    recognizer=None,
) -> list[dict]:
    trials: list[dict] = []
    probe_by_speaker = {
        speaker: utterances[speaker][probe_start : probe_start + target_probes]
        for speaker in speakers
    }
    for index, target_speaker in enumerate(speakers):
        enrollment_rows = utterances[target_speaker][:enroll_utterances]
        clean_enrollment_audio = [
            load_audio_mono16k(row.audio_path) for row in enrollment_rows
        ]
        if denoiser is not None and denoise_enrollment:
            clean_enrollment_audio = [
                denoise_audio(denoiser, samples, sample_rate)
                for samples, sample_rate in clean_enrollment_audio
            ]
        enrollment_audio = [
            (scale_waveform_for_extractor(samples, waveform_scale), sample_rate)
            for samples, sample_rate in augment_enrollment_audio(
                clean_enrollment_audio,
                enrollment_noise_pool,
                enroll_noise_snr_db,
            )
        ]
        target_embedding = enroll(extractor, enrollment_audio)
        probes: list[tuple[int, Utterance]] = [
            (1, row) for row in probe_by_speaker[target_speaker]
        ]
        for offset in range(1, negatives_per_target + 1):
            other_speaker = speakers[(index + offset) % len(speakers)]
            probes.append((0, probe_by_speaker[other_speaker][0]))
        for probe_index, (label, probe) in enumerate(probes):
            samples, _ = load_audio_mono16k(probe.audio_path)
            noise_info: NoiseSample | None = None
            if snr_db is not None:
                if not noise_pool:
                    raise ValueError("snr_db requires a non-empty noise_pool")
                noise_info, noise_audio = noise_pool[
                    (index * len(probes) + probe_index) % len(noise_pool)
                ]
                samples = mix_at_snr(samples, noise_audio, snr_db)
            denoise_started = time.perf_counter()
            if denoiser is not None:
                samples, denoised_sample_rate = denoise_audio(denoiser, samples, 16000)
                if denoised_sample_rate != 16000:
                    raise RuntimeError(
                        f"denoiser returned {denoised_sample_rate} Hz; expected 16000 Hz"
                    )
            denoise_elapsed = time.perf_counter() - denoise_started
            started = time.perf_counter()
            score = segment_score(
                extractor,
                target_embedding,
                scale_waveform_for_extractor(samples, waveform_scale),
                16000,
                win_sec=win_sec,
                hop_sec=hop_sec,
                min_seg_sec=min_duration_sec,
                score_aggregation=score_aggregation,
            )
            elapsed = time.perf_counter() - started
            if score is None:
                raise RuntimeError(f"extractor produced no score for {probe.audio_path}")
            asr_started = time.perf_counter()
            asr_text = (
                asr_decode_full_segment(recognizer, samples, 16000)
                if recognizer is not None
                else None
            )
            asr_elapsed = time.perf_counter() - asr_started if recognizer is not None else None
            trials.append(
                {
                    "split": split,
                    "target_speaker": target_speaker,
                    "probe_speaker": probe.speaker,
                    "label": label,
                    "score": score,
                    "probe_recording_id": probe.recording_id,
                    "probe_session_id": probe.session_id,
                    "probe_audio_path": str(probe.audio_path),
                    "probe_duration_sec": probe.duration_sec,
                    "reference_text": probe.text,
                    "enrollment_recording_ids": [row.recording_id for row in enrollment_rows],
                    "enrollment_session_ids": [row.session_id for row in enrollment_rows],
                    "enrollment_audio_paths": [str(row.audio_path) for row in enrollment_rows],
                    "enrollment_noise_snr_db": list(enroll_noise_snr_db),
                    "score_aggregation": score_aggregation,
                    "score_elapsed_sec": elapsed,
                    "denoise_elapsed_sec": denoise_elapsed,
                    "asr_text": asr_text,
                    "asr_elapsed_sec": asr_elapsed,
                    "condition": "clean" if snr_db is None else f"traffic_snr_{snr_db:g}db",
                    "snr_db": snr_db,
                    "noise_cut_id": noise_info.cut_id if noise_info else None,
                    "noise_audio_path": str(noise_info.audio_path) if noise_info else None,
                }
            )
    return trials


def render_report(summary: dict) -> str:
    test = summary["test_at_dev_threshold"]
    lines = [
        f"# {summary['corpus']} 声纹 clean-domain pilot",
        "",
        f"> 这是 {summary['corpus']} clean-domain 诊断，不是交通现场 blind test 或商用结论。",
        "",
        "## 结果",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| dev/test speakers | {summary['config']['dev_speakers']} / {summary['config']['test_speakers']} |",
        f"| enrollment utterances/identity | {summary['config']['enroll_utterances']} |",
        f"| dev diagnostic EER | {summary['dev_diagnostic_eer']['eer_approx']:.2%} |",
        f"| frozen threshold | {summary['dev_threshold']['threshold']:.6f} ({summary['dev_threshold']['source']}) |",
        f"| test FAR | {test['far']:.2%} ({test['false_accepts']}/{test['negative_trials']}) |",
        f"| test FAR Wilson 95% CI | {test['far_wilson_95'][0]:.2%}–{test['far_wilson_95'][1]:.2%} |",
        f"| test FRR | {test['frr']:.2%} ({test['false_rejects']}/{test['positive_trials']}) |",
        f"| test FRR Wilson 95% CI | {test['frr_wilson_95'][0]:.2%}–{test['frr_wilson_95'][1]:.2%} |",
        f"| test diagnostic EER | {summary['test_diagnostic_eer']['eer_approx']:.2%} |",
        "",
        "## 证据边界",
        "",
        "- dev/test speaker 完全隔离，enrollment/probe 使用不同 recording。",
        (
            "- session 从 recording_id 正则提取，enrollment/probe 强制不相交；"
            "它仍不等同于已验证的录制日期、设备或现场 session。"
            if summary["config"].get("session_id_regex")
            else f"- {summary['corpus']} manifest 没有跨日/session 字段，不能证明跨 session 泛化。"
        ),
        "- 交通噪声仅为合成加性压力，不代表真实设备、距离、混响、AGC 或风噪链路。",
        "- 尚未覆盖重叠讲话、跨设备或攻击样本。",
        f"- test 使用冻结 threshold，来源为 {summary['dev_threshold']['source']}。",
        "",
    ]
    if summary.get("test_noise_at_dev_threshold"):
        lines.extend([
            "## 交通噪声压力结果",
            "",
            "| 条件 | FAR | FRR |",
            "| --- | --- | --- |",
        ])
        for condition, row in summary["test_noise_at_dev_threshold"].items():
            lines.append(f"| {condition} | {row['far']:.2%} | {row['frr']:.2%} |")
        lines.append("")
    if summary.get("asr_metrics_by_condition"):
        lines.extend([
            "## 端到端 ASR 过滤",
            "",
            "| 条件 | baseline target CER | gated target CER | 接受的非目标文本字符 |",
            "| --- | --- | --- | --- |",
        ])
        for condition, row in summary["asr_metrics_by_condition"].items():
            lines.append(
                f"| {condition} | {row['baseline_target_cer']:.2%} | "
                f"{row['gated_target_cer']:.2%} | "
                f"{row['accepted_non_target_hypothesis_characters']} |"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cuts", type=Path, nargs="+", required=True)
    parser.add_argument("--speaker-model", type=Path, required=True)
    parser.add_argument(
        "--denoiser-model",
        type=Path,
        help="optional 16 kHz DPDFNet ONNX; applied to enrollment and every probe",
    )
    parser.add_argument("--denoiser-threads", type=int, default=1)
    parser.add_argument(
        "--denoiser-scope",
        choices=("all", "probe"),
        default="all",
        help=(
            "apply denoising to enrollment and probes (all), or preserve clean enrollment "
            "and denoise probes only (probe)"
        ),
    )
    parser.add_argument("--asr-model-dir", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dev-speakers", type=int, default=10)
    parser.add_argument("--test-speakers", type=int, default=10)
    parser.add_argument("--enroll-utterances", type=int, default=3)
    parser.add_argument(
        "--probe-start",
        type=int,
        help="fixed utterance index for probes; useful for paired enrollment ablations",
    )
    parser.add_argument("--target-probes", type=int, default=1)
    parser.add_argument("--negatives-per-target", type=int, default=2)
    parser.add_argument("--min-duration-sec", type=float, default=1.5)
    parser.add_argument("--max-duration-sec", type=float, default=10.0)
    parser.add_argument("--win-sec", type=float, default=2.5)
    parser.add_argument("--hop-sec", type=float, default=1.0)
    parser.add_argument(
        "--score-aggregation",
        choices=("max", "mean", "median", "whole"),
        default="max",
        help="aggregate long-probe window scores; max preserves the current behavior",
    )
    parser.add_argument("--num-threads", type=int, default=1)
    parser.add_argument(
        "--waveform-scale",
        type=float,
        default=1.0,
        help=(
            "scale PCM only before speaker extraction; use 32768 for models whose "
            "metadata says normalize_samples=0"
        ),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-cuts", type=Path)
    parser.add_argument("--snr-db", type=float, nargs="+", default=[20.0, 10.0, 5.0, 0.0])
    parser.add_argument(
        "--enroll-noise-snr-db",
        type=float,
        nargs="*",
        default=[],
        help="append traffic-noised enrollment copies at these SNRs; requires --noise-cuts",
    )
    parser.add_argument(
        "--scan-all",
        action="store_true",
        help="scan every input row before seeded speaker sampling to avoid prefix bias",
    )
    parser.add_argument(
        "--fixed-threshold",
        type=float,
        help="use an externally frozen threshold instead of selecting one on this dev split",
    )
    parser.add_argument(
        "--session-id-regex",
        help=(
            "extract session from recording_id using named group 'session' or the first group; "
            "enrollment and probes are then forced to different sessions"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    probe_start = args.probe_start if args.probe_start is not None else args.enroll_utterances
    if probe_start < args.enroll_utterances:
        raise ValueError("probe-start must not overlap enrollment utterances")
    required_utterances = probe_start + args.target_probes
    required_speakers = args.dev_speakers + args.test_speakers
    if args.negatives_per_target >= min(args.dev_speakers, args.test_speakers):
        raise ValueError("negatives-per-target must be smaller than each split's speaker count")
    speakers, scan = collect_speakers(
        args.cuts,
        required_utterances=required_utterances,
        required_speakers=required_speakers,
        min_duration_sec=args.min_duration_sec,
        max_duration_sec=args.max_duration_sec,
        stop_when_ready=not args.scan_all,
        session_id_regex=args.session_id_regex,
        enroll_utterances=args.enroll_utterances,
        probe_start=probe_start,
        target_probes=args.target_probes,
    )
    if len(speakers) < required_speakers:
        raise RuntimeError(f"found {len(speakers)} eligible speakers; require {required_speakers}")
    speaker_ids = sorted(speakers)
    random.Random(args.seed).shuffle(speaker_ids)
    speaker_ids = speaker_ids[:required_speakers]
    dev_ids = speaker_ids[: args.dev_speakers]
    test_ids = speaker_ids[args.dev_speakers :]

    extractor = build_speaker(args.speaker_model, num_threads=args.num_threads)
    denoiser = (
        build_denoiser(args.denoiser_model, num_threads=args.denoiser_threads)
        if args.denoiser_model
        else None
    )
    recognizer = build_recognizer(args.asr_model_dir) if args.asr_model_dir else None
    noise_pool: list[tuple[NoiseSample, np.ndarray]] = []
    enrollment_noise_pool: list[tuple[NoiseSample, np.ndarray]] = []
    if args.noise_cuts:
        noise_limit = 32 if args.enroll_noise_snr_db else 16
        for noise_sample in collect_noise_samples(args.noise_cuts, limit=noise_limit):
            noise_audio, _ = load_audio_mono16k(noise_sample.audio_path)
            noise_pool.append((noise_sample, noise_audio))
    if args.enroll_noise_snr_db:
        if len(noise_pool) < 2:
            raise ValueError("enrollment augmentation needs at least two readable noise cuts")
        split_at = len(noise_pool) // 2
        enrollment_noise_pool = noise_pool[split_at:]
        noise_pool = noise_pool[:split_at]
    started = time.perf_counter()
    dev_trials = run_split(
        extractor, "dev", dev_ids, speakers,
        enroll_utterances=args.enroll_utterances,
        probe_start=probe_start,
        target_probes=args.target_probes,
        negatives_per_target=args.negatives_per_target,
        win_sec=args.win_sec, hop_sec=args.hop_sec,
        min_duration_sec=args.min_duration_sec,
        waveform_scale=args.waveform_scale,
        score_aggregation=args.score_aggregation,
        enrollment_noise_pool=enrollment_noise_pool,
        enroll_noise_snr_db=args.enroll_noise_snr_db,
        denoiser=denoiser,
        denoise_enrollment=args.denoiser_scope == "all",
    )
    test_trials = run_split(
        extractor, "test", test_ids, speakers,
        enroll_utterances=args.enroll_utterances,
        probe_start=probe_start,
        target_probes=args.target_probes,
        negatives_per_target=args.negatives_per_target,
        win_sec=args.win_sec, hop_sec=args.hop_sec,
        min_duration_sec=args.min_duration_sec,
        waveform_scale=args.waveform_scale,
        score_aggregation=args.score_aggregation,
        enrollment_noise_pool=enrollment_noise_pool,
        enroll_noise_snr_db=args.enroll_noise_snr_db,
        denoiser=denoiser,
        denoise_enrollment=args.denoiser_scope == "all",
        recognizer=recognizer,
    )
    noisy_test_trials: list[dict] = []
    for snr_db in (args.snr_db if noise_pool else []):
        noisy_test_trials.extend(run_split(
            extractor, "test", test_ids, speakers,
            enroll_utterances=args.enroll_utterances,
            probe_start=probe_start,
            target_probes=args.target_probes,
            negatives_per_target=args.negatives_per_target,
            win_sec=args.win_sec, hop_sec=args.hop_sec,
            min_duration_sec=args.min_duration_sec,
            waveform_scale=args.waveform_scale,
            score_aggregation=args.score_aggregation,
            enrollment_noise_pool=enrollment_noise_pool,
            enroll_noise_snr_db=args.enroll_noise_snr_db,
            noise_pool=noise_pool,
            snr_db=snr_db,
            denoiser=denoiser,
            denoise_enrollment=args.denoiser_scope == "all",
            recognizer=recognizer,
        ))
    elapsed = time.perf_counter() - started

    dev_scores = [row["score"] for row in dev_trials]
    dev_labels = [row["label"] for row in dev_trials]
    test_scores = [row["score"] for row in test_trials]
    test_labels = [row["label"] for row in test_trials]
    dev_threshold, dev_diagnostic_eer = choose_operating_threshold(
        dev_scores, dev_labels, args.fixed_threshold
    )
    test_at_dev_threshold = binary_metrics(
        test_scores, test_labels, dev_threshold["threshold"]
    )
    summary = {
        "study": f"{args.cuts[0].parent.name}-clean-domain-voiceprint-pilot",
        "corpus": args.cuts[0].parent.name,
        "status": "diagnostic_only",
        "config": {
            "dev_speakers": args.dev_speakers,
            "test_speakers": args.test_speakers,
            "enroll_utterances": args.enroll_utterances,
            "probe_start": probe_start,
            "target_probes": args.target_probes,
            "negatives_per_target": args.negatives_per_target,
            "min_duration_sec": args.min_duration_sec,
            "max_duration_sec": args.max_duration_sec,
            "win_sec": args.win_sec,
            "hop_sec": args.hop_sec,
            "score_aggregation": args.score_aggregation,
            "enroll_noise_snr_db": args.enroll_noise_snr_db,
            "denoiser_model": str(args.denoiser_model) if args.denoiser_model else None,
            "denoiser_threads": args.denoiser_threads if args.denoiser_model else None,
            "denoiser_scope": args.denoiser_scope if args.denoiser_model else None,
            "snr_db": args.snr_db if args.noise_cuts else [],
            "seed": args.seed,
            "speaker_sampling": "full_manifest_seeded" if args.scan_all else "eligible_prefix_seeded",
            "fixed_threshold": args.fixed_threshold,
            "waveform_scale": args.waveform_scale,
            "session_id_regex": args.session_id_regex,
            "session_policy": "enrollment_probe_disjoint" if args.session_id_regex else None,
        },
        "artifacts": {
            "speaker_model": str(args.speaker_model),
            "speaker_model_sha256": sha256(args.speaker_model),
            "denoiser_model": str(args.denoiser_model) if args.denoiser_model else None,
            "denoiser_model_sha256": (
                sha256(args.denoiser_model) if args.denoiser_model else None
            ),
            "cut_manifests": [str(path) for path in args.cuts],
            "cut_manifest_sha256": {str(path): sha256(path) for path in args.cuts},
            "noise_cuts": str(args.noise_cuts) if args.noise_cuts else None,
            "noise_cuts_sha256": sha256(args.noise_cuts) if args.noise_cuts else None,
            "asr_model_dir": str(args.asr_model_dir) if args.asr_model_dir else None,
            "asr_model_sha256": (
                {
                    path.name: sha256(path)
                    for path in sorted(args.asr_model_dir.iterdir())
                    if path.is_file()
                }
                if args.asr_model_dir
                else None
            ),
        },
        "scan": scan,
        "dev_speaker_ids": dev_ids,
        "test_speaker_ids": test_ids,
        "dev_threshold": dev_threshold,
        "dev_diagnostic_eer": dev_diagnostic_eer,
        "test_at_dev_threshold": test_at_dev_threshold,
        "test_diagnostic_eer": select_eer_threshold(test_scores, test_labels),
        "confidence_sanity": {
            "method": "rule_of_three_for_zero_errors_only",
            "far_rule_of_three_upper": (
                3.0 / test_at_dev_threshold["negative_trials"]
                if test_at_dev_threshold["false_accepts"] == 0
                else None
            ),
            "frr_rule_of_three_upper": (
                3.0 / test_at_dev_threshold["positive_trials"]
                if test_at_dev_threshold["false_rejects"] == 0
                else None
            ),
        },
        "test_noise_at_dev_threshold": {},
        "test_noise_diagnostic_eer": {},
        "asr_metrics_by_condition": {},
        "score_distribution": {
            "dev_target": describe([row["score"] for row in dev_trials if row["label"] == 1]),
            "dev_non_target": describe([row["score"] for row in dev_trials if row["label"] == 0]),
            "test_target": describe([row["score"] for row in test_trials if row["label"] == 1]),
            "test_non_target": describe([row["score"] for row in test_trials if row["label"] == 0]),
        },
        "runtime": {
            "total_sec": elapsed,
            "trials": len(dev_trials) + len(test_trials) + len(noisy_test_trials),
            "mean_score_sec": statistics.fmean(row["score_elapsed_sec"] for row in dev_trials + test_trials + noisy_test_trials),
            "mean_denoise_sec": statistics.fmean(
                row["denoise_elapsed_sec"]
                for row in dev_trials + test_trials + noisy_test_trials
            ),
        },
        "limitations": [
            f"{args.cuts[0].parent.name} clean speech with optional synthetic additive road noise",
            (
                "session proxy extracted from recording_id; no verified date/device metadata"
                if args.session_id_regex
                else "no independent session/date metadata"
            ),
            "synthetic noise is not a real traffic capture chain",
            "no overlap, device shift, or spoof attacks",
            (
                "full manifests scanned before seeded speaker sampling"
                if args.scan_all
                else "pilot selects the first eligible speakers encountered before seeded dev/test split"
            ),
        ],
    }
    if recognizer is not None:
        summary["asr_metrics_by_condition"]["clean"] = asr_metrics(
            test_trials, dev_threshold["threshold"]
        )
    for condition in sorted({row["condition"] for row in noisy_test_trials}):
        rows = [row for row in noisy_test_trials if row["condition"] == condition]
        scores = [row["score"] for row in rows]
        labels = [row["label"] for row in rows]
        summary["test_noise_at_dev_threshold"][condition] = binary_metrics(
            scores, labels, dev_threshold["threshold"]
        )
        summary["test_noise_diagnostic_eer"][condition] = select_eer_threshold(scores, labels)
        if recognizer is not None:
            summary["asr_metrics_by_condition"][condition] = asr_metrics(
                rows, dev_threshold["threshold"]
            )
        summary["score_distribution"][f"{condition}_target"] = describe(
            [row["score"] for row in rows if row["label"] == 1]
        )
        summary["score_distribution"][f"{condition}_non_target"] = describe(
            [row["score"] for row in rows if row["label"] == 0]
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "trials.jsonl").open("w", encoding="utf-8") as handle:
        for row in dev_trials + test_trials + noisy_test_trials:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
