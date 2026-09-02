"""Pure CPU and memory metrics used by device stress runners."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import statistics
from typing import Iterable


MIN_MEMORY_SAMPLES = 6
MIN_MEMORY_OBSERVATION_SECONDS = 15.0
MIN_MEMORY_SLOPE_SECONDS = 60.0


@dataclass
class MemorySample:
    elapsed_seconds: float
    pid: int
    vm_rss_kb: int
    vm_hwm_kb: int
    vm_data_kb: int
    vm_swap_kb: int
    threads: int
    process_cpu_ticks: int = -1
    system_cpu_ticks: int = -1
    logical_cpus: int = 0


def parse_status(text: str, elapsed: float, pid: int) -> MemorySample | None:
    values: dict[str, int] = {}
    for line in text.replace("\r", "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        token = value.strip().split()[0] if value.strip() else ""
        if token.isdigit():
            values[key] = int(token)
    required = ("VmRSS", "VmHWM", "VmData", "VmSwap", "Threads")
    if not all(key in values for key in required):
        return None
    return MemorySample(
        elapsed_seconds=round(elapsed, 3),
        pid=pid,
        vm_rss_kb=values["VmRSS"],
        vm_hwm_kb=values["VmHWM"],
        vm_data_kb=values["VmData"],
        vm_swap_kb=values["VmSwap"],
        threads=values["Threads"],
    )


def parse_process_cpu_ticks(text: str) -> int | None:
    closing_paren = text.rfind(")")
    if closing_paren < 0:
        return None
    fields = text[closing_paren + 1 :].strip().split()
    # The first field after comm is process state (field 3); utime/stime are fields 14/15.
    if len(fields) <= 12:
        return None
    try:
        return int(fields[11]) + int(fields[12])
    except ValueError:
        return None


def parse_system_cpu_ticks(text: str) -> tuple[int, int] | None:
    lines = text.replace("\r", "").splitlines()
    if not lines:
        return None
    aggregate = lines[0].split()
    if not aggregate or aggregate[0] != "cpu":
        return None
    try:
        counters = [int(value) for value in aggregate[1:]]
    except ValueError:
        return None
    # Linux reports guest/guest_nice as fields 9/10, but those ticks are already
    # included in user/nice. Counting them again would inflate the denominator.
    total_ticks = sum(counters[:8])
    logical_cpus = sum(
        1
        for line in lines[1:]
        if line.split()
        and line.split()[0][3:].isdigit()
        and line.split()[0].startswith("cpu")
    )
    return (total_ticks, logical_cpus) if total_ticks >= 0 and logical_cpus > 0 else None


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def cpu_statistics(samples: list[MemorySample]) -> dict[str, object]:
    valid = [
        sample
        for sample in samples
        if sample.process_cpu_ticks >= 0
        and sample.system_cpu_ticks >= 0
        and sample.logical_cpus > 0
    ]
    intervals: list[float] = []
    for previous, current in zip(valid, valid[1:]):
        if previous.pid != current.pid or previous.logical_cpus != current.logical_cpus:
            continue
        process_delta = current.process_cpu_ticks - previous.process_cpu_ticks
        system_delta = current.system_cpu_ticks - previous.system_cpu_ticks
        if process_delta < 0 or system_delta <= 0:
            continue
        intervals.append(process_delta / system_delta * current.logical_cpus * 100.0)
    if len(valid) < 2 or not intervals:
        return {
            "status": "INCONCLUSIVE",
            "reason": "fewer than two comparable CPU samples",
            "sample_count": len(valid),
        }
    first = valid[0]
    last = valid[-1]
    process_delta = last.process_cpu_ticks - first.process_cpu_ticks
    system_delta = last.system_cpu_ticks - first.system_cpu_ticks
    if process_delta < 0 or system_delta <= 0 or first.pid != last.pid:
        return {
            "status": "INCONCLUSIVE",
            "reason": "CPU counters were not monotonic for one process",
            "sample_count": len(valid),
        }
    logical_cpus = last.logical_cpus
    mean_single_core = process_delta / system_delta * logical_cpus * 100.0
    return {
        "status": "MEASURED",
        "sample_count": len(valid),
        "interval_count": len(intervals),
        "observation_seconds": round(last.elapsed_seconds - first.elapsed_seconds, 3),
        "logical_cpus": logical_cpus,
        "mean_single_core_equivalent_percent": round(mean_single_core, 3),
        "p50_single_core_equivalent_percent": round(percentile(intervals, 0.50), 3),
        "p95_single_core_equivalent_percent": round(percentile(intervals, 0.95), 3),
        "peak_single_core_equivalent_percent": round(max(intervals), 3),
        "mean_device_capacity_percent": round(mean_single_core / logical_cpus, 3),
        "p50_device_capacity_percent": round(percentile(intervals, 0.50) / logical_cpus, 3),
        "p95_device_capacity_percent": round(percentile(intervals, 0.95) / logical_cpus, 3),
        "peak_device_capacity_percent": round(max(intervals) / logical_cpus, 3),
    }


def median_window(values: list[int], from_start: bool) -> float:
    width = max(2, math.ceil(len(values) * 0.2))
    window = values[:width] if from_start else values[-width:]
    return statistics.median(window)


def memory_verdict(
    samples: list[MemorySample], max_growth_mb: float, max_thread_growth: int
) -> dict[str, object]:
    if len(samples) < MIN_MEMORY_SAMPLES:
        return {
            "status": "INCONCLUSIVE",
            "reason": f"fewer than {MIN_MEMORY_SAMPLES} process samples",
            "sample_count": len(samples),
        }
    observation_seconds = samples[-1].elapsed_seconds - samples[0].elapsed_seconds
    if observation_seconds < MIN_MEMORY_OBSERVATION_SECONDS:
        return {
            "status": "INCONCLUSIVE",
            "reason": f"observation shorter than {MIN_MEMORY_OBSERVATION_SECONDS:.0f}s",
            "sample_count": len(samples),
            "observation_seconds": round(observation_seconds, 3),
        }
    warmup = max(1, len(samples) // 5)
    stable = samples[warmup:]
    rss = [sample.vm_rss_kb for sample in stable]
    data = [sample.vm_data_kb for sample in stable]
    threads = [sample.threads for sample in stable]
    elapsed = [sample.elapsed_seconds for sample in stable]
    head_rss = median_window(rss, True)
    tail_rss = median_window(rss, False)
    growth_mb = (tail_rss - head_rss) / 1024.0
    head_data = median_window(data, True)
    tail_data = median_window(data, False)
    head_threads = median_window(threads, True)
    tail_threads = median_window(threads, False)
    thread_growth = tail_threads - head_threads
    mean_elapsed = statistics.mean(elapsed)
    mean_rss = statistics.mean(rss)
    slope_denominator = sum((value - mean_elapsed) ** 2 for value in elapsed)
    rss_slope_mb_per_minute: float | None = None
    if observation_seconds >= MIN_MEMORY_SLOPE_SECONDS and slope_denominator > 0:
        rss_slope_kb_per_second = sum(
            (x - mean_elapsed) * (y - mean_rss) for x, y in zip(elapsed, rss)
        ) / slope_denominator
        rss_slope_mb_per_minute = rss_slope_kb_per_second * 60.0 / 1024.0
    third_medians: list[float] = []
    for index in range(3):
        start = round(index * len(rss) / 3)
        end = round((index + 1) * len(rss) / 3)
        third_medians.append(round(statistics.median(rss[start:end]) / 1024.0, 3))
    status = "PASS" if growth_mb <= max_growth_mb and thread_growth <= max_thread_growth else "FAIL"
    return {
        "status": status,
        "sample_count": len(samples),
        "observation_seconds": round(observation_seconds, 3),
        "warmup_samples_excluded": warmup,
        "head_rss_mb": round(head_rss / 1024.0, 3),
        "tail_rss_mb": round(tail_rss / 1024.0, 3),
        "rss_growth_mb": round(growth_mb, 3),
        "rss_slope_mb_per_minute": (
            round(rss_slope_mb_per_minute, 3) if rss_slope_mb_per_minute is not None else None
        ),
        "rss_third_medians_mb": third_medians,
        "peak_rss_mb": round(max(sample.vm_rss_kb for sample in samples) / 1024.0, 3),
        "peak_hwm_mb": round(max(sample.vm_hwm_kb for sample in samples) / 1024.0, 3),
        "head_vm_data_mb": round(head_data / 1024.0, 3),
        "tail_vm_data_mb": round(tail_data / 1024.0, 3),
        "vm_data_growth_mb": round((tail_data - head_data) / 1024.0, 3),
        "peak_swap_mb": round(max(sample.vm_swap_kb for sample in samples) / 1024.0, 3),
        "head_threads": head_threads,
        "tail_threads": tail_threads,
        "thread_growth": thread_growth,
        "max_rss_growth_mb": max_growth_mb,
        "max_thread_growth": max_thread_growth,
    }


def write_samples(path: Path, samples: Iterable[MemorySample]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MemorySample.__annotations__))
        writer.writeheader()
        for sample in samples:
            writer.writerow(asdict(sample))
