#!/usr/bin/env python3
"""Measure cold Harmony Dingqiao ASR async engine creation and enforce baseline gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
PROJECT_ROOT = REPO_ROOT / "delivery" / "harmony-dingqiao"
HAP = (
    PROJECT_ROOT
    / "samples/dingqiao-demo/entry/build/default/outputs/default/dingqiao_demo-default-signed.hap"
)
PACKED_MANIFEST = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/resources/rawfile/amphion-models/manifest.json"
)
NATIVE_LIBRARY = REPO_ROOT / (
    "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so"
)
HAP_MANIFEST_MEMBER = "resources/rawfile/amphion-models/manifest.json"
HAP_NATIVE_MEMBER = "libs/arm64-v8a/libsherpa-onnx-c-api.so"
BUNDLE = "com.amphion.dingqiao.harmony.demo"
MODULE = "dingqiao_demo"
ABILITY = "EntryAbility"
REMOTE_RESULT_PREFIX = "/data/storage/el2/base/files/asr-loadbench"
POOL_HIT_CREATES = 3
DEFAULT_WARMUP_RUNS = 2
DEFAULT_ITERATIONS = 10
DEFAULT_MIN_P50_IMPROVEMENT_PERCENT = 20.0
DEFAULT_MAX_P95_REGRESSION_PERCENT = 3.0
PROCESS_STOP_TIMEOUT_SECONDS = 10.0


class LoadBenchFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessSample:
    run_id: str
    cold_ms: int
    pool_hit_ms: list[int]
    num_threads: int
    warmup_samples: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Force-stop/start the Harmony demo for each cold ASR process sample, "
            "measuring createEngineAsync invocation-to-callback wall time and three pool hits."
        )
    )
    parser.add_argument("--warmup-runs", type=int, default=DEFAULT_WARMUP_RUNS)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse the local signed HAP, but still verify and install that exact HAP.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Previous report JSON. Enables the default p50/p95 performance gates.",
    )
    parser.add_argument(
        "--min-p50-improvement-percent",
        type=float,
        default=DEFAULT_MIN_P50_IMPROVEMENT_PERCENT,
    )
    parser.add_argument(
        "--max-p95-regression-percent",
        type=float,
        default=DEFAULT_MAX_P95_REGRESSION_PERCENT,
    )
    parser.add_argument("--timeout", type=float, default=90.0, help="Per-process timeout in seconds.")
    parser.add_argument("--poll-interval", type=float, default=0.25, help=argparse.SUPPRESS)
    parser.add_argument("--device", default="", help="HDC target; auto-selects a sole device.")
    parser.add_argument("--output", type=Path, help="Report JSON path.")
    args = parser.parse_args(argv)
    if args.warmup_runs < 0:
        parser.error("--warmup-runs must be non-negative")
    if args.iterations <= 0:
        parser.error("--iterations must be positive")
    if args.timeout <= 0 or args.poll_interval <= 0:
        parser.error("--timeout and --poll-interval must be positive")
    if args.min_p50_improvement_percent < 0 or args.max_p95_regression_percent < 0:
        parser.error("performance gate percentages must be non-negative")
    return args


def run(
    command: list[str], *, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


class Hdc:
    def __init__(self, executable: Path, target: str):
        self.executable = executable
        self.target = target

    def command(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(self.executable), "-t", self.target, *args], check=check)

    def shell(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.command("shell", *args, check=check)

    def app_recv(self, remote: str, local: Path) -> bool:
        result = self.command("file", "recv", "-b", BUNDLE, remote, str(local), check=False)
        output = result.stdout + result.stderr
        return result.returncode == 0 and "[Fail]" not in output and local.is_file()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise LoadBenchFailure(f"missing benchmark artifact: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def model_source_hashes_from_manifest(manifest: object) -> dict[str, str]:
    if not isinstance(manifest, dict) or manifest.get("manifest_version") not in (1, 2):
        raise LoadBenchFailure("HAP model manifest version must be 1 or 2")
    version = int(manifest["manifest_version"])
    bundles = manifest.get("bundles")
    if not isinstance(bundles, dict):
        raise LoadBenchFailure("HAP model manifest is missing bundles")
    specifications = {
        "encoder": ("zh-en/v1", ("encoder.int8.ort", "encoder.int8.onnx")),
        "decoder": ("zh-en/v1", ("decoder.ort", "decoder.int8.ort", "decoder.int8.onnx", "decoder.onnx")),
        "joiner": ("zh-en/v1", ("joiner.int8.ort", "joiner.int8.onnx")),
        "tokens": ("zh-en/v1", ("tokens.txt",)),
        "bbpe_vocab": ("zh-en/v1", ("bbpe.vocab",)),
        "punctuation": ("punct-zhen/v1", ("model.int8.ort", "model.int8.onnx")),
    }
    hashes: dict[str, str] = {}
    for logical_name, (bundle_name, accepted_names) in specifications.items():
        entries = bundles.get(bundle_name)
        if not isinstance(entries, list):
            raise LoadBenchFailure(f"HAP model manifest is missing {bundle_name}")
        matches = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("name") in accepted_names
        ]
        if len(matches) != 1:
            raise LoadBenchFailure(f"HAP model manifest has invalid {logical_name} entry")
        digest_key = "source_sha256" if version == 2 else "sha256"
        digest = matches[0].get(digest_key)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.lower())
        ):
            raise LoadBenchFailure(f"HAP model manifest has invalid {logical_name} SHA-256")
        hashes[logical_name] = digest.lower()
    return hashes


def read_hap_artifacts() -> tuple[bytes, bytes, dict[str, str]]:
    if not HAP.is_file():
        raise LoadBenchFailure(f"missing benchmark HAP: {HAP}")
    try:
        with zipfile.ZipFile(HAP) as package:
            manifest_bytes = package.read(HAP_MANIFEST_MEMBER)
            native_bytes = package.read(HAP_NATIVE_MEMBER)
    except (KeyError, OSError, zipfile.BadZipFile) as error:
        raise LoadBenchFailure(f"cannot inspect benchmark HAP: {error}") from error
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LoadBenchFailure("HAP model manifest is not valid UTF-8 JSON") from error

    local_manifest = PACKED_MANIFEST.read_bytes() if PACKED_MANIFEST.is_file() else b""
    if manifest_bytes != local_manifest:
        raise LoadBenchFailure("HAP model manifest differs from the packed local manifest")
    if sha256_bytes(native_bytes) != sha256_file(NATIVE_LIBRARY):
        raise LoadBenchFailure("HAP native library differs from the packaged local library")
    return manifest_bytes, native_bytes, model_source_hashes_from_manifest(manifest)


def read_device_build(hdc: Hdc) -> str:
    values: list[str] = []
    for parameter in ("const.ohos.fullname", "const.product.software.version"):
        result = hdc.shell("param", "get", parameter, check=False)
        value = result.stdout.replace("\r", "").strip()
        if result.returncode != 0 or not value:
            raise LoadBenchFailure(f"cannot read device build parameter: {parameter}")
        values.append(value)
    return " | ".join(values)


def comparison_identity(
    device: str,
    device_build: str,
    model_source_sha256: dict[str, str],
    warmup_runs: int,
    iterations: int,
    num_threads: int,
    warmup_samples: int,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "device": device,
        "device_build": device_build,
        "profile": {
            "api": "SpeechRecognizeSdk.createEngineAsync",
            "language": "zh-CN",
            "punctuation_requested": True,
            "num_threads": num_threads,
            "warmup_samples": warmup_samples,
            "police_hotword_profile": "defaults-v1",
            "process_isolation": "force-stop",
            "preconditioning": "install-smoke-then-process-warmups",
            "warmup_runs": warmup_runs,
            "iterations": iterations,
            "pool_hit_creates_per_process": POOL_HIT_CREATES,
        },
        "model_source_sha256": model_source_sha256,
    }


def artifact_fingerprints(manifest_bytes: bytes, native_bytes: bytes) -> dict[str, object]:
    commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    dirty = bool(run(["git", "status", "--porcelain"], check=True).stdout.strip())
    return {
        "git_commit": commit,
        "git_worktree_dirty": dirty,
        "hap_sha256": sha256_file(HAP),
        "model_manifest_sha256": sha256_bytes(manifest_bytes),
        "native_library_sha256": sha256_bytes(native_bytes),
    }


def locate_hdc() -> Path:
    deveco = Path(os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents"))
    hdc = deveco / "sdk" / "default" / "openharmony" / "toolchains" / "hdc"
    if not hdc.is_file():
        raise LoadBenchFailure(f"missing HDC: {hdc}")
    return hdc


def select_target(hdc: Path, requested: str) -> str:
    if requested:
        return requested
    result = run([str(hdc), "list", "targets"])
    targets = [line.strip() for line in result.stdout.replace("\r", "").splitlines() if line.strip()]
    if len(targets) != 1:
        raise LoadBenchFailure(f"expected exactly one connected HDC target, found {len(targets)}")
    return targets[0]


def build_install(device: str, skip_build: bool) -> None:
    command = [str(SCRIPT_DIR / "build_install_smoke.sh"), "--device", device]
    if skip_build:
        command.append("--skip-build")
    result = run(
        command,
        check=False,
        capture=False,
    )
    if result.returncode != 0:
        raise LoadBenchFailure("Harmony demo build/install smoke test failed")


def parse_device_result(text: str, expected_run_id: str) -> ProcessSample | None:
    if not text.endswith("\n"):
        return None
    for line in text.splitlines():
        parts = line.split("|")
        if not parts or parts[0] != "LOADBENCH":
            continue
        fields = {
            key: value
            for key, separator, value in (part.partition("=") for part in parts[1:])
            if separator
        }
        if fields.get("runId") != expected_run_id:
            continue
        if fields.get("version") != "2":
            raise LoadBenchFailure("unsupported device loadbench result version")
        if fields.get("api") != "createEngineAsync":
            raise LoadBenchFailure("device loadbench did not measure createEngineAsync")
        if fields.get("status") != "PASS":
            detail = fields.get("fatal", "unknown-device-failure")
            raise LoadBenchFailure(f"device loadbench failed: {detail}")
        if fields.get("punctuationRequested") != "true":
            raise LoadBenchFailure("device loadbench did not request punctuation")
        if fields.get("punctuationLoaded") != "true":
            raise LoadBenchFailure("device loadbench did not load punctuation")
        try:
            cold_ms = int(fields["coldMs"])
            pool_hit_ms = [int(value) for value in fields["poolHitMs"].split(",")]
            num_threads = int(fields["numThreads"])
            warmup_samples = int(fields["warmupSamples"])
        except (KeyError, ValueError) as error:
            raise LoadBenchFailure("malformed device timing result") from error
        if (
            cold_ms < 0
            or len(pool_hit_ms) != POOL_HIT_CREATES
            or any(value < 0 for value in pool_hit_ms)
            or num_threads <= 0
            or warmup_samples < 0
        ):
            raise LoadBenchFailure("device timing result has invalid sample counts or values")
        return ProcessSample(expected_run_id, cold_ms, pool_hit_ms, num_threads, warmup_samples)
    return None


def percentile(values: Sequence[int | float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if quantile < 0.0 or quantile > 1.0:
        raise ValueError("quantile must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * quantile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def timing_statistics(values: Sequence[int | float]) -> dict[str, int | float]:
    if not values:
        raise ValueError("timing statistics require at least one value")
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "p50": round(percentile(values, 0.50), 3),
        "p90": round(percentile(values, 0.90), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def extract_baseline_cold_statistics(report: object) -> dict[str, float]:
    if not isinstance(report, dict):
        raise LoadBenchFailure("baseline report root must be an object")
    statistics_report = report.get("statistics")
    if not isinstance(statistics_report, dict):
        raise LoadBenchFailure("baseline is missing statistics.cold_create_engine_async_ms p50/p95")
    cold = statistics_report.get("cold_create_engine_async_ms")
    if not isinstance(cold, dict):
        raise LoadBenchFailure("baseline is missing statistics.cold_create_engine_async_ms p50/p95")
    try:
        p50 = float(cold["p50"])
        p95 = float(cold["p95"])
    except (KeyError, TypeError, ValueError) as error:
        raise LoadBenchFailure("baseline is missing statistics.cold_create_engine_async_ms p50/p95") from error
    if not math.isfinite(p50) or not math.isfinite(p95) or p50 <= 0 or p95 <= 0:
        raise LoadBenchFailure("baseline p50/p95 must be finite and positive")
    return {"p50": p50, "p95": p95}


def validate_baseline_comparability(
    report: object, expected_identity: dict[str, object]
) -> None:
    if not isinstance(report, dict):
        raise LoadBenchFailure("baseline report root must be an object")
    actual_identity = report.get("comparison_identity")
    if not isinstance(actual_identity, dict):
        raise LoadBenchFailure("baseline is missing comparison_identity")
    if actual_identity != expected_identity:
        mismatched = sorted(
            key
            for key in set(actual_identity) | set(expected_identity)
            if actual_identity.get(key) != expected_identity.get(key)
        )
        raise LoadBenchFailure(
            "baseline comparison_identity mismatch: " + ", ".join(mismatched)
        )


def evaluate_gates(
    current: dict[str, int | float],
    baseline: dict[str, float],
    min_p50_improvement_percent: float = DEFAULT_MIN_P50_IMPROVEMENT_PERCENT,
    max_p95_regression_percent: float = DEFAULT_MAX_P95_REGRESSION_PERCENT,
) -> dict[str, object]:
    current_p50 = float(current["p50"])
    current_p95 = float(current["p95"])
    p50_improvement = (baseline["p50"] - current_p50) / baseline["p50"] * 100.0
    p95_regression = (current_p95 - baseline["p95"]) / baseline["p95"] * 100.0
    p50_pass = p50_improvement + 1e-9 >= min_p50_improvement_percent
    p95_pass = p95_regression <= max_p95_regression_percent + 1e-9
    return {
        "status": "PASS" if p50_pass and p95_pass else "FAIL",
        "p50": {
            "status": "PASS" if p50_pass else "FAIL",
            "baseline_ms": baseline["p50"],
            "current_ms": current_p50,
            "improvement_percent": round(p50_improvement, 3),
            "minimum_improvement_percent": min_p50_improvement_percent,
        },
        "p95": {
            "status": "PASS" if p95_pass else "FAIL",
            "baseline_ms": baseline["p95"],
            "current_ms": current_p95,
            "regression_percent": round(p95_regression, 3),
            "maximum_regression_percent": max_p95_regression_percent,
        },
    }


def default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "build" / "model-load-bench" / f"report-{timestamp}.json"


def new_run_id(phase: str, index: int) -> str:
    entropy = hashlib.sha256(f"{time.time_ns()}-{phase}-{index}".encode()).hexdigest()[:8]
    return f"{phase}-{index:03d}-{entropy}"


def force_stop_and_wait(
    hdc: Hdc,
    timeout: float = PROCESS_STOP_TIMEOUT_SECONDS,
    poll_interval: float = 0.05,
) -> None:
    hdc.shell("aa", "force-stop", BUNDLE, check=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = hdc.shell("pidof", BUNDLE, check=False)
        pids = [token for token in result.stdout.replace("\r", "").split() if token.isdigit()]
        if not pids:
            return
        time.sleep(poll_interval)
    raise LoadBenchFailure(f"demo process did not exit within {timeout:g}s after force-stop")


def run_process_sample(
    hdc: Hdc,
    run_id: str,
    local_result: Path,
    timeout: float,
    poll_interval: float,
) -> ProcessSample:
    remote_result = f"{REMOTE_RESULT_PREFIX}-{run_id}.txt"
    local_result.unlink(missing_ok=True)
    # A failed/asynchronous force-stop would turn this into a process-pool hit and invalidate the
    # headline cold number. Require pidof to be empty before every launch.
    force_stop_and_wait(hdc)
    start = hdc.shell(
        "aa",
        "start",
        "-a",
        ABILITY,
        "-b",
        BUNDLE,
        "-m",
        MODULE,
        "--ps",
        "loadbench",
        "true",
        "--ps",
        "loadbenchRunId",
        run_id,
        "--ps",
        "loadbenchResult",
        remote_result,
        check=False,
    )
    output = start.stdout + start.stderr
    if start.returncode != 0 or "error" in output.lower():
        raise LoadBenchFailure(f"failed to start loadbench ability: {output.strip()}")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if hdc.app_recv(remote_result, local_result):
            try:
                sample = parse_device_result(local_result.read_text(encoding="ascii"), run_id)
            except (OSError, UnicodeError):
                sample = None
            if sample is not None:
                return sample
            local_result.unlink(missing_ok=True)
        time.sleep(poll_interval)
    raise LoadBenchFailure(f"timed out after {timeout:g}s waiting for process sample {run_id}")


def load_baseline(
    path: Path, expected_identity: dict[str, object]
) -> dict[str, float]:
    try:
        report = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LoadBenchFailure(f"cannot read baseline report {path}: {error}") from error
    validate_baseline_comparability(report, expected_identity)
    return extract_baseline_cold_statistics(report)


def run_benchmark(args: argparse.Namespace) -> tuple[Path, str]:
    hdc_path = locate_hdc()
    device = select_target(hdc_path, args.device)
    hdc = Hdc(hdc_path, device)
    output = (args.output or default_output_path()).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_result = output.with_suffix(".device-result.tmp")

    action = "installing the verified local" if args.skip_build else "building and installing the"
    print(f"[INFO] {action} Harmony demo HAP")
    build_install(device, args.skip_build)
    manifest_bytes, native_bytes, model_source_sha256 = read_hap_artifacts()
    device_build = read_device_build(hdc)
    artifacts = artifact_fingerprints(manifest_bytes, native_bytes)

    warmup_samples: list[ProcessSample] = []
    measured_samples: list[ProcessSample] = []
    try:
        total = args.warmup_runs + args.iterations
        for ordinal in range(total):
            warmup = ordinal < args.warmup_runs
            phase = "warmup" if warmup else "measure"
            index = ordinal + 1 if warmup else ordinal - args.warmup_runs + 1
            run_id = new_run_id(phase, index)
            print(f"[INFO] {phase} {index}/{args.warmup_runs if warmup else args.iterations}: {run_id}")
            sample = run_process_sample(hdc, run_id, temporary_result, args.timeout, args.poll_interval)
            print(
                f"[INFO] cold={sample.cold_ms} ms "
                f"poolHits={','.join(str(value) for value in sample.pool_hit_ms)} ms"
            )
            (warmup_samples if warmup else measured_samples).append(sample)
    finally:
        temporary_result.unlink(missing_ok=True)
        force_stop_and_wait(hdc)

    cold_values = [sample.cold_ms for sample in measured_samples]
    pool_values = [value for sample in measured_samples for value in sample.pool_hit_ms]
    runtime_profiles = {
        (sample.num_threads, sample.warmup_samples)
        for sample in warmup_samples + measured_samples
    }
    if len(runtime_profiles) != 1:
        raise LoadBenchFailure("device loadbench samples reported inconsistent runtime profiles")
    num_threads, eager_warmup_samples = runtime_profiles.pop()
    identity = comparison_identity(
        device,
        device_build,
        model_source_sha256,
        args.warmup_runs,
        args.iterations,
        num_threads,
        eager_warmup_samples,
    )
    baseline_statistics = (
        load_baseline(args.baseline, identity) if args.baseline is not None else None
    )
    cold_statistics = timing_statistics(cold_values)
    statistics_report = {
        "cold_create_engine_async_ms": cold_statistics,
        "pool_hit_create_engine_async_ms": timing_statistics(pool_values),
        "pool_hit_by_position_ms": [
            timing_statistics([sample.pool_hit_ms[index] for sample in measured_samples])
            for index in range(POOL_HIT_CREATES)
        ],
    }

    baseline_record: dict[str, object] | None = None
    if args.baseline is None:
        gates: dict[str, object] = {
            "status": "NOT_EVALUATED",
            "reason": "--baseline was not provided",
            "minimum_p50_improvement_percent": args.min_p50_improvement_percent,
            "maximum_p95_regression_percent": args.max_p95_regression_percent,
        }
    else:
        if baseline_statistics is None:
            raise AssertionError("baseline statistics were not loaded")
        baseline_record = {
            "path": str(args.baseline.expanduser().resolve()),
            "cold_create_engine_async_ms": baseline_statistics,
        }
        gates = evaluate_gates(
            cold_statistics,
            baseline_statistics,
            args.min_p50_improvement_percent,
            args.max_p95_regression_percent,
        )

    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "device": device,
        "comparison_identity": identity,
        "artifacts": artifacts,
        "configuration": {
            "warmup_runs": args.warmup_runs,
            "iterations": args.iterations,
            "pool_hit_creates_per_process": POOL_HIT_CREATES,
            "punctuation_requested": True,
            "api": "SpeechRecognizeSdk.createEngineAsync",
            "timeout_seconds": args.timeout,
        },
        "warmup_samples": [asdict(sample) for sample in warmup_samples],
        "samples": [asdict(sample) for sample in measured_samples],
        "statistics": statistics_report,
        "baseline": baseline_record,
        "gates": gates,
    }
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    gate_status = str(gates["status"])
    cold = statistics_report["cold_create_engine_async_ms"]
    print(
        f"[{gate_status}] cold createEngineAsync ms: min={cold['min']} p50={cold['p50']} "
        f"p90={cold['p90']} p95={cold['p95']} max={cold['max']}"
    )
    print(f"[INFO] report={output}")
    return output, gate_status


def main() -> int:
    try:
        _, status = run_benchmark(parse_args())
        return 1 if status == "FAIL" else 0
    except (LoadBenchFailure, subprocess.SubprocessError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
