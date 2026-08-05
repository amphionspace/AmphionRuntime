#!/usr/bin/env python3
"""Estimate voiceprint threshold-selection variance with speaker-cluster bootstrap."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "voiceprint_pilot_for_bootstrap", SCRIPT_DIR / "07_eval_voiceprint_verification.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load voiceprint pilot helpers")
pilot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pilot
SPEC.loader.exec_module(pilot)


def percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot summarize empty values")
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def distribution(values: Sequence[float]) -> dict:
    return {
        "min": min(values),
        "p05": percentile(values, 0.05),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def bootstrap_thresholds(
    dev_rows: Sequence[dict],
    test_rows: Sequence[dict],
    *,
    iterations: int,
    seed: int,
    far_limit: float,
) -> dict:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    by_speaker: dict[str, list[dict]] = {}
    for row in dev_rows:
        by_speaker.setdefault(str(row["target_speaker"]), []).append(row)
    speakers = sorted(by_speaker)
    if len(speakers) < 2:
        raise ValueError("speaker-cluster bootstrap requires at least two dev speakers")
    test_scores = [float(row["score"]) for row in test_rows]
    test_labels = [int(row["label"]) for row in test_rows]
    rng = random.Random(seed)
    thresholds: list[float] = []
    test_fars: list[float] = []
    test_frrs: list[float] = []
    for _ in range(iterations):
        sampled = [rng.choice(speakers) for _ in speakers]
        rows = [row for speaker in sampled for row in by_speaker[speaker]]
        selected = pilot.select_eer_threshold(
            [float(row["score"]) for row in rows],
            [int(row["label"]) for row in rows],
        )
        metrics = pilot.binary_metrics(test_scores, test_labels, selected["threshold"])
        thresholds.append(float(selected["threshold"]))
        test_fars.append(float(metrics["far"]))
        test_frrs.append(float(metrics["frr"]))
    return {
        "dev_speaker_clusters": len(speakers),
        "iterations": iterations,
        "seed": seed,
        "threshold": distribution(thresholds),
        "test_far": distribution(test_fars),
        "test_frr": distribution(test_frrs),
        "probability_test_far_exceeds_limit": sum(value > far_limit for value in test_fars)
        / iterations,
        "far_limit": far_limit,
    }


def render_report(summary: dict) -> str:
    bootstrap = summary["bootstrap"]
    return "\n".join([
        "# 声纹阈值 speaker-cluster bootstrap",
        "",
        "> 这是 calibration sampling variance 诊断，不是新 blind，也不为产品选择阈值。",
        "",
        f"- Dev speaker clusters：{bootstrap['dev_speaker_clusters']}",
        f"- Iterations：{bootstrap['iterations']}",
        f"- 原始 dev threshold：`{summary['original_dev_threshold']:.6f}`",
        f"- Bootstrap threshold p05/p50/p95：`{bootstrap['threshold']['p05']:.6f}` / "
        f"`{bootstrap['threshold']['p50']:.6f}` / `{bootstrap['threshold']['p95']:.6f}`",
        f"- Test FAR p05/p50/p95：{bootstrap['test_far']['p05']:.2%} / "
        f"{bootstrap['test_far']['p50']:.2%} / {bootstrap['test_far']['p95']:.2%}",
        f"- Test FRR p05/p50/p95：{bootstrap['test_frr']['p05']:.2%} / "
        f"{bootstrap['test_frr']['p50']:.2%} / {bootstrap['test_frr']['p95']:.2%}",
        f"- P(Test FAR > {bootstrap['far_limit']:.2%})："
        f"{bootstrap['probability_test_far_exceeds_limit']:.2%}",
        "",
        "Bootstrap 按 target/enrollment speaker 整簇重采样，保留同一 identity 内 target/non-target trial 依赖。",
        "",
    ])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--far-limit", type=float, default=0.05)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = [json.loads(line) for line in args.trials.read_text(encoding="utf-8").splitlines()]
    dev_rows = [row for row in rows if row["split"] == "dev" and row["condition"] == "clean"]
    test_rows = [row for row in rows if row["split"] == "test" and row["condition"] == "clean"]
    original = pilot.select_eer_threshold(
        [float(row["score"]) for row in dev_rows],
        [int(row["label"]) for row in dev_rows],
    )
    summary = {
        "status": "development_only",
        "trials": str(args.trials),
        "trials_sha256": pilot.sha256(args.trials),
        "original_dev_threshold": original["threshold"],
        "bootstrap": bootstrap_thresholds(
            dev_rows,
            test_rows,
            iterations=args.iterations,
            seed=args.seed,
            far_limit=args.far_limit,
        ),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
