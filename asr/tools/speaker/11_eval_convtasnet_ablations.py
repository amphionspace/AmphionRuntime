#!/usr/bin/env python3
"""Separate Conv-TasNet bandwidth loss from two-speaker task matching.

This diagnostic reuses the frozen synthetic voiceprint trial map. It runs two
ablations:

1. Apply only a 16 kHz -> 8 kHz -> 16 kHz round trip before ERes2Net.
2. Create deterministic 0 dB two-speaker mixtures, then compare direct 16 kHz,
   the same 8 kHz round trip, and Conv-TasNet -> ERes2Net.

The second comparison uses max scoring across both separator outputs for target
and non-target trials. It therefore measures whether the separator adds value
after controlling for its mandatory 8 kHz bandwidth, without oracle source
selection.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

FRONTEND_SPEC = importlib.util.spec_from_file_location(
    "convtasnet_frontend_shared", SCRIPT_DIR / "10_eval_convtasnet_frontend.py"
)
assert FRONTEND_SPEC is not None and FRONTEND_SPEC.loader is not None
frontend = importlib.util.module_from_spec(FRONTEND_SPEC)
sys.modules[FRONTEND_SPEC.name] = frontend
FRONTEND_SPEC.loader.exec_module(frontend)

pilot = frontend.pilot
from ts_asr import build_speaker, enroll, load_audio_mono16k  # noqa: E402


TARGET_SAMPLE_RATE = frontend.TARGET_SAMPLE_RATE
CONVTASNET_SAMPLE_RATE = frontend.CONVTASNET_SAMPLE_RATE


def stable_index(parts: Sequence[str], size: int, seed: int) -> int:
    if size <= 0:
        raise ValueError("size must be positive")
    payload = "\0".join([str(seed), *parts]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % size


def bandwidth_round_trip(samples_16k: np.ndarray) -> np.ndarray:
    down = frontend.resample_audio(
        samples_16k, TARGET_SAMPLE_RATE, CONVTASNET_SAMPLE_RATE
    )
    restored = frontend.resample_audio(
        down, CONVTASNET_SAMPLE_RATE, TARGET_SAMPLE_RATE
    )
    if len(restored) < len(samples_16k):
        restored = np.pad(restored, (0, len(samples_16k) - len(restored)))
    return np.ascontiguousarray(restored[: len(samples_16k)], dtype=np.float32)


def build_interferer_pools(clean_rows: Sequence[dict]) -> dict[str, list[dict]]:
    """Use each split's positive probes as a speaker-disjoint interference pool."""
    result: dict[str, list[dict]] = {}
    seen: set[tuple[str, str]] = set()
    for row in clean_rows:
        if int(row["label"]) != 1:
            continue
        key = (str(row["split"]), str(row["probe_speaker"]))
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(key[0], []).append(
            {
                "speaker": key[1],
                "recording_id": str(row["probe_recording_id"]),
                "audio_path": str(row["probe_audio_path"]),
            }
        )
    for pool in result.values():
        pool.sort(key=lambda item: (item["speaker"], item["recording_id"]))
    return result


def select_interferer(row: dict, pool: Sequence[dict], seed: int) -> dict:
    """Select deterministically while preserving the original verification label."""
    excluded = {str(row["target_speaker"]), str(row["probe_speaker"])}
    candidates = [item for item in pool if str(item["speaker"]) not in excluded]
    if not candidates:
        raise RuntimeError("no interferer remains after excluding target and probe speakers")
    index = stable_index(
        [
            str(row["split"]),
            str(row["target_speaker"]),
            str(row["probe_recording_id"]),
        ],
        len(candidates),
        seed,
    )
    return candidates[index]


def select_overlap_rows(clean_rows: Sequence[dict], negatives_per_target: int) -> list[dict]:
    """Keep every positive and a deterministic prefix of negatives per target."""
    if negatives_per_target <= 0:
        raise ValueError("negatives_per_target must be positive")
    grouped: dict[tuple[str, str], dict[int, list[dict]]] = {}
    for row in clean_rows:
        key = (str(row["split"]), str(row["target_speaker"]))
        grouped.setdefault(key, {0: [], 1: []})[int(row["label"])].append(row)
    selected: list[dict] = []
    for key in sorted(grouped):
        labels = grouped[key]
        if len(labels[1]) != 1:
            raise RuntimeError(f"expected one positive clean row for {key}, got {len(labels[1])}")
        negatives = sorted(
            labels[0], key=lambda row: (str(row["probe_speaker"]), str(row["probe_recording_id"]))
        )
        if len(negatives) < negatives_per_target:
            raise RuntimeError(f"not enough negatives for {key}")
        selected.append(labels[1][0])
        selected.extend(negatives[:negatives_per_target])
    return selected


def mix_speakers(primary: np.ndarray, interferer: np.ndarray, sir_db: float) -> np.ndarray:
    """Create a full-duration deterministic speaker mixture at the requested SIR."""
    return pilot.mix_at_snr(primary, interferer, sir_db)


def extract_embeddings(extractor, samples: np.ndarray, config: dict) -> list[np.ndarray]:
    return frontend.extract_window_embeddings(
        extractor,
        samples,
        win_sec=float(config["win_sec"]),
        hop_sec=float(config["hop_sec"]),
        min_duration_sec=float(config["min_duration_sec"]),
    )


def score_embeddings(embeddings: Sequence[np.ndarray], target: np.ndarray) -> float:
    score, _, _ = frontend.score_separated_sources([embeddings], target)
    return score


def metrics_by_condition(rows: Sequence[dict], field: str, threshold: float) -> dict[str, dict]:
    return frontend.metrics_by_condition(rows, field, threshold)


def dev_threshold(rows: Sequence[dict], field: str, *, condition: str | None = None) -> dict:
    selected = [
        row
        for row in rows
        if row["split"] == "dev" and (condition is None or row["condition"] == condition)
    ]
    return pilot.select_eer_threshold(
        [float(row[field]) for row in selected], [int(row["label"]) for row in selected]
    )


def test_eer_by_condition(rows: Sequence[dict], field: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    conditions = sorted({str(row["condition"]) for row in rows if row["split"] == "test"})
    for condition in conditions:
        selected = [
            row for row in rows if row["split"] == "test" and row["condition"] == condition
        ]
        result[condition] = pilot.select_eer_threshold(
            [float(row[field]) for row in selected], [int(row["label"]) for row in selected]
        )
    return result


def paired_shift(rows: Sequence[dict], left: str, right: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    conditions = sorted({str(row["condition"]) for row in rows if row["split"] == "test"})
    for condition in conditions:
        selected = [
            row for row in rows if row["split"] == "test" and row["condition"] == condition
        ]
        result[condition] = {}
        for label, name in ((1, "target"), (0, "non_target")):
            labeled = [row for row in selected if int(row["label"]) == label]
            result[condition][name] = pilot.describe(
                [float(row[right]) - float(row[left]) for row in labeled]
            )
    return result


def index_existing_convtasnet(rows: Sequence[dict]) -> dict[tuple, dict]:
    return {
        (
            str(row["split"]),
            str(row["target_speaker"]),
            str(row["probe_recording_id"]),
            str(row["condition"]),
        ): row
        for row in rows
    }


def trial_key(row: dict) -> tuple:
    return (
        str(row["split"]),
        str(row["target_speaker"]),
        str(row["probe_recording_id"]),
        str(row["condition"]),
    )


def verify_existing_baseline_linkage(
    existing_summary: dict, baseline_summary_path: Path, baseline_trials_path: Path
) -> None:
    artifacts = existing_summary.get("artifacts") or {}
    expected = {
        "baseline_summary_sha256": frontend.sha256(baseline_summary_path),
        "baseline_trials_sha256": frontend.sha256(baseline_trials_path),
    }
    for field, actual_hash in expected.items():
        recorded_hash = artifacts.get(field)
        if recorded_hash != actual_hash:
            raise RuntimeError(
                f"existing Conv-TasNet result is linked to a different baseline: "
                f"{field}={recorded_hash!r}, expected {actual_hash}"
            )


def render_report(summary: dict) -> str:
    bandwidth = summary["bandwidth_ablation"]
    overlap = summary["two_speaker_overlap"]
    conditions = ["clean", "traffic_snr_5db", "traffic_snr_0db"]

    def cell(metrics: dict, condition: str) -> str:
        row = metrics[condition]
        return f"{row['far']:.2%} / {row['frr']:.2%}"

    overlap_metrics = overlap["test_at_own_dev_threshold"]
    overlap_eer = overlap["test_diagnostic_eer"]
    overlap_condition = next(iter(overlap_metrics["direct_score"]))
    lines = [
        "# Conv-TasNet 退化来源消融实验",
        "",
        "## 单人语音：8 kHz 带宽损失",
        "",
        "| 方法 | dev 阈值 | clean FAR/FRR | 5 dB FAR/FRR | 0 dB FAR/FRR |",
        "| --- | ---: | ---: | ---: | ---: |",
        (
            f"| 原始 16 kHz ERes2Net | {summary['baseline_threshold']:.6f} | "
            + " | ".join(cell(bandwidth["baseline_at_baseline_threshold"], c) for c in conditions)
            + " |"
        ),
        (
            f"| 16k→8k→16k ERes2Net | {bandwidth['roundtrip_dev_threshold']['threshold']:.6f} | "
            + " | ".join(cell(bandwidth["roundtrip_at_own_dev_threshold"], c) for c in conditions)
            + " |"
        ),
        (
            f"| Conv-TasNet→ERes2Net | {bandwidth['convtasnet_dev_threshold']['threshold']:.6f} | "
            + " | ".join(cell(bandwidth["convtasnet_at_own_dev_threshold"], c) for c in conditions)
            + " |"
        ),
        "",
        f"## 两人 {summary['config']['sir_db']:g} dB 全时重叠：是否匹配分离任务",
        "",
        "| 方法 | dev 阈值 | test FAR/FRR | test diagnostic EER |",
        "| --- | ---: | ---: | ---: |",
    ]
    for field, label in (
        ("direct_score", "直接 16 kHz ERes2Net"),
        ("roundtrip_score", "16k→8k→16k ERes2Net"),
        ("convtasnet_score", "Conv-TasNet→ERes2Net"),
    ):
        metrics = overlap_metrics[field][overlap_condition]
        eer = overlap_eer[field][overlap_condition]["eer_approx"]
        threshold = overlap["dev_thresholds"][field]["threshold"]
        lines.append(
            f"| {label} | {threshold:.6f} | {metrics['far']:.2%} / {metrics['frr']:.2%} | {eer:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 两人混音只保留每个目标的一条负例，以控制本机实验耗时；它是诊断，不是发布门禁。",
            "- 干扰人来自同一 split 的另一位说话人；负例明确排除 enrolled target，标签不被混音改变。",
            "- Conv-TasNet 两路输出均评分并取最大值，target/non-target 使用同一规则，没有 oracle 选路。",
            "- checkpoint 仍是英文 WHAM sep_clean、8 kHz；中文合成重叠不代表真实设备链路。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--existing-convtasnet-dir", type=Path, required=True)
    parser.add_argument("--conv-tasnet-model", type=Path, required=True)
    parser.add_argument("--speaker-model", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--torch-threads", type=int, default=1)
    parser.add_argument("--speaker-threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--sir-db", type=float, default=0.0)
    parser.add_argument("--negatives-per-target", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frontend.prepare_output_dir(args.out_dir)
    baseline_summary_path = args.baseline_dir / "summary.json"
    baseline_trials_path = args.baseline_dir / "trials.jsonl"
    existing_summary_path = args.existing_convtasnet_dir / "summary.json"
    existing_trials_path = args.existing_convtasnet_dir / "trials.jsonl"
    for path in (
        baseline_summary_path,
        baseline_trials_path,
        existing_summary_path,
        existing_trials_path,
        args.conv_tasnet_model,
    ):
        frontend.verify_artifact(path, None)

    baseline_summary = json.loads(baseline_summary_path.read_text(encoding="utf-8"))
    existing_summary = json.loads(existing_summary_path.read_text(encoding="utf-8"))
    verify_existing_baseline_linkage(
        existing_summary, baseline_summary_path, baseline_trials_path
    )
    rows = [json.loads(line) for line in baseline_trials_path.read_text(encoding="utf-8").splitlines() if line]
    existing_rows = [json.loads(line) for line in existing_trials_path.read_text(encoding="utf-8").splitlines() if line]
    existing_index = index_existing_convtasnet(existing_rows)
    if len(existing_index) != len(rows) or any(trial_key(row) not in existing_index for row in rows):
        raise RuntimeError("existing Conv-TasNet trials do not match the frozen baseline map")

    artifacts = baseline_summary["artifacts"]
    speaker_model = args.speaker_model or Path(artifacts["speaker_model"])
    frontend.verify_artifact(speaker_model, artifacts.get("speaker_model_sha256"))
    expected_conv_hash = existing_summary["artifacts"].get("convtasnet_model_sha256")
    frontend.verify_artifact(args.conv_tasnet_model, expected_conv_hash)
    config = baseline_summary["config"]
    if config.get("score_aggregation", "max") != "max":
        raise ValueError("ablation requires the baseline max score aggregation")

    separator = frontend.ConvTasNetFrontend(args.conv_tasnet_model, args.device, args.torch_threads)
    extractor = build_speaker(speaker_model, num_threads=args.speaker_threads)
    enrollment_cache: dict[tuple[str, ...], np.ndarray] = {}
    audio_cache: dict[str, np.ndarray] = {}

    def audio(path: str) -> np.ndarray:
        if path not in audio_cache:
            samples, _ = load_audio_mono16k(Path(path))
            audio_cache[path] = np.ascontiguousarray(samples, dtype=np.float32)
        return audio_cache[path]

    def target(row: dict) -> np.ndarray:
        paths = tuple(str(path) for path in row["enrollment_audio_paths"])
        if paths not in enrollment_cache:
            enrollment_cache[paths] = enroll(
                extractor, [(audio(path), TARGET_SAMPLE_RATE) for path in paths]
            )
        return enrollment_cache[paths]

    started = time.perf_counter()
    bandwidth_cache: dict[tuple[str, str | None, float | None], list[np.ndarray]] = {}
    bandwidth_rows: list[dict] = []
    for index, row in enumerate(rows, 1):
        probe_key = (
            str(row["probe_audio_path"]),
            str(row["noise_audio_path"]) if row.get("noise_audio_path") else None,
            float(row["snr_db"]) if row.get("snr_db") is not None else None,
        )
        if probe_key not in bandwidth_cache:
            mixture = frontend.load_probe_audio(row)
            bandwidth_cache[probe_key] = extract_embeddings(
                extractor, bandwidth_round_trip(mixture), config
            )
        current = existing_index[trial_key(row)]
        bandwidth_rows.append(
            {
                **row,
                "baseline_score": float(row["score"]),
                "roundtrip_score": score_embeddings(bandwidth_cache[probe_key], target(row)),
                "convtasnet_score": float(current["score"]),
            }
        )
        if args.progress_every > 0 and index % args.progress_every == 0:
            print(f"bandwidth {index}/{len(rows)}", file=sys.stderr, flush=True)

    clean_rows = [row for row in rows if row["condition"] == "clean"]
    overlap_base_rows = select_overlap_rows(clean_rows, args.negatives_per_target)
    pools = build_interferer_pools(clean_rows)
    overlap_rows: list[dict] = []
    separation_times: list[float] = []
    for index, row in enumerate(overlap_base_rows, 1):
        interferer = select_interferer(row, pools[str(row["split"])], args.seed)
        mixture = mix_speakers(
            audio(str(row["probe_audio_path"])),
            audio(str(interferer["audio_path"])),
            args.sir_db,
        )
        direct_embeddings = extract_embeddings(extractor, mixture, config)
        roundtrip_embeddings = extract_embeddings(
            extractor, bandwidth_round_trip(mixture), config
        )
        sources, separation_sec = separator.separate(mixture)
        separation_times.append(separation_sec)
        source_embeddings = [extract_embeddings(extractor, source, config) for source in sources]
        target_embedding = target(row)
        conv_score, selected_source, source_scores = frontend.score_separated_sources(
            source_embeddings, target_embedding
        )
        overlap_rows.append(
            {
                **row,
                "condition": f"two_speaker_sir_{args.sir_db:g}db",
                "interferer_speaker": interferer["speaker"],
                "interferer_recording_id": interferer["recording_id"],
                "interferer_audio_path": interferer["audio_path"],
                "direct_score": score_embeddings(direct_embeddings, target_embedding),
                "roundtrip_score": score_embeddings(roundtrip_embeddings, target_embedding),
                "convtasnet_score": conv_score,
                "convtasnet_selected_source": selected_source,
                "convtasnet_source_scores": source_scores,
            }
        )
        if args.progress_every > 0 and index % args.progress_every == 0:
            print(f"overlap {index}/{len(overlap_base_rows)}", file=sys.stderr, flush=True)

    baseline_threshold = float(baseline_summary["dev_threshold"]["threshold"])
    roundtrip_threshold = dev_threshold(bandwidth_rows, "roundtrip_score", condition="clean")
    conv_threshold = existing_summary["convtasnet_dev_threshold"]
    overlap_fields = ("direct_score", "roundtrip_score", "convtasnet_score")
    overlap_thresholds = {field: dev_threshold(overlap_rows, field) for field in overlap_fields}
    summary = {
        "study": "convtasnet-bandwidth-and-speaker-count-ablation",
        "status": "diagnostic_only",
        "config": {
            "device": args.device,
            "torch_threads": args.torch_threads,
            "speaker_threads": args.speaker_threads,
            "seed": args.seed,
            "sir_db": args.sir_db,
            "negatives_per_target": args.negatives_per_target,
            "interferer_policy": "same_split_positive_probe_excluding_target_and_primary",
            "source_selection": "max_eres2net_score_across_two_sources_for_all_labels",
            "baseline_config": config,
        },
        "artifacts": {
            "baseline_dir": str(args.baseline_dir),
            "baseline_summary_sha256": frontend.sha256(baseline_summary_path),
            "baseline_trials_sha256": frontend.sha256(baseline_trials_path),
            "existing_convtasnet_dir": str(args.existing_convtasnet_dir),
            "existing_convtasnet_summary_sha256": frontend.sha256(existing_summary_path),
            "existing_convtasnet_trials_sha256": frontend.sha256(existing_trials_path),
            "speaker_model": str(speaker_model),
            "speaker_model_sha256": frontend.sha256(speaker_model),
            "convtasnet_model": str(args.conv_tasnet_model),
            "convtasnet_model_sha256": frontend.sha256(args.conv_tasnet_model),
        },
        "baseline_threshold": baseline_threshold,
        "bandwidth_ablation": {
            "roundtrip_dev_threshold": roundtrip_threshold,
            "convtasnet_dev_threshold": conv_threshold,
            "baseline_at_baseline_threshold": metrics_by_condition(
                bandwidth_rows, "baseline_score", baseline_threshold
            ),
            "roundtrip_at_baseline_threshold": metrics_by_condition(
                bandwidth_rows, "roundtrip_score", baseline_threshold
            ),
            "roundtrip_at_own_dev_threshold": metrics_by_condition(
                bandwidth_rows, "roundtrip_score", float(roundtrip_threshold["threshold"])
            ),
            "convtasnet_at_own_dev_threshold": metrics_by_condition(
                bandwidth_rows, "convtasnet_score", float(conv_threshold["threshold"])
            ),
            "test_diagnostic_eer": {
                "baseline_score": test_eer_by_condition(bandwidth_rows, "baseline_score"),
                "roundtrip_score": test_eer_by_condition(bandwidth_rows, "roundtrip_score"),
                "convtasnet_score": test_eer_by_condition(bandwidth_rows, "convtasnet_score"),
            },
            "score_shift_roundtrip_minus_baseline": paired_shift(
                bandwidth_rows, "baseline_score", "roundtrip_score"
            ),
            "score_shift_convtasnet_minus_roundtrip": paired_shift(
                bandwidth_rows, "roundtrip_score", "convtasnet_score"
            ),
        },
        "two_speaker_overlap": {
            "trial_counts": {
                "total": len(overlap_rows),
                "dev": sum(row["split"] == "dev" for row in overlap_rows),
                "test": sum(row["split"] == "test" for row in overlap_rows),
                "target": sum(int(row["label"]) == 1 for row in overlap_rows),
                "non_target": sum(int(row["label"]) == 0 for row in overlap_rows),
            },
            "dev_thresholds": overlap_thresholds,
            "test_at_own_dev_threshold": {
                field: metrics_by_condition(
                    overlap_rows, field, float(overlap_thresholds[field]["threshold"])
                )
                for field in overlap_fields
            },
            "test_at_original_baseline_threshold": {
                field: metrics_by_condition(overlap_rows, field, baseline_threshold)
                for field in overlap_fields
            },
            "test_diagnostic_eer": {
                field: test_eer_by_condition(overlap_rows, field) for field in overlap_fields
            },
            "score_shift_roundtrip_minus_direct": paired_shift(
                overlap_rows, "direct_score", "roundtrip_score"
            ),
            "score_shift_convtasnet_minus_roundtrip": paired_shift(
                overlap_rows, "roundtrip_score", "convtasnet_score"
            ),
        },
        "runtime": {
            "total_sec": time.perf_counter() - started,
            "model_load_sec": separator.load_sec,
            "bandwidth_trials": len(bandwidth_rows),
            "bandwidth_unique_mixtures": len(bandwidth_cache),
            "overlap_trials": len(overlap_rows),
            "mean_overlap_separation_sec": statistics.fmean(separation_times),
        },
        "limitations": [
            "diagnostic synthetic Chinese two-speaker mixtures, not a release acceptance set",
            "one deterministic non-target trial per enrolled target in the overlap ablation",
            "full-duration 0 dB overlap without room impulse response or device capture effects",
            "Conv-TasNet checkpoint is an 8 kHz English WHAM sep_clean two-speaker separator",
            "max scoring across both outputs is non-oracle but creates two chances for false accepts",
        ],
    }

    for name, output_rows in (("bandwidth_trials.jsonl", bandwidth_rows), ("overlap_trials.jsonl", overlap_rows)):
        with (args.out_dir / name).open("w", encoding="utf-8") as handle:
            for row in output_rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
