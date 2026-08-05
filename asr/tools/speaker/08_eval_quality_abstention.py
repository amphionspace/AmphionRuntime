#!/usr/bin/env python3
"""Train and evaluate a CPU-only quality-aware voiceprint abstention ranker.

The ranker never changes the public speaker similarity or its frozen threshold.
It predicts whether the frozen decision is at risk and may return abstain.  Input
features are available from the scored waveform and score; condition/SNR labels
are used only for reporting and never enter the model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ts_asr import load_audio_mono16k  # noqa: E402


PILOT_SPEC = importlib.util.spec_from_file_location(
    "voiceprint_pilot_for_quality", SCRIPT_DIR / "07_eval_voiceprint_verification.py"
)
if PILOT_SPEC is None or PILOT_SPEC.loader is None:
    raise RuntimeError("cannot load voiceprint pilot helpers")
pilot = importlib.util.module_from_spec(PILOT_SPEC)
sys.modules[PILOT_SPEC.name] = pilot
PILOT_SPEC.loader.exec_module(pilot)


SCORE_FEATURES = ("score", "abs_score_margin")
QUALITY_FEATURES = SCORE_FEATURES + (
    "duration_sec",
    "rms_dbfs",
    "crest_db",
    "frame_rms_dynamic_db",
    "active_frame_ratio",
    "zero_crossing_rate",
    "spectral_flatness",
    "clipping_ratio",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_trials(path: Path, split: str) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    selected = [row for row in rows if row.get("split") == split]
    if not selected:
        raise ValueError(f"no rows with split={split!r} in {path}")
    return selected


def _frames(samples: np.ndarray, frame_size: int = 400, hop_size: int = 160) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float64)
    if len(samples) < frame_size:
        samples = np.pad(samples, (0, frame_size - len(samples)))
    count = 1 + (len(samples) - frame_size) // hop_size
    starts = np.arange(count)[:, None] * hop_size
    offsets = np.arange(frame_size)[None, :]
    return samples[starts + offsets]


def audio_quality_features(samples: np.ndarray, sample_rate: int = 16000) -> dict[str, float]:
    """Return cheap, inference-time waveform features without using SNR labels."""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not len(samples):
        raise ValueError("samples must be a non-empty mono waveform")
    eps = 1e-12
    frames = _frames(samples)
    frame_rms = np.sqrt(np.mean(np.square(frames), axis=1) + eps)
    frame_db = 20.0 * np.log10(frame_rms + eps)
    rms = float(np.sqrt(np.mean(np.square(samples)) + eps))
    peak = float(np.max(np.abs(samples)))
    active_floor = max(float(np.percentile(frame_db, 90.0)) - 30.0, -50.0)

    windowed = frames * np.hanning(frames.shape[1])[None, :]
    power = np.square(np.abs(np.fft.rfft(windowed, axis=1))) + eps
    flatness = np.exp(np.mean(np.log(power), axis=1)) / np.mean(power, axis=1)
    signs = np.signbit(samples)
    return {
        "duration_sec": len(samples) / float(sample_rate),
        "rms_dbfs": 20.0 * math.log10(rms + eps),
        "crest_db": 20.0 * math.log10((peak + eps) / (rms + eps)),
        "frame_rms_dynamic_db": float(np.percentile(frame_db, 90.0) - np.percentile(frame_db, 10.0)),
        "active_frame_ratio": float(np.mean(frame_db >= active_floor)),
        "zero_crossing_rate": float(np.mean(signs[1:] != signs[:-1])) if len(samples) > 1 else 0.0,
        "spectral_flatness": float(np.median(flatness)),
        "clipping_ratio": float(np.mean(np.abs(samples) >= 0.98)),
    }


def waveform_features_for_row(
    row: dict,
    cache: dict[tuple[str, str | None, float | None], dict[str, float]],
) -> dict[str, float]:
    key = (
        str(row["probe_audio_path"]),
        str(row["noise_audio_path"]) if row.get("noise_audio_path") else None,
        float(row["snr_db"]) if row.get("snr_db") is not None else None,
    )
    if key not in cache:
        samples, _source_sample_rate = load_audio_mono16k(Path(key[0]))
        if key[2] is not None:
            if key[1] is None:
                raise ValueError("noisy row is missing noise_audio_path")
            noise, _noise_source_sample_rate = load_audio_mono16k(Path(key[1]))
            samples = pilot.mix_at_snr(samples, noise, key[2])
        # load_audio_mono16k returns the source rate for provenance, while its
        # waveform is always resampled to the 16 kHz runtime contract.
        cache[key] = audio_quality_features(samples, 16000)
    return cache[key]


def feature_matrix(
    rows: Sequence[dict],
    speaker_threshold: float,
    feature_names: Sequence[str],
    cache: dict[tuple[str, str | None, float | None], dict[str, float]] | None = None,
) -> np.ndarray:
    cache = {} if cache is None else cache
    vectors = []
    for row in rows:
        score = float(row["score"])
        values = {
            "score": score,
            "abs_score_margin": abs(score - speaker_threshold),
            **waveform_features_for_row(row, cache),
        }
        vectors.append([values[name] for name in feature_names])
    matrix = np.asarray(vectors, dtype=np.float64)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("non-finite quality feature")
    return matrix


def decision_error_labels(rows: Sequence[dict], speaker_threshold: float) -> np.ndarray:
    return np.asarray(
        [int((float(row["score"]) >= speaker_threshold) != bool(row["label"])) for row in rows],
        dtype=np.float64,
    )


def fit_error_ranker(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    l2: float = 1e-2,
    max_iterations: int = 100,
) -> dict:
    """Fit balanced, L2-regularized logistic regression with Newton updates."""
    matrix = np.asarray(matrix, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    if matrix.ndim != 2 or labels.shape != (matrix.shape[0],):
        raise ValueError("matrix/label shape mismatch")
    positives = int(np.sum(labels == 1.0))
    negatives = int(np.sum(labels == 0.0))
    if not positives or not negatives:
        raise ValueError("ranker training requires both error and correct decisions")
    mean = np.mean(matrix, axis=0)
    scale = np.std(matrix, axis=0)
    scale[scale < 1e-8] = 1.0
    standardized = (matrix - mean) / scale
    design = np.column_stack([np.ones(len(matrix)), standardized])
    sample_weight = np.where(labels == 1.0, 0.5 / positives, 0.5 / negatives)
    weights = np.zeros(design.shape[1], dtype=np.float64)
    penalty = np.eye(design.shape[1], dtype=np.float64) * l2
    penalty[0, 0] = 0.0
    for _ in range(max_iterations):
        logits = np.clip(design @ weights, -35.0, 35.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        gradient = design.T @ (sample_weight * (probabilities - labels)) + penalty @ weights
        curvature = sample_weight * probabilities * (1.0 - probabilities)
        hessian = design.T @ (design * curvature[:, None]) + penalty
        step = np.linalg.solve(hessian + np.eye(len(weights)) * 1e-10, gradient)
        weights -= step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return {
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": weights.tolist(),
        "training_errors": positives,
        "training_correct": negatives,
        "l2": l2,
    }


def predict_error_risk(model: dict, matrix: np.ndarray) -> np.ndarray:
    mean = np.asarray(model["mean"], dtype=np.float64)
    scale = np.asarray(model["scale"], dtype=np.float64)
    weights = np.asarray(model["weights"], dtype=np.float64)
    standardized = (np.asarray(matrix, dtype=np.float64) - mean) / scale
    design = np.column_stack([np.ones(len(standardized)), standardized])
    logits = np.clip(design @ weights, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-logits))


def select_abstain_threshold(risks: Sequence[float], budget: float) -> float:
    """Select the lowest risk threshold whose tied group stays within budget."""
    if not 0.0 <= budget < 1.0:
        raise ValueError("abstain budget must be in [0, 1)")
    risks = np.asarray(risks, dtype=np.float64)
    allowed = math.floor(len(risks) * budget + 1e-12)
    if allowed == 0:
        return math.nextafter(float(np.max(risks)), math.inf)
    selected = 0
    threshold = math.inf
    for risk in sorted(set(float(value) for value in risks), reverse=True):
        group = int(np.sum(risks == risk))
        if selected + group > allowed:
            break
        selected += group
        threshold = risk
    return threshold


def ranking_metrics(risks: Sequence[float], error_labels: Sequence[float]) -> dict:
    """Measure error-ranking discrimination without selecting a policy threshold."""
    risks = np.asarray(risks, dtype=np.float64)
    labels = np.asarray(error_labels, dtype=np.float64)
    positives = risks[labels == 1.0]
    negatives = risks[labels == 0.0]
    if not len(positives) or not len(negatives):
        raise ValueError("ranking metrics require error and correct decisions")
    comparisons = positives[:, None] - negatives[None, :]
    auc = float(np.mean(comparisons > 0.0) + 0.5 * np.mean(comparisons == 0.0))
    order = np.argsort(-risks, kind="stable")
    ordered_labels = labels[order]
    cumulative = np.cumsum(ordered_labels)
    positive_ranks = np.flatnonzero(ordered_labels == 1.0)
    average_precision = float(
        np.mean(cumulative[positive_ranks] / (positive_ranks.astype(np.float64) + 1.0))
    )
    return {
        "errors": len(positives),
        "correct": len(negatives),
        "error_prevalence": float(len(positives) / len(risks)),
        "roc_auc": auc,
        "average_precision": average_precision,
    }


def _policy_metrics(
    rows: Sequence[dict],
    risks: np.ndarray,
    risk_threshold: float,
    speaker_threshold: float,
) -> dict:
    abstain = risks >= risk_threshold
    labels = np.asarray([int(row["label"]) for row in rows])
    decisions = np.asarray([float(row["score"]) >= speaker_threshold for row in rows])
    baseline_errors = decisions != labels.astype(bool)
    decided = ~abstain
    positive = labels == 1
    negative = ~positive
    false_accept = decided & negative & decisions
    false_reject = decided & positive & ~decisions
    decided_positive = int(np.sum(decided & positive))
    decided_negative = int(np.sum(decided & negative))
    return {
        "trials": len(rows),
        "coverage": float(np.mean(decided)),
        "target_coverage": float(np.mean(decided[positive])) if np.any(positive) else None,
        "non_target_coverage": float(np.mean(decided[negative])) if np.any(negative) else None,
        "abstained": int(np.sum(abstain)),
        "baseline_errors": int(np.sum(baseline_errors)),
        "errors_abstained": int(np.sum(abstain & baseline_errors)),
        "error_capture_rate": (
            float(np.sum(abstain & baseline_errors) / np.sum(baseline_errors))
            if np.any(baseline_errors)
            else None
        ),
        "conditional_far": float(np.sum(false_accept) / decided_negative) if decided_negative else None,
        "conditional_frr": float(np.sum(false_reject) / decided_positive) if decided_positive else None,
        "population_far": float(np.sum(false_accept) / np.sum(negative)) if np.any(negative) else None,
        "population_frr": float(np.sum(false_reject) / np.sum(positive)) if np.any(positive) else None,
    }


def evaluate_policy(
    rows: Sequence[dict],
    risks: np.ndarray,
    risk_threshold: float,
    speaker_threshold: float,
) -> dict:
    result = {
        "all": _policy_metrics(rows, risks, risk_threshold, speaker_threshold),
        "by_condition": {},
    }
    for condition in sorted({str(row["condition"]) for row in rows}):
        indices = np.asarray([row["condition"] == condition for row in rows])
        result["by_condition"][condition] = _policy_metrics(
            [row for row, keep in zip(rows, indices) if keep],
            risks[indices],
            risk_threshold,
            speaker_threshold,
        )
    return result


def render_report(summary: dict) -> str:
    lines = [
        "# 声纹质量感知 abstention T0 实验",
        "",
        "> CPU-only development experiment。模型不修改 speakerSimilarity 或冻结声纹阈值；KeSpeech 已被历史实验观察过，因此仅是 external diagnostic，不是 blind test。",
        "",
        f"冻结声纹阈值：`{summary['speaker_threshold']:.10f}`",
        "",
        "| ranker | external error AP/AUC | AISHELL abstain budget | AISHELL coverage/error capture | KeSpeech coverage/error capture | KeSpeech 0 dB conditional FAR/FRR |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, model in summary["rankers"].items():
        for budget, policy in model["policies"].items():
            train = policy["train"]["all"]
            external = policy["external"]["all"]
            noise = policy["external"]["by_condition"].get("traffic_snr_0db", {})
            ranking = model["external_ranking"]
            lines.append(
                f"| {name} | {ranking['average_precision']:.3f}/{ranking['roc_auc']:.3f} | "
                f"{float(budget):.0%} | {train['coverage']:.2%}/{train['error_capture_rate']:.2%} | "
                f"{external['coverage']:.2%}/{external['error_capture_rate']:.2%} | "
                f"{noise.get('conditional_far', 0.0):.2%}/{noise.get('conditional_frr', 0.0):.2%} |"
            )
    lines.extend([
        "",
        "## 解释约束",
        "",
        "- condition 和 SNR 只用于分桶报告，不是模型输入。",
        "- conditional FAR/FRR 只统计已决定样本，必须与 coverage、target/non-target coverage 一起读取。",
        "- 该实验用于决定质量特征是否值得带入真实设备 pilot，不能选择商用 abstain 成本或阈值。",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-trials", type=Path, required=True)
    parser.add_argument("--external-trials", type=Path, required=True)
    parser.add_argument("--speaker-threshold", type=float, required=True)
    parser.add_argument("--train-split", default="test")
    parser.add_argument("--external-split", default="test")
    parser.add_argument("--abstain-budgets", type=float, nargs="+", default=[0.05, 0.10, 0.20])
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    train_rows = read_trials(args.train_trials, args.train_split)
    external_rows = read_trials(args.external_trials, args.external_split)
    train_cache: dict[tuple[str, str | None, float | None], dict[str, float]] = {}
    external_cache: dict[tuple[str, str | None, float | None], dict[str, float]] = {}
    labels = decision_error_labels(train_rows, args.speaker_threshold)
    summary = {
        "status": "development_only",
        "speaker_threshold": args.speaker_threshold,
        "train_trials": str(args.train_trials),
        "train_trials_sha256": sha256(args.train_trials),
        "external_trials": str(args.external_trials),
        "external_trials_sha256": sha256(args.external_trials),
        "input_contract": "score and waveform features only; condition/snr excluded",
        "rankers": {},
    }
    for name, feature_names in (
        ("score_only", SCORE_FEATURES),
        ("score_plus_quality", QUALITY_FEATURES),
    ):
        train_matrix = feature_matrix(
            train_rows, args.speaker_threshold, feature_names, train_cache
        )
        external_matrix = feature_matrix(
            external_rows, args.speaker_threshold, feature_names, external_cache
        )
        model = fit_error_ranker(train_matrix, labels)
        train_risks = predict_error_risk(model, train_matrix)
        external_risks = predict_error_risk(model, external_matrix)
        external_labels = decision_error_labels(external_rows, args.speaker_threshold)
        ranker = {
            "feature_names": list(feature_names),
            "model": model,
            "train_ranking": ranking_metrics(train_risks, labels),
            "external_ranking": ranking_metrics(external_risks, external_labels),
            "policies": {},
        }
        for budget in args.abstain_budgets:
            threshold = select_abstain_threshold(train_risks, budget)
            ranker["policies"][str(budget)] = {
                "risk_threshold": threshold,
                "train": evaluate_policy(
                    train_rows, train_risks, threshold, args.speaker_threshold
                ),
                "external": evaluate_policy(
                    external_rows, external_risks, threshold, args.speaker_threshold
                ),
            }
        summary["rankers"][name] = ranker

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
