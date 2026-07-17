#!/usr/bin/env python3
"""Run repeatable real-audio stress tests against the Harmony Dingqiao SDK."""

from __future__ import annotations

import argparse
import audioop
import csv
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
PROJECT_ROOT = REPO_ROOT / "delivery" / "harmony-dingqiao"
BUILD_IDENTITY = PROJECT_ROOT / "build" / "smoke" / "build-identity.json"
BUILD_IDENTITY_TOOL = SCRIPT_DIR / "harmony_build_identity.py"
BUNDLE = "com.amphion.dingqiao.harmony.demo"
MODULE = "dingqiao_demo"
ABILITY = "EntryAbility"
REMOTE_ROOT = "/data/storage/el2/base/files/asr-stress"
FINISH_MODES = {
    "burst", "paced", "vad-begin", "reconfigure", "recreate", "max-duration", "numeric-edge",
}
MIN_MEMORY_SAMPLES = 6
MIN_MEMORY_OBSERVATION_SECONDS = 15.0
MIN_MEMORY_SLOPE_SECONDS = 60.0


@dataclass(frozen=True)
class AudioSource:
    path: Path
    sample_rate: int
    channels: int
    sample_width: int
    frames: int
    duration_seconds: float


@dataclass
class MemorySample:
    elapsed_seconds: float
    pid: int
    vm_rss_kb: int
    vm_hwm_kb: int
    vm_data_kb: int
    vm_swap_kb: int
    threads: int


class StressFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive the Harmony ASR SDK through a headless test carrier and check its contracts."
    )
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "Downloads" / "testdata")
    parser.add_argument(
        "--mode",
        choices=(
            "burst",
            "paced",
            "vad-begin",
            "vad-begin-silence",
            "voiceprint",
            "voiceprint-fallback",
            "voiceprint-vad-begin",
            "voiceprint-vad-begin-idle",
            "cancel",
            "cancel-full",
            "recreate",
            "reconfigure",
            "max-duration",
            "edge",
            "reentrant",
            "start-cancel",
            "start-write",
            "start-write-reload",
            "speaker-vad-onstart",
            "callback-api-reentrant",
            "endpoint-reentrant",
            "user-sequence",
            "numeric-edge",
        ),
        default="burst",
    )
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument(
        "--files",
        type=int,
        default=24,
        help="Representative WAV count; 0 selects every valid WAV.",
    )
    parser.add_argument("--settle-ms", type=int, default=0)
    parser.add_argument("--pace-ms", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--post-run-observe", type=float, default=5.0)
    parser.add_argument("--max-rss-growth-mb", type=float, default=64.0)
    parser.add_argument("--max-thread-growth", type=int, default=2)
    parser.add_argument("--max-empty-final-rate", type=float, default=0.05)
    parser.add_argument("--skip-build-install", action="store_true")
    parser.add_argument("--device", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "build" / "device-stress",
    )
    args = parser.parse_args()
    if args.cycles <= 0:
        parser.error("--cycles must be positive")
    if args.files < 0:
        parser.error("--files must be non-negative")
    if args.timeout <= 0 or args.sample_interval <= 0:
        parser.error("--timeout and --sample-interval must be positive")
    if args.settle_ms < 0 or args.pace_ms < 0 or args.post_run_observe < 0:
        parser.error("timing values must be non-negative")
    return args


def run(command: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_build_identity() -> dict[str, object]:
    if not BUILD_IDENTITY.is_file():
        raise StressFailure(
            "missing Harmony build identity; build and install the current source before stress testing"
        )
    result = run(
        [sys.executable, str(BUILD_IDENTITY_TOOL), "--verify", str(BUILD_IDENTITY)],
        check=False,
    )
    if result.returncode != 0:
        raise StressFailure((result.stdout + result.stderr).strip())
    try:
        identity = json.loads(BUILD_IDENTITY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StressFailure(f"cannot read Harmony build identity: {error}") from error
    if not isinstance(identity, dict):
        raise StressFailure("Harmony build identity must be a JSON object")
    return identity


class Hdc:
    def __init__(self, executable: Path, target: str):
        self.executable = executable
        self.target = target

    def command(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(self.executable), "-t", self.target, *args], check=check)

    def shell(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.command("shell", *args, check=check)

    def app_send(self, local: Path, remote: str) -> None:
        result = self.command("file", "send", "-b", BUNDLE, str(local), remote, check=False)
        if result.returncode != 0 or "[Fail]" in result.stdout + result.stderr:
            raise StressFailure(f"failed to send stress payload: {(result.stdout + result.stderr).strip()}")

    def app_recv(self, remote: str, local: Path) -> bool:
        result = self.command("file", "recv", "-b", BUNDLE, remote, str(local), check=False)
        return result.returncode == 0 and "[Fail]" not in result.stdout + result.stderr and local.is_file()


def locate_hdc() -> Path:
    deveco = Path(os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents"))
    hdc = deveco / "sdk" / "default" / "openharmony" / "toolchains" / "hdc"
    if not hdc.is_file():
        raise StressFailure(f"missing HDC: {hdc}")
    return hdc


def select_target(hdc: Path, requested: str) -> str:
    if requested:
        return requested
    result = run([str(hdc), "list", "targets"])
    targets = [line.strip() for line in result.stdout.replace("\r", "").splitlines() if line.strip()]
    if len(targets) != 1:
        raise StressFailure(f"expected exactly one connected HDC target, found {len(targets)}")
    return targets[0]


def inspect_wavs(root: Path) -> list[AudioSource]:
    if not root.is_dir():
        raise StressFailure(f"audio data directory does not exist: {root}")
    sources: list[AudioSource] = []
    for path in sorted(root.rglob("*.wav")):
        if path.name.startswith("._") or "__MACOSX" in path.parts:
            continue
        try:
            with wave.open(str(path), "rb") as wav:
                if wav.getcomptype() != "NONE":
                    continue
                frames = wav.getnframes()
                sample_rate = wav.getframerate()
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
        except (EOFError, OSError, wave.Error):
            continue
        if frames <= 0 or sample_rate <= 0:
            continue
        sources.append(
            AudioSource(
                path=path,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
                frames=frames,
                duration_seconds=frames / sample_rate,
            )
        )
    if not sources:
        raise StressFailure(f"no valid PCM WAV files found under {root}")
    return sources


def quantile_pick(items: list[AudioSource], count: int) -> list[AudioSource]:
    if count >= len(items):
        return list(items)
    ordered = sorted(items, key=lambda item: (item.duration_seconds, str(item.path)))
    if count == 1:
        return [ordered[len(ordered) // 2]]
    indexes = [round(i * (len(ordered) - 1) / (count - 1)) for i in range(count)]
    return [ordered[index] for index in indexes]


def representative_sources(sources: list[AudioSource], count: int) -> list[AudioSource]:
    if count == 0 or count >= len(sources):
        return sorted(sources, key=lambda item: str(item.path))
    rates: dict[int, list[AudioSource]] = {}
    for source in sources:
        rates.setdefault(source.sample_rate, []).append(source)
    if count < len(rates):
        return quantile_pick(sources, count)

    quotas = {rate: max(1, round(count * len(group) / len(sources))) for rate, group in rates.items()}
    while sum(quotas.values()) > count:
        candidates = [rate for rate, quota in quotas.items() if quota > 1]
        quotas[max(candidates, key=lambda rate: quotas[rate])] -= 1
    while sum(quotas.values()) < count:
        rate = max(rates, key=lambda key: len(rates[key]) - quotas[key])
        quotas[rate] += 1

    picked: list[AudioSource] = []
    for rate in sorted(rates):
        picked.extend(quantile_pick(rates[rate], min(quotas[rate], len(rates[rate]))))
    return sorted(picked, key=lambda item: (item.sample_rate, item.duration_seconds, str(item.path)))


def initial_signal_level(source: AudioSource, seconds: float = 3.0) -> float:
    with wave.open(str(source.path), "rb") as wav:
        raw = wav.readframes(min(wav.getnframes(), round(wav.getframerate() * seconds)))
    if not raw:
        return 0.0
    full_scale = float((1 << (source.sample_width * 8 - 1)) - 1)
    return audioop.rms(raw, source.sample_width) / full_scale


def convert_to_pcm(source: AudioSource, destination: Path) -> int:
    if source.sample_width != 2:
        raise StressFailure(f"unsupported sample width {source.sample_width * 8} for {source.path}")
    if source.channels not in (1, 2):
        raise StressFailure(f"unsupported channel count {source.channels} for {source.path}")
    with wave.open(str(source.path), "rb") as wav:
        raw = wav.readframes(wav.getnframes())
    if source.channels == 2:
        raw = audioop.tomono(raw, 2, 0.5, 0.5)
    if source.sample_rate != 16000:
        raw, _ = audioop.ratecv(raw, 2, 1, source.sample_rate, 16000, None)
    if len(raw) % 2:
        raw = raw[:-1]
    destination.write_bytes(raw)
    return len(raw)


def prepare_payload(
    sources: list[AudioSource], payload: Path, remote_dir: str, corpus_root: Path
) -> list[dict[str, object]]:
    audio_dir = payload / "audio"
    audio_dir.mkdir(parents=True)
    manifest_lines: list[str] = []
    mapping: list[dict[str, object]] = []
    for index, source in enumerate(sources):
        corpus_id = f"{index:06d}"
        filename = f"{corpus_id}.pcm"
        pcm_path = audio_dir / filename
        output_bytes = convert_to_pcm(source, pcm_path)
        manifest_lines.append(f"{corpus_id}\t{remote_dir}/audio/{filename}")
        mapping.append(
            {
                "id": corpus_id,
                "source": str(source.path.relative_to(corpus_root)),
                "source_sha256": sha256_file(source.path),
                "sample_rate": source.sample_rate,
                "channels": source.channels,
                "sample_width": source.sample_width,
                "duration_seconds": round(source.duration_seconds, 6),
                "pcm_bytes": output_bytes,
                "pcm_sha256": sha256_file(pcm_path),
            }
        )
    (payload / "manifest.txt").write_text("\n".join(manifest_lines) + "\n", encoding="ascii")
    (payload / "corpus.json").write_text(json.dumps(mapping, ensure_ascii=True, indent=2) + "\n")
    return mapping


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


def read_process_sample(hdc: Hdc, started_at: float) -> MemorySample | None:
    pid_result = hdc.shell("pidof", BUNDLE, check=False)
    pid_tokens = pid_result.stdout.replace("\r", "").strip().split()
    if not pid_tokens or not pid_tokens[0].isdigit():
        return None
    pid = int(pid_tokens[0])
    status = hdc.shell("cat", f"/proc/{pid}/status", check=False)
    if status.returncode != 0:
        return None
    return parse_status(status.stdout, time.monotonic() - started_at, pid)


def parse_result(path: Path, run_id: str) -> tuple[dict[str, str], list[dict[str, str]]] | None:
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    summary: dict[str, str] | None = None
    cycles: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = line.split("|")
        if not parts:
            continue
        fields = {key: value for key, _, value in (part.partition("=") for part in parts[1:]) if key}
        if parts[0] == "CYCLE":
            cycles.append(fields)
        elif parts[0] == "SUMMARY" and fields.get("runId") == run_id:
            summary = fields
    return (summary, cycles) if summary is not None else None


def median_window(values: list[int], from_start: bool) -> float:
    width = max(2, math.ceil(len(values) * 0.2))
    window = values[:width] if from_start else values[-width:]
    return statistics.median(window)


def memory_verdict(samples: list[MemorySample], max_growth_mb: float, max_thread_growth: int) -> dict[str, object]:
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


def build_install(device: str) -> None:
    command = [str(SCRIPT_DIR / "build_install_smoke.sh"), "--device", device]
    result = run(command, check=False, capture=False)
    if result.returncode != 0:
        raise StressFailure("Harmony demo build/install smoke test failed")


def capture_hilog(hdc: Hdc, destination: Path) -> None:
    result = hdc.shell("hilog", "-x", check=False)
    destination.write_text(result.stdout + result.stderr, encoding="utf-8", errors="replace")


def run_stress(args: argparse.Namespace) -> Path:
    hdc_path = locate_hdc()
    device = select_target(hdc_path, args.device)
    hdc = Hdc(hdc_path, device)
    all_sources = inspect_wavs(args.data_dir.expanduser().resolve())
    selected = representative_sources(all_sources, args.files)
    if args.mode == "voiceprint-fallback":
        sources_by_name = {source.path.name: source for source in all_sources}
        required_names = ("000_enroll.wav", "001_recognize.wav")
        if any(name not in sources_by_name for name in required_names):
            raise StressFailure(
                "voiceprint-fallback requires 000_enroll.wav and 001_recognize.wav"
            )
        selected = [sources_by_name[name] for name in required_names]
    elif args.mode in ("voiceprint-vad-begin", "speaker-vad-onstart"):
        # The carrier adds 800 ms leading silence in half the cycles. Keep only sources whose own
        # first 200 ms already contain signal, so that case still places speech before vadBegin.
        # Otherwise the test would correctly time out before the source itself starts speaking.
        selected.sort(key=initial_signal_level, reverse=True)
        selected = [source for source in selected if initial_signal_level(source, 0.2) >= 0.015]
        # Runtime Speaker VAD rejects non-target speakers, so its enrollment and recognition source
        # must be identical. Verification-only mode can intentionally span several sources.
        selected = selected[:1] if args.mode == "speaker-vad-onstart" else selected[:8]
        if not selected:
            raise StressFailure(f"{args.mode} requires a source with a non-silent onset")
    elif args.mode == "voiceprint-vad-begin-idle":
        selected.sort(key=initial_signal_level, reverse=True)
        selected = selected[:1]

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    entropy = hashlib.sha256(f"{time.time_ns()}-{args.mode}".encode()).hexdigest()[:8]
    run_id = f"{timestamp}-{args.mode}-{entropy}"
    artifact_dir = args.output_root.expanduser().resolve() / run_id
    payload = artifact_dir / "payload"
    payload.mkdir(parents=True)
    remote_dir = f"{REMOTE_ROOT}/{run_id}"
    mapping = prepare_payload(selected, payload, remote_dir, args.data_dir.expanduser().resolve())
    remote_manifest = f"{remote_dir}/manifest.txt"
    remote_result = f"{remote_dir}/result.txt"
    local_result = artifact_dir / "result.txt"

    inventory = {
        "valid_wavs": len(all_sources),
        "selected_wavs": len(selected),
        "total_valid_duration_seconds": round(sum(item.duration_seconds for item in all_sources), 3),
        "selected_duration_seconds": round(sum(item.duration_seconds for item in selected), 3),
        "sample_rates": {str(rate): sum(1 for item in all_sources if item.sample_rate == rate) for rate in sorted({item.sample_rate for item in all_sources})},
    }
    (artifact_dir / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")

    print(
        f"[INFO] corpus: {inventory['valid_wavs']} valid WAVs, "
        f"{inventory['total_valid_duration_seconds'] / 3600:.2f} h; selected {len(selected)} files"
    )
    if not args.skip_build_install:
        print("[INFO] building, installing, and smoke-testing the Harmony SDK test carrier")
        build_install(device)
    build_identity = verified_build_identity()

    print(f"[INFO] sending {sum(int(item['pcm_bytes']) for item in mapping) / 1024 / 1024:.1f} MiB PCM payload")
    hdc.app_send(payload, remote_dir)
    hdc.shell("hilog", "-r", check=False)
    hdc.shell("aa", "force-stop", BUNDLE, check=False)

    start_result = hdc.shell(
        "aa", "start", "-a", ABILITY, "-b", BUNDLE, "-m", MODULE,
        "--ps", "stress", "true",
        "--ps", "stressRunId", run_id,
        "--ps", "stressManifest", remote_manifest,
        "--ps", "stressResult", remote_result,
        "--ps", "stressMode", args.mode,
        "--ps", "stressCycles", str(args.cycles),
        "--ps", "stressSettleMs", str(args.settle_ms),
        "--ps", "stressPaceMs", str(args.pace_ms),
        check=False,
    )
    if start_result.returncode != 0 or "error" in (start_result.stdout + start_result.stderr).lower():
        raise StressFailure(f"failed to start stress ability: {(start_result.stdout + start_result.stderr).strip()}")

    samples: list[MemorySample] = []
    started_at = time.monotonic()
    parsed: tuple[dict[str, str], list[dict[str, str]]] | None = None
    process_seen = False
    next_poll = started_at
    print(f"[INFO] running mode={args.mode} cycles={args.cycles}")
    while time.monotonic() - started_at < args.timeout:
        now = time.monotonic()
        if now < next_poll:
            time.sleep(min(0.1, next_poll - now))
            continue
        sample = read_process_sample(hdc, started_at)
        if sample is not None:
            process_seen = True
            samples.append(sample)
        elif process_seen:
            capture_hilog(hdc, artifact_dir / "hilog.txt")
            write_samples(artifact_dir / "memory.csv", samples)
            raise StressFailure("SDK test carrier exited before the stress summary was written")

        temporary_result = artifact_dir / "result.tmp"
        if hdc.app_recv(remote_result, temporary_result):
            candidate = parse_result(temporary_result, run_id)
            if candidate is not None:
                shutil.move(temporary_result, local_result)
                parsed = candidate
                break
        temporary_result.unlink(missing_ok=True)
        next_poll = time.monotonic() + args.sample_interval
    if parsed is None:
        capture_hilog(hdc, artifact_dir / "hilog.txt")
        write_samples(artifact_dir / "memory.csv", samples)
        raise StressFailure(f"timed out after {args.timeout}s waiting for the stress summary")

    observe_until = time.monotonic() + args.post_run_observe
    while time.monotonic() < observe_until:
        sample = read_process_sample(hdc, started_at)
        if sample is not None:
            samples.append(sample)
        time.sleep(args.sample_interval)

    capture_hilog(hdc, artifact_dir / "hilog.txt")
    write_samples(artifact_dir / "memory.csv", samples)
    app_summary, cycle_results = parsed
    memory = memory_verdict(samples, args.max_rss_growth_mb, args.max_thread_growth)
    completed = int(app_summary.get("completed", "0"))
    empty_finals = int(app_summary.get("emptyFinals", "0"))
    empty_rate = empty_finals / completed if completed else 1.0
    live_stream_counts: list[int] = []
    for cycle in cycle_results:
        try:
            live_stream_counts.append(int(cycle["liveStreams"]))
        except (KeyError, ValueError):
            continue
    nonzero_live_stream_cycles = sum(1 for count in live_stream_counts if count != 0)
    stream_status = "PASS" if len(live_stream_counts) == completed and nonzero_live_stream_cycles == 0 else "FAIL"
    empty_status = "PASS"
    if args.mode in FINISH_MODES and empty_rate > args.max_empty_final_rate:
        empty_status = "FAIL"

    overall = "PASS"
    failures: list[str] = []
    if app_summary.get("status") != "PASS":
        overall = "FAIL"
        failures.append("SDK contract checks failed")
    if memory.get("status") == "FAIL":
        overall = "FAIL"
        failures.append("RSS/thread growth exceeded threshold")
    if stream_status == "FAIL":
        overall = "FAIL"
        failures.append("native stream ownership check failed")
    if empty_status == "FAIL":
        overall = "FAIL"
        failures.append("empty-final rate exceeded threshold")

    report = {
        "run_id": run_id,
        "mode": args.mode,
        "overall_status": overall,
        "failures": failures,
        "device": device,
        "build_identity": build_identity,
        "configuration": {
            "cycles": args.cycles,
            "settle_ms": args.settle_ms,
            "pace_ms": args.pace_ms,
            "sample_interval_seconds": args.sample_interval,
            "post_run_observe_seconds": args.post_run_observe,
        },
        "inventory": inventory,
        "application": app_summary,
        "empty_finals": {
            "status": empty_status,
            "count": empty_finals,
            "rate": round(empty_rate, 6),
            "max_rate": args.max_empty_final_rate,
        },
        "native_streams": {
            "status": stream_status,
            "observed_cycles": len(live_stream_counts),
            "nonzero_cycles": nonzero_live_stream_cycles,
            "max_live_streams": max(live_stream_counts, default=0),
        },
        "memory": memory,
        "cycles": cycle_results,
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    print(
        f"[{overall}] sdk={app_summary.get('status')} memory={memory.get('status')} "
        f"emptyFinalRate={empty_rate:.3f} artifacts={artifact_dir}"
    )
    if "rss_growth_mb" in memory:
        slope = memory["rss_slope_mb_per_minute"]
        slope_text = f"{slope} MiB/min" if slope is not None else f"inconclusive (<{MIN_MEMORY_SLOPE_SECONDS:.0f}s)"
        print(
            f"[INFO] RSS head={memory['head_rss_mb']} MiB tail={memory['tail_rss_mb']} MiB "
            f"growth={memory['rss_growth_mb']} MiB peak={memory['peak_rss_mb']} MiB "
            f"slope={slope_text}"
        )
    if overall != "PASS":
        raise StressFailure("; ".join(failures))
    return artifact_dir


def main() -> int:
    try:
        run_stress(parse_args())
        return 0
    except (StressFailure, subprocess.SubprocessError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
