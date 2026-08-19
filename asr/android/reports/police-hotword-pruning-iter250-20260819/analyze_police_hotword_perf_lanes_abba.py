#!/usr/bin/env python3
"""Validate and summarize formal split-lane Android hotword ABBA evidence.

The CPU/latency lane never samples PSS/RSS.  The memory lane samples resources but its CPU and
latency numbers are diagnostic only.  Paced-input SDK RTF is also diagnostic: it has no absolute
0.8 gate. Process CPU uses the same formal p95 relative-regression gate as latency, with paired
deltas retained as supporting evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import analyze_police_hotword_create_only_abba as base


LANES = ("cpu_latency", "memory")
PROFILES = ("full", "prune_ui28")
ABBA = ("full", "prune_ui28", "prune_ui28", "full")
COUNTS = {"full": 370, "prune_ui28": 342}
MIN_CYCLES = 10
MIN_P95_SAMPLES = 20
MAX_START_TEMP_SKEW_C = 3.0
CASE = "police-hotword-performance"
MANIFEST_CASE = "police-hotword-performance-lanes-abba"

HOST_METRICS = (
    "prepareMs",
    "createMs",
    "startToOnStartMs",
    "firstPartialMs",
    "firstPartialOverheadMs",
    "finalE2eWallMs",
    "completeE2eWallMs",
    "prepareCpuMs",
    "createCpuMs",
    "sessionCpuMs",
    "cpuRtf",
)
MEMORY_METRICS = (
    "pssBaselineKb",
    "pssAfterPrepareKb",
    "pssAfterCreateKb",
    "pssPeakKb",
    "pssPeakDeltaKb",
    "pssBeforeShutdownKb",
    "pssAfterShutdownKb",
    "pssAfterUnloadKb",
    "rssBaselineKb",
    "rssAfterPrepareKb",
    "rssAfterCreateKb",
    "rssPeakKb",
    "rssPeakDeltaKb",
    "rssBeforeShutdownKb",
    "rssAfterShutdownKb",
    "rssAfterUnloadKb",
)
SDK_METRICS = (
    "sdk_engineReadyMs",
    "sdk_firstPartialLatencyMs",
    "sdk_utteranceE2eLatencyMs",
    "sdk_rtf",
    "sdk_nativeRssMbAtReady",
)
ALL_METRICS = (*HOST_METRICS, *MEMORY_METRICS, *SDK_METRICS)

# Candidate p95 must be <= max(FULL * ratio, FULL + floor).  SDK RTF is deliberately absent.
CPU_P95_GATES: dict[str, tuple[float, float]] = {
    "prepareMs": (1.05, 20.0),
    "createMs": (1.05, 20.0),
    "startToOnStartMs": (1.05, 20.0),
    "firstPartialMs": (1.05, 20.0),
    "firstPartialOverheadMs": (1.05, 20.0),
    "finalE2eWallMs": (1.05, 20.0),
    "sdk_engineReadyMs": (1.05, 20.0),
    "sdk_firstPartialLatencyMs": (1.05, 20.0),
    "sdk_utteranceE2eLatencyMs": (1.05, 20.0),
    "prepareCpuMs": (1.05, 20.0),
    "createCpuMs": (1.05, 20.0),
    "sessionCpuMs": (1.05, 20.0),
    "cpuRtf": (1.05, 0.02),
}
PROCESS_CPU_PAIRED_GATES: dict[str, tuple[float, float]] = {
    "prepareCpuMs": (0.05, 20.0),
    "createCpuMs": (0.05, 20.0),
    "sessionCpuMs": (0.05, 20.0),
    "cpuRtf": (0.05, 0.02),
}
MEMORY_P95_GATES: dict[str, tuple[float, float]] = {
    "pssPeakDeltaKb": (1.05, 10_240.0),
    "rssPeakDeltaKb": (1.05, 10_240.0),
    "sdk_nativeRssMbAtReady": (1.05, 10.0),
}

ROOT_FIELDS = (
    "schema_version",
    "case",
    "lanes",
    "git_sha",
    "worktree_dirty",
    "git_status_sha256",
    "git_status_after_sha256",
    "source_build",
    "plain_application",
    "audio_asset",
    "audio_evidence",
    "audio_sha256",
    "model_manifest_evidence",
    "model_manifest_sha256",
    "profile_source_evidence",
    "profile_source_sha256",
    "abba_cycles",
    "resolved_android_serial",
    "device_fingerprint",
    "device_sdk",
    "device_abi",
)
ARTIFACT_FIELDS = (
    "profile",
    "expected_count",
    "git_sha",
    "worktree_dirty",
    "git_status_sha256",
    "source_build",
    "plain_application",
    "audio_asset",
    "audio_sha256",
    "model_manifest_sha256",
    "model_payload_sha256",
    "profile_source_sha256",
    "target_apk_sha256",
    "test_apk_sha256",
)
RUN_FIELDS = (
    "run_id",
    "lane",
    "cycle",
    "position",
    "profile",
    "expected_count",
    "git_sha",
    "worktree_dirty",
    "git_status_sha256",
    "source_build",
    "plain_application",
    "resolved_android_serial",
    "device_fingerprint",
    "device_sdk",
    "device_abi",
    "audio_asset",
    "audio_sha256",
    "model_manifest_sha256",
    "model_payload_sha256",
    "profile_source_sha256",
    "artifact_manifest_sha256",
    "target_apk_sha256",
    "test_apk_sha256",
)


def numeric(value: object, *, allow_negative: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or (not allow_negative and result < 0.0):
        return None
    return result


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * q) - 1)]


def summary(values: Sequence[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def sha256_zip_entry(apk: Path, entry: str) -> tuple[str | None, str | None]:
    try:
        digest = hashlib.sha256()
        with zipfile.ZipFile(apk) as archive, archive.open(entry) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), None
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        return None, str(error)


def read_report(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return None, [f"missing report: {path}"]
    try:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                errors.append(f"{path}: line {line_no} is not an object")
            else:
                rows.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, [f"cannot parse {path}: {error}"]
    if len(rows) != 1:
        errors.append(f"{path}: expected exactly one report row, found {len(rows)}")
    return (rows[0] if rows else None), errors


def validate_instrumentation(run_dir: Path) -> list[str]:
    errors: list[str] = []
    try:
        exit_code = int((run_dir / "instrument-exit-code.txt").read_text().strip())
    except (OSError, ValueError):
        exit_code = -1
        errors.append(f"{run_dir.name}: invalid instrumentation exit code")
    text = (run_dir / "instrument.txt").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "instrument.txt").is_file() else ""
    if exit_code != 0:
        errors.append(f"{run_dir.name}: instrumentation exit={exit_code}")
    for marker in base.FAILURE_MARKERS:
        if marker in text:
            errors.append(f"{run_dir.name}: instrumentation marker {marker!r}")
    if "OK (1 test)" not in text:
        errors.append(f"{run_dir.name}: instrumentation is missing OK (1 test)")
    for name in ("compile-target.txt", "compile-test.txt"):
        path = run_dir / name
        content = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        if "Success" not in content:
            errors.append(f"{run_dir.name}: {name} does not prove successful fixed compilation")
    return errors


def read_metrics_log(run_dir: Path, run_id: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    path = run_dir / "metrics.log"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return {}, [f"{run_dir.name}: cannot read metrics.log: {error}"]
    log_re = re.compile(r"^\s*\S+\s+(\d+)\s+\d+\s+[A-Z]\s+([^:]+):\s*(.*)$")
    phase_re = re.compile(r"\brunId=(\S+)\s+pid=(\d+)\s+phase=(\S+)")
    phases: list[tuple[int, int, int, str, str]] = []
    cold: list[tuple[int, int]] = []
    utterances: list[tuple[int, dict[str, Any]]] = []
    for index, line in enumerate(text.splitlines()):
        matched = log_re.match(line)
        if matched is None:
            continue
        pid = int(matched.group(1))
        tag = matched.group(2).strip()
        message = matched.group(3).strip()
        if tag == "DqPoliceHotwordPerf":
            phase = phase_re.search(message)
            if phase:
                phases.append((index, pid, int(phase.group(2)), phase.group(1), phase.group(3)))
        if tag == "AmphionMetrics" and "kind=COLD_MODEL_LOAD" in message:
            cold.append((index, pid))
        if tag == "AmphionMetrics" and "kind=UTTERANCE" in message:
            parsed: dict[str, Any] = {}
            for token in message[message.find("kind=UTTERANCE"):].split():
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                try:
                    parsed[key] = float(value) if "." in value else int(value)
                except ValueError:
                    parsed[key] = value
            utterances.append((pid, parsed))

    expected_phases = (
        "prepare_start",
        "prepare_end",
        "create_start",
        "create_end",
        "recognition_start",
        "recognition_end",
    )
    own = [event for event in phases if event[3] == run_id]
    foreign = sorted({event[3] for event in phases if event[3] != run_id})
    if foreign:
        errors.append(f"{run_dir.name}: foreign phase runIds={foreign}")
    by_name: dict[str, tuple[int, int, int, str, str]] = {}
    for name in expected_phases:
        matches = [event for event in own if event[4] == name]
        if len(matches) != 1:
            errors.append(f"{run_dir.name}: phase={name} count={len(matches)}, expected 1")
        else:
            by_name[name] = matches[0]
    unexpected = sorted({event[4] for event in own if event[4] not in expected_phases})
    if unexpected:
        errors.append(f"{run_dir.name}: unexpected phases={unexpected}")
    if len(cold) != 1:
        errors.append(f"{run_dir.name}: COLD_MODEL_LOAD count={len(cold)}, expected 1")
    measurement_pid: int | None = None
    if len(by_name) == len(expected_phases) and len(cold) == 1:
        ordered = (
            by_name["prepare_start"][0],
            cold[0][0],
            by_name["prepare_end"][0],
            by_name["create_start"][0],
            by_name["create_end"][0],
            by_name["recognition_start"][0],
            by_name["recognition_end"][0],
        )
        if tuple(sorted(ordered)) != ordered or len(set(ordered)) != len(ordered):
            errors.append(f"{run_dir.name}: invalid phase/cold order={ordered}")
        prefix_pids = {event[1] for event in by_name.values()}
        message_pids = {event[2] for event in by_name.values()}
        for event in by_name.values():
            if event[1] != event[2]:
                errors.append(
                    f"{run_dir.name}: phase prefix PID={event[1]} != message PID={event[2]}",
                )
        pids = prefix_pids | message_pids | {cold[0][1]}
        if len(pids) != 1:
            errors.append(f"{run_dir.name}: phases/cold span PIDs={sorted(pids)}")
        else:
            measurement_pid = next(iter(pids))
    lowered = text.lower()
    for marker in base.POOL_MISMATCH_MARKERS:
        if marker in lowered:
            errors.append(f"{run_dir.name}: recognizer pool mismatch marker={marker!r}")
    if len(utterances) != 1:
        errors.append(f"{run_dir.name}: UTTERANCE metric count={len(utterances)}, expected 1")
    utterance_pid, selected = utterances[0] if utterances else (-1, {})
    if measurement_pid is not None and utterance_pid != measurement_pid:
        errors.append(
            f"{run_dir.name}: UTTERANCE PID={utterance_pid} != measurement PID={measurement_pid}",
        )
    if selected and selected.get("utteranceIndex") != 1:
        errors.append(
            f"{run_dir.name}: SDK utteranceIndex={selected.get('utteranceIndex')!r}, expected 1",
        )
    sdk = {f"sdk_{key}": value for key, value in selected.items()}
    sdk["sdk_logPid"] = utterance_pid
    return sdk, errors


def validate_root(root: Path, manifest: Mapping[str, str], issues: list[str]) -> int | None:
    issues.extend(base.require_fields(manifest, ROOT_FIELDS, "run manifest"))
    expected = {
        "schema_version": "2",
        "case": MANIFEST_CASE,
        "lanes": "cpu_latency,memory",
        "source_build": "true",
        "plain_application": "true",
        "audio_evidence": "artifacts/audio/input.wav",
        "model_manifest_evidence": "artifacts/model/manifest.json",
        "profile_source_evidence": "artifacts/profile-source-sha256.txt",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            issues.append(f"run manifest {key}={manifest.get(key)!r}, expected={value!r}")
    if not base.is_git_sha(manifest.get("git_sha")):
        issues.append(f"run manifest git_sha={manifest.get('git_sha')!r} is invalid")
    for key in (
        "git_status_sha256",
        "git_status_after_sha256",
        "audio_sha256",
        "model_manifest_sha256",
        "profile_source_sha256",
    ):
        if not base.is_sha256(manifest.get(key)):
            issues.append(f"run manifest {key}={manifest.get(key)!r} is invalid")
    if manifest.get("worktree_dirty") != "false":
        issues.append("formal evidence requires worktree_dirty=false")
    cycles = base.parse_int(manifest.get("abba_cycles"), "run manifest abba_cycles", issues)
    if cycles is not None and cycles < MIN_CYCLES:
        issues.append(f"abba_cycles={cycles}; require at least {MIN_CYCLES}")
    for key, path in (
        ("git_status_sha256", root / "git-status.txt"),
        ("git_status_after_sha256", root / "git-status-after.txt"),
        ("audio_sha256", root / "artifacts/audio/input.wav"),
        ("model_manifest_sha256", root / "artifacts/model/manifest.json"),
        ("profile_source_sha256", root / "artifacts/profile-source-sha256.txt"),
    ):
        actual = base.sha256_file(path)
        if actual is None or actual != manifest.get(key):
            issues.append(f"root binding {key}: manifest={manifest.get(key)!r} actual={actual!r}")
    before = root / "git-status.txt"
    after = root / "git-status-after.txt"
    if not before.is_file() or before.read_text(encoding="utf-8", errors="replace").strip():
        issues.append("formal git-status.txt must exist and be empty")
    if not after.is_file() or after.read_text(encoding="utf-8", errors="replace").strip():
        issues.append("formal git-status-after.txt must exist and be empty")
    serial = manifest.get("resolved_android_serial", "")
    devices = (root / "adb-devices.txt").read_text(encoding="utf-8", errors="replace") \
        if (root / "adb-devices.txt").is_file() else ""
    if not serial or not re.search(rf"(?m)^{re.escape(serial)}\s+device\b", devices):
        issues.append(f"resolved serial {serial!r} is not bound as device in adb-devices.txt")
    getprop = (root / "device-getprop.txt").read_text(encoding="utf-8", errors="replace") \
        if (root / "device-getprop.txt").is_file() else ""
    prop_expectations = {
        "ro.build.fingerprint": manifest.get("device_fingerprint"),
        "ro.build.version.sdk": manifest.get("device_sdk"),
        "ro.product.cpu.abi": manifest.get("device_abi"),
    }
    for prop, value in prop_expectations.items():
        if not value or f"[{prop}]: [{value}]" not in getprop:
            issues.append(f"device property {prop}={value!r} is not bound in device-getprop.txt")
    return cycles


def load_artifacts(
    root: Path,
    manifest: Mapping[str, str],
    issues: list[str],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    payloads: set[str] = set()
    for profile in PROFILES:
        artifact_dir = root / "artifacts" / profile
        path = artifact_dir / "manifest.txt"
        artifact, parse_errors = base.read_key_values(path, f"{profile} artifact")
        issues.extend(parse_errors)
        issues.extend(base.require_fields(artifact, ARTIFACT_FIELDS, f"{profile} artifact"))
        artifact = dict(artifact)
        artifact["artifact_manifest_sha256"] = base.sha256_file(path) or ""
        result[profile] = artifact
        if artifact.get("profile") != profile:
            issues.append(f"{profile}: artifact profile={artifact.get('profile')!r}")
        if base.parse_int(artifact.get("expected_count"), "expected_count", issues) != COUNTS[profile]:
            issues.append(f"{profile}: artifact expected_count must be {COUNTS[profile]}")
        for key in (
            "git_sha",
            "worktree_dirty",
            "git_status_sha256",
            "source_build",
            "plain_application",
            "audio_asset",
            "audio_sha256",
            "model_manifest_sha256",
            "profile_source_sha256",
        ):
            if artifact.get(key) != manifest.get(key):
                issues.append(
                    f"{profile}: artifact {key}={artifact.get(key)!r} "
                    f"expected={manifest.get(key)!r}",
                )
        for key, filename in (("target_apk_sha256", "target.apk"), ("test_apk_sha256", "test.apk")):
            actual = base.sha256_file(artifact_dir / filename)
            if actual != artifact.get(key):
                issues.append(f"{profile}: {filename} hash={actual} expected={artifact.get(key)}")
        payload, payload_errors = base.verify_apk_model_payloads(
            artifact_dir / "target.apk",
            root / "artifacts/model/manifest.json",
        )
        issues.extend(f"{profile}: {item}" for item in payload_errors)
        if payload != artifact.get("model_payload_sha256"):
            issues.append(
                f"{profile}: model payload={payload!r} expected={artifact.get('model_payload_sha256')!r}",
            )
        if payload:
            payloads.add(payload)
        embedded, error = sha256_zip_entry(
            artifact_dir / "test.apk",
            f"assets/{manifest.get('audio_asset', '')}",
        )
        if error or embedded != manifest.get("audio_sha256"):
            issues.append(
                f"{profile}: embedded audio hash={embedded!r} error={error!r} "
                f"expected={manifest.get('audio_sha256')!r}",
            )
    if len(payloads) != 1:
        issues.append(f"FULL/PRUNE must bind one identical model payload, got={sorted(payloads)}")
    return result


def validate_report(
    row: Mapping[str, Any],
    meta: Mapping[str, str],
    artifact: Mapping[str, str],
    issues: list[str],
    failures: list[str],
) -> None:
    run_id = meta.get("run_id", "")
    lane = meta.get("lane", "")
    exact = {
        "schemaVersion": 2,
        "case": CASE,
        "runId": run_id,
        "perfLane": lane,
        "applicationClass": "android.app.Application",
        "plainApplicationRequired": True,
        "demoBootstrapSuppressed": True,
        "prepareCallCount": 1,
        "createCallCount": 1,
        "compiledDefaultProfile": meta.get("profile"),
        "effectiveHotwordCount": COUNTS.get(meta.get("profile", "")),
        "audioAsset": meta.get("audio_asset"),
        "targetApkSha256": artifact.get("target_apk_sha256"),
        "testApkSha256": artifact.get("test_apk_sha256"),
        "modelManifestSha256": artifact.get("model_manifest_sha256"),
        "modelPayloadSha256": artifact.get("model_payload_sha256"),
        "audioSha256": artifact.get("audio_sha256"),
    }
    for key, expected in exact.items():
        if row.get(key) != expected:
            issues.append(f"{run_id}: report {key}={row.get(key)!r} expected={expected!r}")
    if not base.is_sha256(row.get("effectiveHotwordSha256")):
        issues.append(f"{run_id}: invalid effectiveHotwordSha256")
    if lane == "cpu_latency":
        for metric in HOST_METRICS:
            if numeric(row.get(metric)) is None:
                issues.append(f"{run_id}: missing/non-negative host metric {metric}")
        expected_cpu = {
            "resourceSamplerEnabled": False,
            "cpuIncludesResourceSampler": False,
            "resourceSampleIntervalMs": -1,
            "resourceSampleCount": 0,
            "resourceBackgroundSampleCount": 0,
            "resourceSamplingDurationMs": -1,
        }
        for key, expected in expected_cpu.items():
            if row.get(key) != expected:
                issues.append(f"{run_id}: CPU report {key}={row.get(key)!r} expected={expected!r}")
        for metric in MEMORY_METRICS:
            if numeric(row.get(metric), allow_negative=True) != -1.0:
                issues.append(f"{run_id}: CPU lane {metric} must be -1")
        if row.get("rssAvailable") is not False:
            issues.append(f"{run_id}: CPU lane rssAvailable must be false")
    elif lane == "memory":
        expected_memory = {
            "resourceSamplerEnabled": True,
            "cpuIncludesResourceSampler": True,
            "resourceSampleIntervalMs": 50,
            "resourceSamplingStoppedBeforeReport": True,
            "rssAvailable": True,
        }
        for key, expected in expected_memory.items():
            if row.get(key) != expected:
                issues.append(f"{run_id}: memory report {key}={row.get(key)!r} expected={expected!r}")
        total_samples = numeric(row.get("resourceSampleCount"))
        background_samples = numeric(row.get("resourceBackgroundSampleCount"))
        sampling_duration_ms = numeric(row.get("resourceSamplingDurationMs"))
        if total_samples is None or background_samples is None or sampling_duration_ms is None:
            issues.append(f"{run_id}: memory sampler coverage fields are missing")
        else:
            conservative_expected = max(5, math.floor(sampling_duration_ms / 50.0 * 0.5))
            if background_samples < conservative_expected:
                issues.append(
                    f"{run_id}: background samples={background_samples:.0f} below 50% coverage "
                    f"floor={conservative_expected} for duration={sampling_duration_ms:.0f}ms",
                )
            if total_samples < background_samples + 2:
                issues.append(
                    f"{run_id}: total samples={total_samples:.0f} do not include "
                    f"background={background_samples:.0f} plus measurement-end checkpoints",
                )
        for metric in MEMORY_METRICS:
            if numeric(row.get(metric)) is None:
                issues.append(f"{run_id}: missing/non-negative memory metric {metric}")
    if row.get("errors"):
        failures.append(f"{run_id}: recognition errors={row.get('errors')!r}")
    if numeric(row.get("finalCount")) is None or int(row.get("finalCount", 0)) <= 0:
        failures.append(f"{run_id}: no final result")
    if row.get("lastCount") != 1:
        failures.append(f"{run_id}: lastCount={row.get('lastCount')!r}, expected=1")


def load_runs(
    root: Path,
    cycles: int | None,
    manifest: Mapping[str, str],
    artifacts: Mapping[str, Mapping[str, str]],
    issues: list[str],
    failures: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane in LANES:
        runs_root = root / lane / "runs"
        run_dirs = sorted(path for path in runs_root.glob("*") if path.is_dir()) \
            if runs_root.is_dir() else []
        expected_dirs = {
            f"{lane}-c{cycle:02d}-p{position:02d}-{profile}"
            for cycle in range(1, (cycles or 0) + 1)
            for position, profile in enumerate(ABBA, 1)
        }
        actual_dirs = {path.name for path in run_dirs}
        if cycles is None or actual_dirs != expected_dirs:
            issues.append(
                f"{lane}: exact run set mismatch; missing={sorted(expected_dirs - actual_dirs)} "
                f"extra={sorted(actual_dirs - expected_dirs)}",
            )
        for run_dir in run_dirs:
            meta, meta_errors = base.read_key_values(run_dir / "meta.txt", f"{run_dir.name} meta")
            issues.extend(meta_errors)
            issues.extend(base.require_fields(meta, RUN_FIELDS, f"{run_dir.name} meta"))
            run_id = meta.get("run_id", "")
            profile = meta.get("profile", "")
            cycle = base.parse_int(meta.get("cycle"), f"{run_dir.name} cycle", issues)
            position = base.parse_int(meta.get("position"), f"{run_dir.name} position", issues)
            if run_id != run_dir.name or meta.get("lane") != lane:
                issues.append(f"{run_dir.name}: run/lane identity mismatch")
            expected_profile = ABBA[position - 1] if position and 1 <= position <= 4 else None
            canonical = f"{lane}-c{cycle:02d}-p{position:02d}-{profile}" \
                if cycle is not None and position is not None else ""
            if run_id != canonical or profile != expected_profile:
                issues.append(
                    f"{run_dir.name}: noncanonical identity/profile, canonical={canonical!r} "
                    f"expected_profile={expected_profile!r}",
                )
            artifact = artifacts.get(profile, {})
            shared = {
                "git_sha": manifest.get("git_sha"),
                "worktree_dirty": manifest.get("worktree_dirty"),
                "git_status_sha256": manifest.get("git_status_sha256"),
                "source_build": "true",
                "plain_application": "true",
                "resolved_android_serial": manifest.get("resolved_android_serial"),
                "device_fingerprint": manifest.get("device_fingerprint"),
                "device_sdk": manifest.get("device_sdk"),
                "device_abi": manifest.get("device_abi"),
                "audio_asset": artifact.get("audio_asset"),
                "audio_sha256": artifact.get("audio_sha256"),
                "model_manifest_sha256": artifact.get("model_manifest_sha256"),
                "model_payload_sha256": artifact.get("model_payload_sha256"),
                "profile_source_sha256": artifact.get("profile_source_sha256"),
                "artifact_manifest_sha256": artifact.get("artifact_manifest_sha256"),
                "target_apk_sha256": artifact.get("target_apk_sha256"),
                "test_apk_sha256": artifact.get("test_apk_sha256"),
            }
            for key, expected in shared.items():
                if meta.get(key) != expected:
                    issues.append(f"{run_dir.name}: meta {key}={meta.get(key)!r} expected={expected!r}")
            if base.parse_int(meta.get("expected_count"), "expected_count", issues) != COUNTS.get(profile):
                issues.append(f"{run_dir.name}: invalid expected_count")
            failures.extend(validate_instrumentation(run_dir))
            report, report_errors = read_report(run_dir / "report.jsonl")
            issues.extend(report_errors)
            sdk, metric_errors = read_metrics_log(run_dir, run_id)
            issues.extend(metric_errors)
            thermal, thermal_errors = base.read_thermal_evidence(run_dir)
            issues.extend(f"{run_dir.name}: {item}" for item in thermal_errors)
            for key in ("thermal_status_before", "thermal_status_after", "ap_status_before", "ap_status_after"):
                if thermal.get(key) != 0:
                    issues.append(f"{run_dir.name}: {key}={thermal.get(key)!r}, expected 0")
            if report is None:
                continue
            validate_report(report, meta, artifact, issues, failures)
            if sdk.get("sdk_pcmBytesAccepted") != report.get("acceptedPcmBytes"):
                issues.append(
                    f"{run_dir.name}: SDK pcmBytesAccepted={sdk.get('sdk_pcmBytesAccepted')!r} "
                    f"!= report acceptedPcmBytes={report.get('acceptedPcmBytes')!r}",
                )
            if sdk.get("sdk_sessionId") not in (1, "1"):
                issues.append(
                    f"{run_dir.name}: fresh-process SDK sessionId={sdk.get('sdk_sessionId')!r}, expected 1",
                )
            required_sdk = (
                "sdk_engineReadyMs",
                "sdk_firstPartialLatencyMs",
                "sdk_utteranceE2eLatencyMs",
            ) if lane == "cpu_latency" else ("sdk_nativeRssMbAtReady",)
            for sdk_metric in required_sdk:
                if numeric(sdk.get(sdk_metric)) is None:
                    issues.append(f"{run_dir.name}: missing SDK metric {sdk_metric}")
            rows.append({**report, **sdk, **thermal, "meta": dict(meta), "runDir": run_dir.name})
    return rows


def validate_thermal_pairs(rows: Sequence[Mapping[str, Any]], issues: list[str]) -> None:
    indexed: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    for row in rows:
        meta = row["meta"]
        try:
            indexed[(str(meta["lane"]), int(meta["cycle"]), int(meta["position"]))] = row
        except (KeyError, TypeError, ValueError):
            continue
    for lane in LANES:
        cycles = sorted({key[1] for key in indexed if key[0] == lane})
        for cycle in cycles:
            for pair, full_pos, prune_pos in (("A", 1, 2), ("B", 4, 3)):
                full = indexed.get((lane, cycle, full_pos))
                prune = indexed.get((lane, cycle, prune_pos))
                if full is None or prune is None:
                    issues.append(f"{lane} cycle={cycle} pair={pair}: missing thermal pair")
                    continue
                for key in ("battery_before_c", "ap_before_c"):
                    left = numeric(full.get(key), allow_negative=True)
                    right = numeric(prune.get(key), allow_negative=True)
                    if left is None or right is None:
                        issues.append(f"{lane} cycle={cycle} pair={pair}: missing {key}")
                    elif abs(right - left) > MAX_START_TEMP_SKEW_C:
                        issues.append(
                            f"{lane} cycle={cycle} pair={pair}: {key} skew="
                            f"{abs(right-left):.2f}C > {MAX_START_TEMP_SKEW_C:.2f}C",
                        )


def validate_effective_hotword_hashes(
    rows: Sequence[Mapping[str, Any]],
    issues: list[str],
) -> None:
    by_profile: dict[str, set[str]] = {}
    for profile in PROFILES:
        hashes = {
            str(row.get("effectiveHotwordSha256"))
            for row in rows
            if row.get("compiledDefaultProfile") == profile
            and base.is_sha256(row.get("effectiveHotwordSha256"))
        }
        by_profile[profile] = hashes
        if len(hashes) != 1:
            issues.append(
                f"{profile}: effective hotword hash must be stable across both lanes/all runs, "
                f"got={sorted(hashes)}",
            )
    if all(len(by_profile[profile]) == 1 for profile in PROFILES):
        if by_profile["full"] == by_profile["prune_ui28"]:
            issues.append("FULL and PRUNE_UI28 effective hotword hashes must differ")


def build_summaries(rows: Sequence[Mapping[str, Any]], issues: list[str]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for lane in LANES:
        summaries[lane] = {}
        applicable = (*HOST_METRICS, *SDK_METRICS) if lane == "cpu_latency" else ALL_METRICS
        required = set(
            (*HOST_METRICS, "sdk_engineReadyMs", "sdk_firstPartialLatencyMs", "sdk_utteranceE2eLatencyMs")
            if lane == "cpu_latency"
            else (*MEMORY_METRICS, "sdk_nativeRssMbAtReady")
        )
        for profile in PROFILES:
            selected = [row for row in rows if row.get("perfLane") == lane and row.get("compiledDefaultProfile") == profile]
            summaries[lane][profile] = {}
            if len(selected) < MIN_P95_SAMPLES:
                issues.append(
                    f"{lane}/{profile}: {len(selected)} complete rows; require at least {MIN_P95_SAMPLES}",
                )
            for metric in applicable:
                values = [value for row in selected if (value := numeric(row.get(metric))) is not None]
                if len(values) != len(selected) or len(values) < MIN_P95_SAMPLES:
                    if metric not in required:
                        continue
                    issues.append(
                        f"{lane}/{profile}/{metric}: {len(values)}/{len(selected)} valid samples; "
                        f"require >= {MIN_P95_SAMPLES} and no missing values",
                    )
                    continue
                summaries[lane][profile][metric] = summary(values)
    return summaries


def paired_metric(rows: Sequence[Mapping[str, Any]], lane: str, metric: str) -> list[dict[str, float | int | str]]:
    indexed: dict[tuple[int, int], Mapping[str, Any]] = {}
    for row in rows:
        meta = row.get("meta", {})
        if meta.get("lane") != lane:
            continue
        indexed[(int(meta["cycle"]), int(meta["position"]))] = row
    result: list[dict[str, float | int | str]] = []
    for cycle in sorted({key[0] for key in indexed}):
        for pair, full_pos, prune_pos in (("A", 1, 2), ("B", 4, 3)):
            full = indexed.get((cycle, full_pos))
            prune = indexed.get((cycle, prune_pos))
            if full is None or prune is None:
                continue
            full_value = numeric(full.get(metric))
            prune_value = numeric(prune.get(metric))
            if full_value is None or prune_value is None:
                continue
            result.append(
                {
                    "cycle": cycle,
                    "pair": pair,
                    "full": full_value,
                    "prune": prune_value,
                    "delta": prune_value - full_value,
                    "delta_percent": ((prune_value / full_value) - 1.0) * 100.0 if full_value else 0.0,
                },
            )
    return result


def apply_gates(
    rows: Sequence[Mapping[str, Any]],
    summaries: Mapping[str, Any],
    cycles: int | None,
    issues: list[str],
    failures: list[str],
) -> dict[str, Any]:
    comparisons: dict[str, Any] = {"cpu_latency": {}, "memory": {}, "process_cpu_paired": {}}
    for lane, gates in (("cpu_latency", CPU_P95_GATES), ("memory", MEMORY_P95_GATES)):
        for metric, (ratio, floor) in gates.items():
            full = summaries.get(lane, {}).get("full", {}).get(metric)
            prune = summaries.get(lane, {}).get("prune_ui28", {}).get(metric)
            if not full or not prune:
                continue
            full_p95 = float(full["p95"])
            prune_p95 = float(prune["p95"])
            allowed = max(full_p95 * ratio, full_p95 + floor)
            comparisons[lane][metric] = {
                "full_p95": full_p95,
                "prune_p95": prune_p95,
                "allowed_p95": allowed,
                "delta": prune_p95 - full_p95,
            }
            if prune_p95 > allowed:
                failures.append(
                    f"{lane}/{metric}: prune p95={prune_p95:.3f} > allowed={allowed:.3f}",
                )
    for metric, (ratio, floor) in PROCESS_CPU_PAIRED_GATES.items():
        pairs = paired_metric(rows, "cpu_latency", metric)
        expected_pairs = 2 * cycles if cycles is not None else 0
        if len(pairs) != expected_pairs:
            issues.append(
                f"cpu_latency/{metric}: paired count={len(pairs)}, expected={expected_pairs}",
            )
        if not pairs:
            continue
        full_median = statistics.median(float(item["full"]) for item in pairs)
        delta_median = statistics.median(float(item["delta"]) for item in pairs)
        allowed_delta = max(full_median * ratio, floor)
        comparisons["process_cpu_paired"][metric] = {
            "n": len(pairs),
            "full_median": full_median,
            "paired_delta_median": delta_median,
            "allowed_delta": allowed_delta,
            "positive_delta_count": sum(float(item["delta"]) > 0.0 for item in pairs),
            "negative_delta_count": sum(float(item["delta"]) < 0.0 for item in pairs),
            "pairs": pairs,
        }
        if delta_median > allowed_delta:
            failures.append(
                f"cpu_latency/{metric}: paired median delta={delta_median:.3f} "
                f"> allowed={allowed_delta:.3f}",
            )
    return comparisons


def write_summary(
    root: Path,
    status: str,
    rows: Sequence[Mapping[str, Any]],
    summaries: Mapping[str, Any],
    comparisons: Mapping[str, Any],
    failures: Sequence[str],
    issues: Sequence[str],
) -> None:
    payload = {
        "schema_version": 3,
        "status": status,
        "formal_build": not issues,
        "cpu_memory_probes_split": True,
        "automatic_thermal_validation": True,
        "run_count": len(rows),
        "profile_counts": {
            lane: {
                profile: sum(
                    row.get("perfLane") == lane and row.get("compiledDefaultProfile") == profile
                    for row in rows
                )
                for profile in PROFILES
            }
            for lane in LANES
        },
        "summaries": summaries,
        "comparisons": comparisons,
        "failures": list(dict.fromkeys(failures)),
        "inconclusive": list(dict.fromkeys(issues)),
        "gate_notes": [
            "memory lane CPU/latency values are diagnostic only",
            "cpu_latency lane memory values are disabled and never gated",
            "process CPU has p95 relative gates plus paired diagnostics; there is no absolute 0.8 gate",
            "paced-input SDK RTF is displayed but never gated",
            "this tool decides PRUNE-vs-FULL relative regression, not an absolute delivery SLA",
        ],
    }
    (root / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Police hotword formal split-lane ABBA",
        "",
        f"Status: **{status}**",
        "",
        f"Complete rows: {len(rows)}",
    ]
    for lane in LANES:
        lines += ["", f"## {lane}", "", "| Metric | FULL median / p95 | PRUNE median / p95 |", "| --- | ---: | ---: |"]
        metrics = (*HOST_METRICS, *SDK_METRICS) if lane == "cpu_latency" else ALL_METRICS
        for metric in metrics:
            full = summaries.get(lane, {}).get("full", {}).get(metric)
            prune = summaries.get(lane, {}).get("prune_ui28", {}).get(metric)
            if full and prune:
                lines.append(
                    f"| {metric} | {full['median']:.3f} / {full['p95']:.3f} | "
                    f"{prune['median']:.3f} / {prune['p95']:.3f} |",
                )
    if failures:
        lines += ["", "## Failures", "", *[f"- {item}" for item in dict.fromkeys(failures)]]
    if issues:
        lines += ["", "## Inconclusive evidence", "", *[f"- {item}" for item in dict.fromkeys(issues)]]
    lines += [
        "",
        "## Gate semantics",
        "",
        "- Memory-lane CPU/latency is diagnostic only.",
        "- Process CPU uses p95 relative gates plus paired diagnostics; no absolute 0.8 gate exists.",
        "- Paced-input SDK RTF is reported but never gated.",
        "- PASS answers relative PRUNE-vs-FULL regression only; it is not an absolute delivery SLA.",
    ]
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(root: Path) -> int:
    issues: list[str] = []
    failures: list[str] = []
    manifest, parse_errors = base.read_key_values(root / "run-manifest.txt", "run manifest")
    issues.extend(parse_errors)
    cycles = validate_root(root, manifest, issues)
    artifacts = load_artifacts(root, manifest, issues)
    rows = load_runs(root, cycles, manifest, artifacts, issues, failures)
    validate_effective_hotword_hashes(rows, issues)
    validate_thermal_pairs(rows, issues)
    summaries = build_summaries(rows, issues)
    comparisons = apply_gates(rows, summaries, cycles, issues, failures)
    issues = list(dict.fromkeys(issues))
    failures = list(dict.fromkeys(failures))
    status = "FAIL" if failures else ("INCONCLUSIVE" if issues else "PASS")
    write_summary(root, status, rows, summaries, comparisons, failures, issues)
    print(json.dumps({"status": status, "summary": str(root / "summary.json")}, ensure_ascii=False))
    return 0 if status == "PASS" else (1 if status == "FAIL" else 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", nargs="?", type=Path)
    parser.add_argument("extra", nargs="*", type=Path)
    parser.add_argument("--print-model-payload-hash", action="store_true")
    args = parser.parse_args()
    if args.print_model_payload_hash:
        paths = ([args.evidence_root] if args.evidence_root else []) + args.extra
        if len(paths) != 2:
            parser.error("--print-model-payload-hash requires APK and model manifest")
        payload, errors = base.verify_apk_model_payloads(paths[0].resolve(), paths[1].resolve())
        if errors or payload is None:
            for error in errors:
                print(error, file=sys.stderr)
            raise SystemExit(1)
        print(payload)
        return
    if args.evidence_root is None or args.extra:
        parser.error("provide exactly one evidence root")
    raise SystemExit(analyze(args.evidence_root.resolve()))


if __name__ == "__main__":
    main()
