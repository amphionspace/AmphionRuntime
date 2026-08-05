#!/usr/bin/env python3
"""在 Linux CPU 上复验固定 2 秒 Conv-TasNet overlap rescue 全链路。

该工具刻意复刻 Harmony 真机 pilot 的平台无关部分：

  三段 enrollment 均值 -> 2 秒块/0.5 秒交叠 -> Conv-TasNet 两路分离
  -> 每路一个完整 2 秒 ERes2Net embedding -> 0.25 选流
  -> 低置信块静音 -> cosine crossfade -> ZH_EN ASR 重识别

它不验证 Harmony SDK 的 isLast/onComplete/cancel；这些门只能由真机公共 API 报告证明。
模型和客户音频只通过路径传入，报告记录哈希，不复制到输出目录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


ASR_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ASR_ROOT.parent
sys.path.insert(0, str(ASR_ROOT / "tools" / "speaker"))

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 32000
OVERLAP_SAMPLES = 8000
HOP_SAMPLES = CHUNK_SAMPLES - OVERLAP_SAMPLES
DEFAULT_THRESHOLD = 0.25
DEFAULT_MAX_SEPARATOR_P95_RTF = 0.35
DEFAULT_MAX_PEAK_DELTA_MB = 250.0
EXPECTED_SEPARATOR_SHA256 = "f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab"
EXPECTED_SPEAKER_SHA256 = "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b"
EXPECTED_ASR_SHA256 = {
    "encoder.int8.onnx": "0e86d904862c53e9bdff44df0650a109d61783cb262a7233742f68198abbcbba",
    "decoder.onnx": "519597bb518f9dacb01d0acc9c8d9fb6d8fb03b3f993bbcf99eb6d42ea79c286",
    "joiner.onnx": "bfbd996a09853f43600b37b6d4332968e280498b4fbf23a2db374d6a8f31d2da",
    "joiner.int8.onnx": "bfbd996a09853f43600b37b6d4332968e280498b4fbf23a2db374d6a8f31d2da",
    "tokens.txt": "29a20d469f044011706d9720ff31770e5dcd6c30714943282e9563a55c6918f5",
}
DEFAULT_INPUT_HASH_MANIFEST = (
    WORKSPACE_ROOT / "docs" / "speaker" / "CONVTASNET_LINUX_INPUT_HASHES_20260804.json"
)

ENROLLMENT_NAMES = (
    "000_enrollment_far.wav",
    "001_enrollment_mid.wav",
    "002_enrollment_near.wav",
)
CUSTOMER_CASES = (
    ("C1", "101_C1.wav", "customer"),
    ("C2", "102_C2.wav", "customer"),
    ("C3", "103_C3.wav", "customer"),
)
NEGATIVE_CASES = (
    ("target-only", "201_target_only.wav", "target-only"),
    ("other-only", "202_other_only.wav", "other-only"),
)


@dataclass(frozen=True)
class MemorySample:
    elapsed_seconds: float
    vm_rss_kb: int
    vm_hwm_kb: int
    vm_data_kb: int
    threads: int


class ProcSampler:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self.started_at = time.monotonic()
        self.samples: List[MemorySample] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="overlap-rescue-memory", daemon=True)

    def start(self) -> None:
        self._sample_once()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_seconds * 3))
        self._sample_once()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample_once()

    def _sample_once(self) -> None:
        status = read_proc_status(Path("/proc/self/status"))
        if status is None:
            return
        self.samples.append(
            MemorySample(
                elapsed_seconds=round(time.monotonic() - self.started_at, 6),
                vm_rss_kb=status.get("VmRSS", 0),
                vm_hwm_kb=status.get("VmHWM", 0),
                vm_data_kb=status.get("VmData", 0),
                threads=status.get("Threads", 0),
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("baseline", "full"), required=True)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--separator-model", type=Path)
    parser.add_argument("--speaker-model", type=Path, required=True)
    parser.add_argument("--asr-model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument(
        "--input-hash-manifest",
        type=Path,
        default=DEFAULT_INPUT_HASH_MANIFEST,
        help="Expected filename-to-SHA256 JSON; defaults to the frozen C1-C3 pilot inputs.",
    )
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--separator-threads", type=int, default=4)
    parser.add_argument("--speaker-threads", type=int, default=2)
    parser.add_argument("--asr-threads", type=int, default=2)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument("--post-observe-seconds", type=float, default=3.0)
    parser.add_argument(
        "--max-separator-p95-rtf", type=float, default=DEFAULT_MAX_SEPARATOR_P95_RTF
    )
    parser.add_argument(
        "--max-peak-delta-mb", type=float, default=DEFAULT_MAX_PEAK_DELTA_MB
    )
    parser.add_argument(
        "--skip-negative",
        action="store_true",
        help="只跑 C1-C3；报告整体状态为 INCONCLUSIVE，不可作为完整门禁。",
    )
    parser.add_argument("--write-enhanced-wav", action="store_true")
    args = parser.parse_args()
    if args.mode == "full" and args.separator_model is None:
        parser.error("--mode full requires --separator-model")
    if args.cycles <= 0:
        parser.error("--cycles must be positive")
    for name in ("separator_threads", "speaker_threads", "asr_threads"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if not -1 <= args.threshold <= 1:
        parser.error("--threshold must be in [-1, 1]")
    if args.sample_interval <= 0 or args.post_observe_seconds < 0:
        parser.error("memory sampling intervals must be non-negative")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asr_model_artifacts(model_dir: Path) -> List[Dict[str, Any]]:
    names = ["encoder.int8.onnx", "decoder.onnx", "tokens.txt"]
    joiner = "joiner.int8.onnx" if (model_dir / "joiner.int8.onnx").is_file() else "joiner.onnx"
    names.append(joiner)
    missing = [name for name in names if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"ASR model directory is missing: {', '.join(missing)}")
    return [
        {
            "name": name,
            "path": str(model_dir / name),
            "size_bytes": (model_dir / name).stat().st_size,
            "sha256": sha256(model_dir / name),
        }
        for name in names
    ]


def require_sha256(path: Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def verify_input_hashes(case_dir: Path, manifest_path: Path, filenames: Sequence[str]) -> None:
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(expected, dict):
        raise ValueError("input hash manifest must be a JSON object")
    for filename in filenames:
        value = expected.get(filename)
        if not isinstance(value, str):
            raise ValueError(f"input hash manifest is missing {filename}")
        require_sha256(case_dir / filename, value, filename)


def read_proc_status(path: Path) -> Optional[Dict[str, int]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    result: Dict[str, int] = {}
    for line in lines:
        key, separator, rest = line.partition(":")
        if not separator or key not in {"VmRSS", "VmHWM", "VmData", "Threads"}:
            continue
        value = rest.strip().split()[0]
        try:
            result[key] = int(value)
        except ValueError:
            continue
    return result


def nearest_rank_percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def cosine_ramp(overlap_samples: int = OVERLAP_SAMPLES) -> np.ndarray:
    if overlap_samples < 2:
        raise ValueError("overlap_samples must be at least 2")
    positions = np.arange(overlap_samples, dtype=np.float64)
    return ((1.0 - np.cos(np.pi * positions / (overlap_samples - 1))) / 2.0).astype(
        np.float32
    )


def case_gate(expectation: str, text: str, selected: Sequence[int]) -> Tuple[bool, str]:
    if expectation == "customer":
        ok = "上海" in text and "你好" not in text
        return ok, "contains-shanghai-without-hello" if ok else "customer-text-gate"
    if expectation == "target-only":
        ok = bool(text) and any(value >= 0 for value in selected)
        return ok, "target-retained" if ok else "target-only-gate"
    if expectation == "other-only":
        ok = not text and all(value < 0 for value in selected)
        return ok, "other-rejected" if ok else "other-only-gate"
    raise ValueError(f"unsupported expectation: {expectation}")


def ensure_output_dir(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def require_inputs(case_dir: Path, include_negative: bool) -> List[Tuple[str, Path, str]]:
    cases = list(CUSTOMER_CASES)
    if include_negative:
        cases.extend(NEGATIVE_CASES)
    required = list(ENROLLMENT_NAMES) + [filename for _, filename, _ in cases]
    missing = [name for name in required if not (case_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"case directory is missing: {', '.join(missing)}")
    return [(name, case_dir / filename, expectation) for name, filename, expectation in cases]


def embedding(extractor: Any, samples: np.ndarray) -> np.ndarray:
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=np.ascontiguousarray(samples))
    stream.input_finished()
    if not extractor.is_ready(stream):
        raise RuntimeError("speaker extractor is not ready for a 2-second chunk")
    value = np.asarray(extractor.compute(stream), dtype=np.float32)
    norm = float(np.linalg.norm(value))
    if not np.isfinite(value).all() or norm <= 0:
        raise RuntimeError("speaker extractor returned an invalid embedding")
    return value / norm


def rms_normalize(candidate: np.ndarray, input_rms: float, available: int) -> np.ndarray:
    output_rms = float(np.sqrt(np.mean(np.square(candidate[:available], dtype=np.float64))))
    return np.ascontiguousarray(candidate * (input_rms / max(1e-9, output_rms)), dtype=np.float32)


def run_rescue(
    session: Any,
    extractor: Any,
    target_embedding: np.ndarray,
    samples: np.ndarray,
    threshold: float,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    starts = list(range(0, len(samples), HOP_SAMPLES))
    accumulator = np.zeros(len(samples) + CHUNK_SAMPLES, dtype=np.float32)
    weights = np.zeros_like(accumulator)
    ramp = cosine_ramp()
    selected: List[int] = []
    score0: List[float] = []
    score1: List[float] = []
    inference_ms: List[float] = []
    speaker_ms: List[float] = []
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    for chunk_index, start in enumerate(starts):
        available = min(CHUNK_SAMPLES, len(samples) - start)
        chunk = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
        chunk[:available] = samples[start : start + available]
        input_rms = float(np.sqrt(np.mean(np.square(chunk[:available], dtype=np.float64))))

        inference_started = time.perf_counter()
        output = session.run([output_name], {input_name: chunk[None, :]})[0]
        inference_ms.append((time.perf_counter() - inference_started) * 1000.0)
        output = np.asarray(output, dtype=np.float32)
        if output.shape != (1, 2, CHUNK_SAMPLES) or not np.isfinite(output).all():
            raise RuntimeError(f"separator output must be finite [1,2,32000], got {output.shape}")

        candidates: List[np.ndarray] = []
        scores: List[float] = []
        for stream_index in range(2):
            candidate = rms_normalize(output[0, stream_index], input_rms, available)
            speaker_started = time.perf_counter()
            candidate_embedding = embedding(extractor, candidate)
            speaker_ms.append((time.perf_counter() - speaker_started) * 1000.0)
            candidates.append(candidate)
            scores.append(float(np.dot(target_embedding, candidate_embedding)))
        score0.append(scores[0])
        score1.append(scores[1])
        best_stream = 1 if scores[1] > scores[0] else 0
        accepted = scores[best_stream] >= threshold
        selected.append(best_stream if accepted else -1)

        weight = np.ones(CHUNK_SAMPLES, dtype=np.float32)
        if chunk_index > 0:
            weight[:OVERLAP_SAMPLES] = ramp
        if chunk_index + 1 < len(starts):
            weight[-OVERLAP_SAMPLES:] = ramp[::-1]
        value = candidates[best_stream] if accepted else np.zeros(CHUNK_SAMPLES, dtype=np.float32)
        end = start + CHUNK_SAMPLES
        accumulator[start:end] += value * weight
        weights[start:end] += weight

    enhanced = accumulator[: len(samples)] / np.maximum(weights[: len(samples)], 1e-6)
    if not np.isfinite(enhanced).all():
        raise RuntimeError("enhanced PCM is not finite")
    return np.ascontiguousarray(enhanced, dtype=np.float32), {
        "starts": starts,
        "selected": selected,
        "score0": score0,
        "score1": score1,
        "inference_ms": inference_ms,
        "speaker_ms": speaker_ms,
    }


def memory_summary(samples: Sequence[MemorySample]) -> Dict[str, Any]:
    if not samples:
        return {"status": "INCONCLUSIVE", "sample_count": 0}
    return {
        "status": "PASS",
        "sample_count": len(samples),
        "observation_seconds": round(samples[-1].elapsed_seconds, 3),
        "head_rss_mb": round(samples[0].vm_rss_kb / 1024.0, 3),
        "tail_rss_mb": round(samples[-1].vm_rss_kb / 1024.0, 3),
        "peak_rss_mb": round(max(sample.vm_rss_kb for sample in samples) / 1024.0, 3),
        "peak_hwm_mb": round(max(sample.vm_hwm_kb for sample in samples) / 1024.0, 3),
        "peak_vm_data_mb": round(max(sample.vm_data_kb for sample in samples) / 1024.0, 3),
        "head_threads": samples[0].threads,
        "tail_threads": samples[-1].threads,
        "peak_threads": max(sample.threads for sample in samples),
    }


def package_versions() -> Dict[str, str]:
    result = {"python": sys.version.split()[0], "numpy": np.__version__}
    for module_name in ("onnxruntime", "sherpa_onnx", "soundfile", "scipy"):
        try:
            module = __import__(module_name)
            result[module_name] = str(getattr(module, "__version__", "unknown"))
        except ImportError:
            result[module_name] = "missing"
    return result


def create_separator(path: Path, threads: int) -> Tuple[Any, float, float]:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    created_at = time.perf_counter()
    session = ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    create_ms = (time.perf_counter() - created_at) * 1000.0
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    warmed_at = time.perf_counter()
    warm = session.run(
        [output_name], {input_name: np.zeros((1, CHUNK_SAMPLES), dtype=np.float32)}
    )[0]
    warm_ms = (time.perf_counter() - warmed_at) * 1000.0
    if np.asarray(warm).shape != (1, 2, CHUNK_SAMPLES):
        raise RuntimeError(f"separator warmup returned unexpected shape: {np.asarray(warm).shape}")
    return session, create_ms, warm_ms


def write_memory_csv(path: Path, samples: Iterable[MemorySample]) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MemorySample.__annotations__))
        writer.writeheader()
        for sample in samples:
            writer.writerow(asdict(sample))


def main() -> int:
    args = parse_args()
    args.case_dir = args.case_dir.expanduser().resolve()
    args.speaker_model = args.speaker_model.expanduser().resolve()
    args.asr_model_dir = args.asr_model_dir.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.input_hash_manifest = args.input_hash_manifest.expanduser().resolve()
    if args.separator_model is not None:
        args.separator_model = args.separator_model.expanduser().resolve()
    ensure_output_dir(args.output_dir)

    cases = require_inputs(args.case_dir, include_negative=not args.skip_negative)
    for model in (args.speaker_model,):
        if not model.is_file():
            raise FileNotFoundError(model)
    if args.mode == "full" and not args.separator_model.is_file():
        raise FileNotFoundError(args.separator_model)
    asr_artifacts = asr_model_artifacts(args.asr_model_dir)
    selected_filenames = list(ENROLLMENT_NAMES) + [path.name for _, path, _ in cases]
    verify_input_hashes(args.case_dir, args.input_hash_manifest, selected_filenames)
    require_sha256(args.speaker_model, EXPECTED_SPEAKER_SHA256, "ERes2Net")
    if args.separator_model is not None:
        require_sha256(args.separator_model, EXPECTED_SEPARATOR_SHA256, "Conv-TasNet")
    for artifact in asr_artifacts:
        require_sha256(
            Path(artifact["path"]), EXPECTED_ASR_SHA256[artifact["name"]], artifact["name"]
        )

    from ts_asr import asr_decode_full_segment, build_recognizer, build_speaker, enroll, load_audio_mono16k

    sampler = ProcSampler(args.sample_interval)
    sampler.start()
    started_at = time.perf_counter()
    failures: List[str] = []
    case_results: List[Dict[str, Any]] = []
    separator_session: Any = None
    separator_create_ms: Optional[float] = None
    separator_warm_ms: Optional[float] = None
    fatal: Optional[str] = None

    try:
        extractor = build_speaker(
            args.speaker_model, num_threads=args.speaker_threads, provider="cpu"
        )
        enrollment_audio = [load_audio_mono16k(args.case_dir / name)[0] for name in ENROLLMENT_NAMES]
        target_embedding = enroll(
            extractor, [(samples, SAMPLE_RATE) for samples in enrollment_audio]
        )
        recognizer = build_recognizer(
            args.asr_model_dir,
            num_threads=args.asr_threads,
            provider="cpu",
            enable_endpoint_detection=True,
        )
        if args.mode == "full":
            separator_session, separator_create_ms, separator_warm_ms = create_separator(
                args.separator_model, args.separator_threads
            )

        for cycle in range(args.cycles):
            for case_name, path, expectation in cases:
                samples, original_sample_rate = load_audio_mono16k(path)
                case_started = time.perf_counter()
                if args.mode == "full":
                    enhanced, detail = run_rescue(
                        separator_session, extractor, target_embedding, samples, args.threshold
                    )
                    rescue_ms = (time.perf_counter() - case_started) * 1000.0
                else:
                    enhanced = samples
                    detail = {
                        "starts": [],
                        "selected": [],
                        "score0": [],
                        "score1": [],
                        "inference_ms": [],
                        "speaker_ms": [],
                    }
                    rescue_ms = 0.0
                asr_started = time.perf_counter()
                text = asr_decode_full_segment(recognizer, enhanced, SAMPLE_RATE)
                asr_ms = (time.perf_counter() - asr_started) * 1000.0
                elapsed_ms = (time.perf_counter() - case_started) * 1000.0

                if args.mode == "full":
                    gate_passed, gate_detail = case_gate(expectation, text, detail["selected"])
                else:
                    gate_passed, gate_detail = True, "baseline-resource-only"
                if not gate_passed:
                    failures.append(f"cycle {cycle} {case_name}: {gate_detail}")
                if args.write_enhanced_wav and args.mode == "full":
                    import soundfile as sf

                    sf.write(
                        str(args.output_dir / f"cycle-{cycle:03d}-{case_name}-enhanced.wav"),
                        enhanced,
                        SAMPLE_RATE,
                        subtype="PCM_16",
                    )
                case_results.append(
                    {
                        "cycle": cycle,
                        "case": case_name,
                        "expectation": expectation,
                        "status": "PASS" if gate_passed else "FAIL",
                        "detail": gate_detail,
                        "source": str(path),
                        "source_sha256": sha256(path),
                        "original_sample_rate": original_sample_rate,
                        "duration_seconds": round(len(samples) / SAMPLE_RATE, 6),
                        "text": text,
                        "rescue_ms": round(rescue_ms, 3),
                        "asr_ms": round(asr_ms, 3),
                        "elapsed_ms": round(elapsed_ms, 3),
                        "full_chain_rtf": round(elapsed_ms / 1000.0 / (len(samples) / SAMPLE_RATE), 6),
                        "starts": detail["starts"],
                        "selected": detail["selected"],
                        "score0": [round(value, 6) for value in detail["score0"]],
                        "score1": [round(value, 6) for value in detail["score1"]],
                        "inference_ms": [round(value, 3) for value in detail["inference_ms"]],
                        "speaker_ms": [round(value, 3) for value in detail["speaker_ms"]],
                    }
                )
    except Exception as error:
        fatal = f"{type(error).__name__}: {error}"
        failures.append(fatal)
    finally:
        if args.post_observe_seconds:
            time.sleep(args.post_observe_seconds)
        sampler.stop()

    inference_rtf = [
        value / 2000.0
        for case in case_results
        for value in case["inference_ms"]
    ]
    p95_separator_rtf = (
        nearest_rank_percentile(inference_rtf, 0.95) if inference_rtf else None
    )
    performance_status = "INCONCLUSIVE" if fatal is not None else "PASS"
    if fatal is None and args.mode == "full" and (
        p95_separator_rtf is None or p95_separator_rtf >= args.max_separator_p95_rtf
    ):
        performance_status = "FAIL"
        failures.append("separator p95 RTF exceeded threshold")

    memory = memory_summary(sampler.samples)
    baseline_peak: Optional[float] = None
    peak_delta: Optional[float] = None
    memory_gate = "INCONCLUSIVE"
    if args.baseline_report is not None:
        try:
            baseline = json.loads(args.baseline_report.expanduser().read_text(encoding="utf-8"))
            baseline_peak = float(baseline["memory"]["peak_rss_mb"])
            peak_delta = float(memory["peak_rss_mb"]) - baseline_peak
            memory_gate = "PASS" if peak_delta < args.max_peak_delta_mb else "FAIL"
            if memory_gate == "FAIL":
                failures.append("peak RSS delta exceeded threshold")
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            memory_gate = "FAIL"
            failures.append(f"invalid baseline report: {error}")
    elif args.mode == "baseline":
        memory_gate = "PASS"

    if args.mode == "baseline":
        overall = "PASS" if not failures else "FAIL"
    elif failures:
        overall = "FAIL"
    elif args.skip_negative or memory_gate == "INCONCLUSIVE":
        overall = "INCONCLUSIVE"
    else:
        overall = "PASS"

    report = {
        "schema_version": 1,
        "overall_status": overall,
        "mode": args.mode,
        "created_at_epoch_seconds": time.time(),
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "packages": package_versions(),
        },
        "configuration": {
            "cycles": args.cycles,
            "sample_rate": SAMPLE_RATE,
            "chunk_samples": CHUNK_SAMPLES,
            "overlap_samples": OVERLAP_SAMPLES,
            "hop_samples": HOP_SAMPLES,
            "threshold": args.threshold,
            "separator_threads": args.separator_threads,
            "speaker_threads": args.speaker_threads,
            "asr_threads": args.asr_threads,
            "negative_cases_skipped": args.skip_negative,
            "input_hash_manifest": str(args.input_hash_manifest),
        },
        "artifacts": {
            "separator_model": (
                {
                    "path": str(args.separator_model),
                    "sha256": sha256(args.separator_model),
                }
                if args.separator_model is not None
                else None
            ),
            "speaker_model": {
                "path": str(args.speaker_model),
                "sha256": sha256(args.speaker_model),
            },
            "asr_model_dir": str(args.asr_model_dir),
            "asr_model_files": asr_artifacts,
            "enrollment": [
                {
                    "path": str(args.case_dir / name),
                    "sha256": sha256(args.case_dir / name),
                }
                for name in ENROLLMENT_NAMES
            ],
        },
        "separator": {
            "create_ms": round(separator_create_ms, 3) if separator_create_ms is not None else None,
            "warm_ms": round(separator_warm_ms, 3) if separator_warm_ms is not None else None,
            "chunk_count": len(inference_rtf),
            "p50_rtf": round(nearest_rank_percentile(inference_rtf, 0.5), 6)
            if inference_rtf
            else None,
            "p95_rtf": round(p95_separator_rtf, 6)
            if p95_separator_rtf is not None
            else None,
            "max_rtf": round(max(inference_rtf), 6) if inference_rtf else None,
            "max_p95_rtf": args.max_separator_p95_rtf,
            "status": performance_status,
        },
        "memory": {
            **memory,
            "baseline_peak_rss_mb": baseline_peak,
            "peak_rss_delta_mb": round(peak_delta, 3) if peak_delta is not None else None,
            "max_peak_delta_mb": args.max_peak_delta_mb,
            "gate_status": memory_gate,
        },
        "lifecycle": {
            "status": "NOT_APPLICABLE",
            "detail": "Linux Python cannot prove Harmony public API isLast/onComplete/cancel contracts",
        },
        "failures": failures,
        "fatal": fatal,
        "cases": case_results,
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_memory_csv(args.output_dir / "memory.csv", sampler.samples)
    print(
        f"[{overall}] mode={args.mode} cases={len(case_results)} "
        f"separator_p95_rtf={p95_separator_rtf} peak_rss_mb={memory.get('peak_rss_mb')} "
        f"report={args.output_dir / 'report.json'}"
    )
    return 0 if overall in {"PASS", "INCONCLUSIVE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
