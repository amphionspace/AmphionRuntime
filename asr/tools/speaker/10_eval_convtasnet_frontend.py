#!/usr/bin/env python3
"""Evaluate a frozen Conv-TasNet front-end before the existing ERes2Net scorer.

The input is a completed ``07_eval_voiceprint_verification.py`` result directory.
Its trial map freezes speakers, enrollment/probe recordings, traffic-noise files,
SNRs, and baseline ERes2Net scores. Conv-TasNet is a two-source separator, not a
speaker embedder, so both separated sources are scored with ERes2Net and the
maximum score is used for every target and non-target trial.
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

PILOT_SPEC = importlib.util.spec_from_file_location(
    "voiceprint_pilot_shared", SCRIPT_DIR / "07_eval_voiceprint_verification.py"
)
assert PILOT_SPEC is not None and PILOT_SPEC.loader is not None
pilot = importlib.util.module_from_spec(PILOT_SPEC)
sys.modules[PILOT_SPEC.name] = pilot
PILOT_SPEC.loader.exec_module(pilot)

from ts_asr import build_speaker, enroll, load_audio_mono16k  # noqa: E402


TARGET_SAMPLE_RATE = 16_000
CONVTASNET_SAMPLE_RATE = 8_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(path: Path, expected_sha256: str | None) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if expected_sha256 and sha256(path) != expected_sha256:
        raise RuntimeError(f"artifact hash changed: {path}")


def prepare_output_dir(path: Path) -> None:
    """Create a fresh result directory without overwriting prior artifacts."""
    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(path)
        if any(path.iterdir()):
            raise FileExistsError(f"refusing to overwrite non-empty result directory: {path}")
        return
    path.mkdir(parents=True)


def resample_audio(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Polyphase-resample a finite mono waveform and preserve contiguous float32."""
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    if not len(samples):
        raise ValueError("audio must not be empty")
    if source_rate == target_rate:
        return samples
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    import math

    from scipy.signal import resample_poly

    divisor = math.gcd(source_rate, target_rate)
    return np.ascontiguousarray(
        resample_poly(samples, target_rate // divisor, source_rate // divisor),
        dtype=np.float32,
    )


class ConvTasNetFrontend:
    """Lazy Asteroid wrapper that enforces the published 8 kHz/two-source contract."""

    def __init__(self, model_path: Path, device: str, torch_threads: int) -> None:
        import torch
        from asteroid.models import BaseModel

        if torch_threads <= 0:
            raise ValueError("torch-threads must be positive")
        torch.set_num_threads(torch_threads)
        self.torch = torch
        self.device = torch.device(device)
        started = time.perf_counter()
        self.model = BaseModel.from_pretrained(str(model_path)).eval().to(self.device)
        self.load_sec = time.perf_counter() - started
        model_rate = int(round(float(getattr(self.model, "sample_rate", 0))))
        if model_rate != CONVTASNET_SAMPLE_RATE:
            raise RuntimeError(
                f"Conv-TasNet model reports {model_rate} Hz; expected {CONVTASNET_SAMPLE_RATE} Hz"
            )

    def separate(self, samples_16k: np.ndarray) -> tuple[list[np.ndarray], float]:
        torch = self.torch
        samples_8k = resample_audio(
            samples_16k, TARGET_SAMPLE_RATE, CONVTASNET_SAMPLE_RATE
        )
        tensor = torch.from_numpy(samples_8k).unsqueeze(0).to(self.device)
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        started = time.perf_counter()
        with torch.inference_mode():
            separated = self.model(tensor)
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        elapsed = time.perf_counter() - started
        output = separated.detach().cpu().numpy()
        if output.ndim != 3 or output.shape[0] != 1 or output.shape[1] != 2:
            raise RuntimeError(f"expected [1, 2, time] Conv-TasNet output, got {output.shape}")
        if not np.isfinite(output).all():
            raise RuntimeError("Conv-TasNet returned non-finite samples")
        sources: list[np.ndarray] = []
        for source in output[0]:
            restored = resample_audio(
                source, CONVTASNET_SAMPLE_RATE, TARGET_SAMPLE_RATE
            )
            if len(restored) < len(samples_16k):
                restored = np.pad(restored, (0, len(samples_16k) - len(restored)))
            sources.append(
                np.ascontiguousarray(restored[: len(samples_16k)], dtype=np.float32)
            )
        return sources, elapsed


def extract_window_embeddings(
    extractor,
    samples: np.ndarray,
    *,
    win_sec: float,
    hop_sec: float,
    min_duration_sec: float,
) -> list[np.ndarray]:
    """Extract the same complete windows used by the baseline max scorer."""
    minimum = int(min_duration_sec * TARGET_SAMPLE_RATE)
    if len(samples) < minimum:
        return []
    window = int(win_sec * TARGET_SAMPLE_RATE)
    hop = int(hop_sec * TARGET_SAMPLE_RATE)
    if window <= 0 or hop <= 0:
        raise ValueError("window and hop must be positive")
    segments = (
        [samples]
        if len(samples) < window
        else [samples[start : start + window] for start in range(0, len(samples) - window + 1, hop)]
    )
    embeddings: list[np.ndarray] = []
    for segment in segments:
        stream = extractor.create_stream()
        stream.accept_waveform(
            sample_rate=TARGET_SAMPLE_RATE,
            waveform=np.ascontiguousarray(segment, dtype=np.float32),
        )
        stream.input_finished()
        if not extractor.is_ready(stream):
            continue
        embedding = np.asarray(extractor.compute(stream), dtype=np.float32)
        embedding /= np.linalg.norm(embedding) + 1e-9
        embeddings.append(embedding)
    return embeddings


def score_separated_sources(
    source_embeddings: Sequence[Sequence[np.ndarray]], target_embedding: np.ndarray
) -> tuple[float, int, list[float]]:
    """Max-score both sources; applying the same rule to negatives protects FAR."""
    target = np.asarray(target_embedding, dtype=np.float32)
    target /= np.linalg.norm(target) + 1e-9
    source_scores: list[float] = []
    for embeddings in source_embeddings:
        if embeddings:
            source_scores.append(max(float(np.dot(item, target)) for item in embeddings))
        else:
            source_scores.append(float("-inf"))
    if not source_scores or not np.isfinite(source_scores).any():
        raise RuntimeError("no scoreable Conv-TasNet output source")
    selected = int(np.argmax(source_scores))
    return source_scores[selected], selected, source_scores


def load_probe_audio(row: dict) -> np.ndarray:
    # load_audio_mono16k returns normalized 16 kHz samples plus the source file's
    # original sample rate. The second value must not drive another resample.
    samples, _ = load_audio_mono16k(Path(row["probe_audio_path"]))
    if row.get("snr_db") is not None:
        noise, _ = load_audio_mono16k(Path(row["noise_audio_path"]))
        samples = pilot.mix_at_snr(samples, noise, float(row["snr_db"]))
    return np.ascontiguousarray(samples, dtype=np.float32)


def metrics_by_condition(
    rows: Sequence[dict], score_field: str, threshold: float
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for condition in sorted({str(row["condition"]) for row in rows if row["split"] == "test"}):
        selected = [
            row for row in rows if row["split"] == "test" and row["condition"] == condition
        ]
        result[condition] = pilot.binary_metrics(
            [float(row[score_field]) for row in selected],
            [int(row["label"]) for row in selected],
            threshold,
        )
    return result


def select_far_constrained_threshold(
    scores: Sequence[float], labels: Sequence[int], max_far: float
) -> dict:
    """Minimize dev FRR without exceeding a pre-registered FAR limit."""
    if not 0.0 <= max_far <= 1.0:
        raise ValueError("max_far must be between 0 and 1")
    unique = sorted({float(score) for score in scores})
    if not unique:
        raise ValueError("cannot select a threshold without scores")
    epsilon = 1e-7
    candidates = [unique[0] - epsilon]
    candidates.extend((left + right) / 2.0 for left, right in zip(unique, unique[1:]))
    candidates.append(unique[-1] + epsilon)
    feasible = []
    for threshold in candidates:
        metrics = pilot.binary_metrics(scores, labels, threshold)
        if metrics["far"] <= max_far:
            feasible.append(metrics)
    if not feasible:
        raise RuntimeError("no threshold satisfies the FAR constraint")
    selected = min(
        feasible,
        key=lambda row: (float(row["frr"]), float(row["far"]), float(row["threshold"])),
    )
    return {**selected, "max_far": max_far, "source": "dev_far_constrained"}


def render_report(summary: dict) -> str:
    baseline = summary["baseline_at_baseline_threshold"]
    same = summary["convtasnet_at_baseline_threshold"]
    calibrated = summary["convtasnet_at_own_dev_threshold"]
    far_constrained = summary["convtasnet_at_dev_far_constrained_threshold"]
    conditions = ["clean", "traffic_snr_5db", "traffic_snr_0db"]

    def cell(metrics: dict, condition: str) -> str:
        row = metrics[condition]
        return f"{row['far']:.2%} / {row['frr']:.2%}"

    lines = [
        "# Conv-TasNet → ERes2Net 合成声纹复验",
        "",
        "> Conv-TasNet 是 8 kHz 两路语音分离前端，不是 ERes2Net 的替代 embedding 模型。",
        "",
        "| 配置 | 阈值 | clean FAR/FRR | 5 dB FAR/FRR | 0 dB FAR/FRR |",
        "| --- | ---: | ---: | ---: | ---: |",
        (
            f"| ERes2Net baseline | {summary['baseline_threshold']:.6f} | "
            + " | ".join(cell(baseline, condition) for condition in conditions)
            + " |"
        ),
        (
            f"| Conv-TasNet → ERes2Net（原阈值） | {summary['baseline_threshold']:.6f} | "
            + " | ".join(cell(same, condition) for condition in conditions)
            + " |"
        ),
        (
            f"| Conv-TasNet → ERes2Net（clean dev 重校准） | "
            f"{summary['convtasnet_dev_threshold']['threshold']:.6f} | "
            + " | ".join(cell(calibrated, condition) for condition in conditions)
            + " |"
        ),
        (
            f"| Conv-TasNet → ERes2Net（dev FAR 约束） | "
            f"{summary['convtasnet_dev_far_constrained_threshold']['threshold']:.6f} | "
            + " | ".join(cell(far_constrained, condition) for condition in conditions)
            + " |"
        ),
        "",
        "## 运行信息",
        "",
        f"- trials：{summary['runtime']['trials']}；唯一混音：{summary['runtime']['unique_mixtures']}。",
        f"- device：`{summary['config']['device']}`。",
        f"- 平均 Conv-TasNet 分离耗时：{summary['runtime']['mean_separation_sec'] * 1000:.2f} ms/唯一混音。",
        f"- 平均 ERes2Net 表征提取耗时：{summary['runtime']['mean_embedding_sec'] * 1000:.2f} ms/唯一混音。",
        "",
        "## 证据边界",
        "",
        "- 复用 baseline trial map，speaker、enrollment、probe、noise、SNR 和标签均不变。",
        "- 两路输出都计算目标相似度并取最大；同一规则也用于 non-target，避免人为压低 FAR。",
        "- checkpoint 训练于英文 WHAM sep_clean、8 kHz、两人语音分离，不匹配中文单人加交通噪声。",
        "- 合成加性噪声不代表真实设备、混响、AGC、风噪或交通现场链路。",
        "- GPU 耗时只用于本机实验，不代表 Android/Harmony 端侧性能。",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--conv-tasnet-model", type=Path, required=True)
    parser.add_argument("--speaker-model", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--torch-threads", type=int, default=1)
    parser.add_argument("--speaker-threads", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prepare_output_dir(args.out_dir)
    baseline_summary_path = args.baseline_dir / "summary.json"
    baseline_trials_path = args.baseline_dir / "trials.jsonl"
    verify_artifact(baseline_summary_path, None)
    verify_artifact(baseline_trials_path, None)
    verify_artifact(args.conv_tasnet_model, None)
    baseline_summary = json.loads(baseline_summary_path.read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in baseline_trials_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if baseline_summary["config"].get("score_aggregation", "max") != "max":
        raise ValueError("Conv-TasNet comparison currently requires baseline max aggregation")
    artifacts = baseline_summary["artifacts"]
    speaker_model = args.speaker_model or Path(artifacts["speaker_model"])
    verify_artifact(speaker_model, artifacts.get("speaker_model_sha256"))
    for manifest in artifacts.get("cut_manifests", []):
        verify_artifact(Path(manifest), artifacts.get("cut_manifest_sha256", {}).get(manifest))
    if artifacts.get("noise_cuts"):
        verify_artifact(Path(artifacts["noise_cuts"]), artifacts.get("noise_cuts_sha256"))

    frontend = ConvTasNetFrontend(args.conv_tasnet_model, args.device, args.torch_threads)
    extractor = build_speaker(speaker_model, num_threads=args.speaker_threads)
    config = baseline_summary["config"]
    enrollment_cache: dict[tuple[str, ...], np.ndarray] = {}
    probe_cache: dict[tuple[str, str | None, float | None], dict] = {}
    output_rows: list[dict] = []
    separation_times: list[float] = []
    embedding_times: list[float] = []
    started = time.perf_counter()

    for index, row in enumerate(rows, 1):
        enrollment_paths = tuple(str(path) for path in row["enrollment_audio_paths"])
        if enrollment_paths not in enrollment_cache:
            enrollment_audio = [load_audio_mono16k(Path(path)) for path in enrollment_paths]
            enrollment_cache[enrollment_paths] = enroll(extractor, enrollment_audio)
        target_embedding = enrollment_cache[enrollment_paths]

        probe_key = (
            str(row["probe_audio_path"]),
            str(row["noise_audio_path"]) if row.get("noise_audio_path") else None,
            float(row["snr_db"]) if row.get("snr_db") is not None else None,
        )
        if probe_key not in probe_cache:
            mixture = load_probe_audio(row)
            sources, separation_sec = frontend.separate(mixture)
            embedding_started = time.perf_counter()
            source_embeddings = [
                extract_window_embeddings(
                    extractor,
                    source,
                    win_sec=float(config["win_sec"]),
                    hop_sec=float(config["hop_sec"]),
                    min_duration_sec=float(config["min_duration_sec"]),
                )
                for source in sources
            ]
            embedding_sec = time.perf_counter() - embedding_started
            probe_cache[probe_key] = {
                "embeddings": source_embeddings,
                "separation_sec": separation_sec,
                "embedding_sec": embedding_sec,
                "source_rms": [
                    float(np.sqrt(np.mean(np.square(source), dtype=np.float64)))
                    for source in sources
                ],
            }
            separation_times.append(separation_sec)
            embedding_times.append(embedding_sec)
        cached = probe_cache[probe_key]
        score, selected_source, source_scores = score_separated_sources(
            cached["embeddings"], target_embedding
        )
        output_rows.append(
            {
                **row,
                "baseline_score": float(row["score"]),
                "score": score,
                "convtasnet_selected_source": selected_source,
                "convtasnet_source_scores": source_scores,
                "convtasnet_source_rms": cached["source_rms"],
            }
        )
        if args.progress_every > 0 and index % args.progress_every == 0:
            print(
                f"processed {index}/{len(rows)} trials; "
                f"unique mixtures={len(probe_cache)}",
                file=sys.stderr,
                flush=True,
            )

    dev_rows = [row for row in output_rows if row["split"] == "dev"]
    convtasnet_dev_threshold = pilot.select_eer_threshold(
        [row["score"] for row in dev_rows], [row["label"] for row in dev_rows]
    )
    baseline_threshold = float(baseline_summary["dev_threshold"]["threshold"])
    convtasnet_dev_far_constrained_threshold = select_far_constrained_threshold(
        [row["score"] for row in dev_rows],
        [row["label"] for row in dev_rows],
        float(baseline_summary["dev_threshold"]["far"]),
    )
    baseline_metrics = metrics_by_condition(output_rows, "baseline_score", baseline_threshold)
    conv_same_metrics = metrics_by_condition(output_rows, "score", baseline_threshold)
    conv_calibrated_metrics = metrics_by_condition(
        output_rows, "score", float(convtasnet_dev_threshold["threshold"])
    )
    conv_far_constrained_metrics = metrics_by_condition(
        output_rows,
        "score",
        float(convtasnet_dev_far_constrained_threshold["threshold"]),
    )
    diagnostic_eer: dict[str, dict] = {}
    score_shift: dict[str, dict] = {}
    paired_decisions_at_baseline_threshold: dict[str, dict[str, int]] = {}
    for condition in sorted({row["condition"] for row in output_rows if row["split"] == "test"}):
        selected = [
            row for row in output_rows if row["split"] == "test" and row["condition"] == condition
        ]
        diagnostic_eer[condition] = pilot.select_eer_threshold(
            [row["score"] for row in selected], [row["label"] for row in selected]
        )
        score_shift[condition] = {}
        for label, label_name in ((1, "target"), (0, "non_target")):
            labeled = [row for row in selected if row["label"] == label]
            score_shift[condition][label_name] = {
                "baseline": pilot.describe([row["baseline_score"] for row in labeled]),
                "convtasnet": pilot.describe([row["score"] for row in labeled]),
                "paired_delta": pilot.describe(
                    [row["score"] - row["baseline_score"] for row in labeled]
                ),
            }
        transitions = {
            "baseline_correct_convtasnet_correct": 0,
            "baseline_correct_convtasnet_wrong": 0,
            "baseline_wrong_convtasnet_correct": 0,
            "baseline_wrong_convtasnet_wrong": 0,
        }
        for row in selected:
            expected_accept = bool(row["label"])
            baseline_correct = (row["baseline_score"] >= baseline_threshold) == expected_accept
            convtasnet_correct = (row["score"] >= baseline_threshold) == expected_accept
            transitions[
                f"baseline_{'correct' if baseline_correct else 'wrong'}_"
                f"convtasnet_{'correct' if convtasnet_correct else 'wrong'}"
            ] += 1
        paired_decisions_at_baseline_threshold[condition] = transitions

    summary = {
        "study": "convtasnet-wham-sepclean-before-eres2net-paired-ab",
        "status": "diagnostic_only",
        "config": {
            "device": args.device,
            "torch_threads": args.torch_threads,
            "speaker_threads": args.speaker_threads,
            "source_selection": "max_eres2net_score_across_two_sources",
            "convtasnet_sample_rate": CONVTASNET_SAMPLE_RATE,
            "eres2net_sample_rate": TARGET_SAMPLE_RATE,
            "baseline_config": config,
        },
        "artifacts": {
            "baseline_dir": str(args.baseline_dir),
            "baseline_summary_sha256": sha256(baseline_summary_path),
            "baseline_trials_sha256": sha256(baseline_trials_path),
            "speaker_model": str(speaker_model),
            "speaker_model_sha256": sha256(speaker_model),
            "convtasnet_model": str(args.conv_tasnet_model),
            "convtasnet_model_sha256": sha256(args.conv_tasnet_model),
            "convtasnet_model_card": "https://huggingface.co/mpariente/ConvTasNet_WHAM_sepclean",
        },
        "baseline_threshold": baseline_threshold,
        "convtasnet_dev_threshold": convtasnet_dev_threshold,
        "convtasnet_dev_far_constrained_threshold": convtasnet_dev_far_constrained_threshold,
        "baseline_at_baseline_threshold": baseline_metrics,
        "convtasnet_at_baseline_threshold": conv_same_metrics,
        "convtasnet_at_own_dev_threshold": conv_calibrated_metrics,
        "convtasnet_at_dev_far_constrained_threshold": conv_far_constrained_metrics,
        "convtasnet_test_diagnostic_eer": diagnostic_eer,
        "score_shift": score_shift,
        "paired_decisions_at_baseline_threshold": paired_decisions_at_baseline_threshold,
        "runtime": {
            "total_sec": time.perf_counter() - started,
            "model_load_sec": frontend.load_sec,
            "trials": len(output_rows),
            "unique_mixtures": len(probe_cache),
            "unique_enrollments": len(enrollment_cache),
            "mean_separation_sec": statistics.fmean(separation_times),
            "mean_embedding_sec": statistics.fmean(embedding_times),
        },
        "limitations": [
            "Conv-TasNet checkpoint is an 8 kHz two-speaker separator trained on English WHAM sep_clean",
            "evaluation input is Chinese single-speaker speech with synthetic additive traffic noise",
            "both separated sources are max-scored for target and non-target trials",
            "synthetic additive noise is not a real device or traffic capture chain",
            "GPU timing is not an Android or Harmony edge benchmark",
        ],
    }
    with (args.out_dir / "trials.jsonl").open("w", encoding="utf-8") as handle:
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
