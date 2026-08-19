#!/usr/bin/env python3
"""Validate and summarize isolated Android create-only ABBA evidence.

This analyzer intentionally has no performance pass/fail threshold.  Its status
only answers two questions:

* is every run bound to the declared source-built APK/model/profile evidence (and formal when
  the captured worktree is clean); and
* were the paired FULL/PRUNE runs thermally comparable at their start?

Small-sample percentiles are misleading for the default five-cycle run (ten
samples per profile), so p95 is emitted only when a profile has at least twenty
samples.
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
from typing import Any, Iterable, Mapping, Sequence


PROFILES = ("full", "prune_ui28")
EXPECTED_COUNTS = {"full": 370, "prune_ui28": 342}
EXPECTED_ABBA = ("full", "prune_ui28", "prune_ui28", "full")
CASE = "police-hotword-create-only"
MANIFEST_CASE = "police-hotword-create-only-abba"
MIN_CYCLES = 5
MIN_P95_SAMPLES = 20
MAX_PAIRED_START_TEMPERATURE_SKEW_C = 3.0
METRICS: tuple[tuple[str, str], ...] = (
    ("prepareMs", "prepare wall ms"),
    ("createMs", "create wall ms"),
    ("prepareCpuMs", "prepare process CPU ms"),
    ("createCpuMs", "create process CPU ms"),
)

ROOT_MANIFEST_FIELDS = (
    "schema_version",
    "case",
    "git_sha",
    "worktree_dirty",
    "git_status_sha256",
    "git_status_after_sha256",
    "model_manifest_evidence",
    "model_manifest_sha256",
    "profile_source_evidence",
    "profile_source_sha256",
    "abba_cycles",
    "source_build",
    "android_serial",
)
ARTIFACT_FIELDS = (
    "profile",
    "expected_count",
    "git_sha",
    "worktree_dirty",
    "git_status_sha256",
    "source_build",
    "model_manifest_sha256",
    "model_payload_sha256",
    "profile_source_sha256",
    "target_apk_sha256",
    "test_apk_sha256",
)
RUN_META_FIELDS = (
    "run_id",
    "cycle",
    "position",
    *ARTIFACT_FIELDS,
    "artifact_manifest_sha256",
)
FAILURE_MARKERS = (
    "FAILURES!!!",
    "INSTRUMENTATION_FAILED",
    "INSTRUMENTATION_ABORTED",
    "shortMsg=Process crashed",
)
POOL_MISMATCH_MARKERS = (
    "pooled but config mismatch",
    "pool mismatch",
    "pool_mismatch",
)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def is_git_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None


def read_key_values(path: Path, label: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    values: dict[str, str] = {}
    if not path.is_file():
        return values, [f"missing {label}: {path}"]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        return values, [f"cannot read {label} {path}: {error}"]
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        if "=" not in raw:
            errors.append(f"{label} line {line_number} is not key=value")
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            errors.append(f"{label} line {line_number} has an empty key")
        elif key in values:
            errors.append(f"{label} has duplicate key {key!r}")
        else:
            values[key] = value
    return values, errors


def require_fields(
    values: Mapping[str, str],
    fields: Iterable[str],
    label: str,
) -> list[str]:
    return [f"{label} is missing {field}" for field in fields if not values.get(field)]


def parse_int(value: object, label: str, errors: list[str]) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        errors.append(f"{label}={value!r} is not an integer")
        return None
    return parsed


def numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else None


def percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def summarize_values(values: Sequence[float]) -> dict[str, object]:
    result: dict[str, object] = {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }
    if len(values) >= MIN_P95_SAMPLES:
        result["p95"] = percentile(values, 0.95)
    else:
        result["percentile_note"] = (
            f"p95 omitted: n={len(values)} < {MIN_P95_SAMPLES}"
        )
    return result


def verify_apk_model_payloads(
    apk_path: Path,
    model_manifest_path: Path,
) -> tuple[str | None, list[str]]:
    """Verify every manifest model asset and hash their canonical inventory."""

    errors: list[str] = []
    try:
        model_manifest = json.loads(model_manifest_path.read_text(encoding="utf-8"))
        bundles = model_manifest["bundles"]
        if not isinstance(bundles, dict):
            raise ValueError("manifest bundles must be an object")
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return None, [f"cannot parse model manifest: {error}"]

    inventory: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(apk_path) as archive:
            for bundle_id in sorted(bundles):
                entries = bundles[bundle_id]
                if not isinstance(entries, list):
                    errors.append(f"model bundle {bundle_id} is not a list")
                    continue
                sortable_entries = sorted(
                    entries,
                    key=lambda item: (
                        str(item.get("name", "")) if isinstance(item, dict) else str(item)
                    ),
                )
                for entry in sortable_entries:
                    name = entry.get("name") if isinstance(entry, dict) else None
                    expected = entry.get("output_sha256") if isinstance(entry, dict) else None
                    if not isinstance(name, str) or not name or not is_sha256(expected):
                        errors.append(f"invalid model entry in bundle {bundle_id}: {entry}")
                        continue
                    archive_name = f"assets/amphion-models/{bundle_id}/{name}"
                    try:
                        digest = hashlib.sha256()
                        with archive.open(archive_name) as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(chunk)
                        actual = digest.hexdigest()
                    except KeyError:
                        errors.append(f"APK is missing model asset {archive_name}")
                        continue
                    inventory.append((archive_name, actual))
                    if actual != expected:
                        errors.append(
                            f"model asset {archive_name} hash={actual} expected={expected}",
                        )
    except (OSError, zipfile.BadZipFile) as error:
        return None, [f"cannot inspect target APK models: {error}"]

    if not inventory:
        errors.append("no model payloads were verified in target APK")
        return None, errors
    combined = hashlib.sha256()
    for name, digest in inventory:
        combined.update(f"{name}={digest}\n".encode("utf-8"))
    return combined.hexdigest(), errors


def read_report(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return None, [f"missing report: {path}"]
    try:
        for line_number, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as error:
                errors.append(f"{path}: invalid JSON at line {line_number}: {error}")
                continue
            if not isinstance(row, dict):
                errors.append(f"{path}: line {line_number} is not a JSON object")
                continue
            rows.append(row)
    except (OSError, UnicodeError) as error:
        return None, [f"cannot read report {path}: {error}"]
    if len(rows) != 1:
        errors.append(f"{path}: expected exactly one JSONL row, found {len(rows)}")
    if not rows:
        return None, errors
    if rows[0].get("case") != CASE:
        errors.append(f"{path}: case={rows[0].get('case')!r} expected={CASE!r}")
    return rows[0], errors


def validate_instrumentation(run_dir: Path) -> list[str]:
    errors: list[str] = []
    exit_path = run_dir / "instrument-exit-code.txt"
    try:
        exit_code = int(exit_path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError, ValueError):
        errors.append(f"{run_dir.name}: invalid or missing instrumentation exit code")
        exit_code = None
    if exit_code is not None and exit_code != 0:
        errors.append(f"{run_dir.name}: instrumentation exit={exit_code}")

    instrument_path = run_dir / "instrument.txt"
    try:
        text = instrument_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        errors.append(f"{run_dir.name}: cannot read instrumentation output: {error}")
        return errors
    marker = next((item for item in FAILURE_MARKERS if item in text), None)
    if marker:
        errors.append(f"{run_dir.name}: instrumentation failure marker {marker!r}")
    if "OK (1 test)" not in text:
        errors.append(f"{run_dir.name}: instrumentation output is missing 'OK (1 test)'")
    return errors


def validate_metrics_log(run_dir: Path, run_id: str) -> tuple[int, list[str]]:
    errors: list[str] = []
    path = run_dir / "metrics.log"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return 0, [f"{run_dir.name}: cannot read metrics.log: {error}"]
    lines = text.splitlines()
    cold_events: list[tuple[int, int]] = []
    phase_events: list[tuple[int, int, str, str]] = []
    log_line = re.compile(
        r"^\s*\S+\s+(\d+)\s+\d+\s+[A-Z]\s+([^:]+):\s*(.*)$",
    )
    phase_message = re.compile(r"^runId=(\S+)\s+phase=(\S+)$")
    for index, line in enumerate(lines):
        parsed = log_line.match(line)
        if parsed is None:
            continue
        pid = int(parsed.group(1))
        tag = parsed.group(2).strip()
        message = parsed.group(3).strip()
        if tag == "AmphionMetrics" and "kind=COLD_MODEL_LOAD" in message:
            cold_events.append((index, pid))
        if tag == "DqPoliceCreateOnlyPerf":
            phase = phase_message.match(message)
            if phase is not None:
                phase_events.append((index, pid, phase.group(1), phase.group(2)))

    cold_count = len(cold_events)
    if cold_count != 1:
        errors.append(
            f"{run_dir.name}: expected exactly one COLD_MODEL_LOAD log, found {cold_count}",
        )
    expected_phases = ("prepare_start", "prepare_end", "create_start", "create_end")
    own_events = [event for event in phase_events if event[2] == run_id]
    foreign_run_ids = sorted({event[2] for event in phase_events if event[2] != run_id})
    if foreign_run_ids:
        errors.append(
            f"{run_dir.name}: phase logs contain foreign runIds={foreign_run_ids}",
        )
    phase_by_name: dict[str, tuple[int, int, str, str]] = {}
    for phase_name in expected_phases:
        matches = [event for event in own_events if event[3] == phase_name]
        if len(matches) != 1:
            errors.append(
                f"{run_dir.name}: expected one phase={phase_name} log, found {len(matches)}",
            )
        else:
            phase_by_name[phase_name] = matches[0]
    unexpected_phases = sorted(
        {event[3] for event in own_events if event[3] not in expected_phases},
    )
    if unexpected_phases:
        errors.append(f"{run_dir.name}: unexpected phase logs={unexpected_phases}")

    if len(phase_by_name) == len(expected_phases) and cold_count == 1:
        marker_pids = {event[1] for event in phase_by_name.values()}
        cold_index, cold_pid = cold_events[0]
        if len(marker_pids) != 1 or cold_pid not in marker_pids:
            errors.append(
                f"{run_dir.name}: phase PID(s)={sorted(marker_pids)} "
                f"do not match COLD_MODEL_LOAD PID={cold_pid}",
            )
        observed_order = (
            phase_by_name["prepare_start"][0],
            cold_index,
            phase_by_name["prepare_end"][0],
            phase_by_name["create_start"][0],
            phase_by_name["create_end"][0],
        )
        if tuple(sorted(observed_order)) != observed_order or len(set(observed_order)) != 5:
            errors.append(
                f"{run_dir.name}: expected prepare_start < COLD_MODEL_LOAD < prepare_end "
                f"< create_start < create_end, indexes={observed_order}",
            )
    lowered = text.lower()
    marker = next((item for item in POOL_MISMATCH_MARKERS if item in lowered), None)
    if marker:
        errors.append(f"{run_dir.name}: recognizer pool mismatch logged ({marker})")
    return cold_count, errors


def parse_battery_temperature(path: Path) -> tuple[float | None, list[str]]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return None, [f"cannot read {path}: {error}"]
    matches = re.findall(r"(?m)^\s*temperature:\s*(-?\d+(?:\.\d+)?)\s*$", text)
    if len(matches) != 1:
        return None, [f"{path}: expected one battery temperature, found {len(matches)}"]
    temperature = float(matches[0]) / 10.0
    if not math.isfinite(temperature) or not -20.0 <= temperature <= 100.0:
        errors.append(f"{path}: implausible battery temperature {temperature}")
        return None, errors
    return temperature, errors


def parse_thermal_service(path: Path) -> tuple[int | None, float | None, int | None, list[str]]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return None, None, None, [f"cannot read {path}: {error}"]

    status_matches = re.findall(r"(?m)^\s*Thermal Status:\s*(-?\d+)\s*$", text)
    thermal_status: int | None = None
    if len(status_matches) != 1:
        errors.append(f"{path}: expected one Thermal Status, found {len(status_matches)}")
    else:
        thermal_status = int(status_matches[0])

    ap_readings: list[tuple[float, int]] = []
    for line in text.splitlines():
        if "Temperature{" not in line or "mName=AP" not in line:
            continue
        value_match = re.search(r"mValue=(-?\d+(?:\.\d+)?)", line)
        status_match = re.search(r"mStatus=(-?\d+)", line)
        if value_match and status_match:
            ap_readings.append((float(value_match.group(1)), int(status_match.group(1))))
    ap_temperature: float | None = None
    ap_status: int | None = None
    if not ap_readings:
        errors.append(f"{path}: no AP thermal reading found")
    else:
        # dumpsys normally lists a cached reading and then the current HAL reading.  The final
        # occurrence is the current value and is the one used for comparison.
        ap_temperature, ap_status = ap_readings[-1]
        if not math.isfinite(ap_temperature) or not -20.0 <= ap_temperature <= 150.0:
            errors.append(f"{path}: implausible AP temperature {ap_temperature}")
            ap_temperature = None
    return thermal_status, ap_temperature, ap_status, errors


def read_thermal_evidence(run_dir: Path) -> tuple[dict[str, object], list[str]]:
    result: dict[str, object] = {}
    errors: list[str] = []
    for phase in ("before", "after"):
        battery, battery_errors = parse_battery_temperature(run_dir / f"battery-{phase}.txt")
        status, ap, ap_status, thermal_errors = parse_thermal_service(
            run_dir / f"thermal-{phase}.txt",
        )
        errors.extend(battery_errors)
        errors.extend(thermal_errors)
        result[f"battery_{phase}_c"] = battery
        result[f"thermal_status_{phase}"] = status
        result[f"ap_{phase}_c"] = ap
        result[f"ap_status_{phase}"] = ap_status
    return result, errors


def validate_root_manifest(
    root: Path,
    manifest: Mapping[str, str],
    expected_cycles_override: int | None,
    errors: list[str],
) -> int | None:
    errors.extend(require_fields(manifest, ROOT_MANIFEST_FIELDS, "run manifest"))
    if manifest.get("schema_version") != "1":
        errors.append(f"run manifest schema_version={manifest.get('schema_version')!r} expected='1'")
    if manifest.get("case") != MANIFEST_CASE:
        errors.append(f"run manifest case={manifest.get('case')!r} expected={MANIFEST_CASE!r}")
    if manifest.get("source_build") != "true":
        errors.append("run manifest source_build must be true")
    if manifest.get("worktree_dirty") not in {"true", "false"}:
        errors.append("run manifest worktree_dirty must be true or false")
    if not is_git_sha(manifest.get("git_sha")):
        errors.append(f"run manifest git_sha={manifest.get('git_sha')!r} is invalid")
    for key in (
        "git_status_sha256",
        "git_status_after_sha256",
        "model_manifest_sha256",
        "profile_source_sha256",
    ):
        if not is_sha256(manifest.get(key)):
            errors.append(f"run manifest {key}={manifest.get(key)!r} is invalid")
    if manifest.get("model_manifest_evidence") != "artifacts/model/manifest.json":
        errors.append("run manifest model_manifest_evidence must be artifacts/model/manifest.json")
    if manifest.get("profile_source_evidence") != "artifacts/profile-source-sha256.txt":
        errors.append(
            "run manifest profile_source_evidence must be artifacts/profile-source-sha256.txt",
        )

    cycles = parse_int(manifest.get("abba_cycles"), "run manifest abba_cycles", errors)
    if cycles is not None and cycles < MIN_CYCLES:
        errors.append(f"run manifest abba_cycles={cycles}; require at least {MIN_CYCLES}")
    if expected_cycles_override is not None and cycles != expected_cycles_override:
        errors.append(
            f"run manifest abba_cycles={cycles} expected override={expected_cycles_override}",
        )

    evidence_files = (
        ("git_status_sha256", root / "git-status.txt"),
        ("git_status_after_sha256", root / "git-status-after.txt"),
        ("model_manifest_sha256", root / "artifacts/model/manifest.json"),
        ("profile_source_sha256", root / "artifacts/profile-source-sha256.txt"),
    )
    for key, path in evidence_files:
        actual = sha256_file(path)
        expected = manifest.get(key)
        if actual is None:
            errors.append(f"missing bound evidence file for {key}: {path}")
        elif expected and actual != expected:
            errors.append(f"{key} mismatch: manifest={expected} actual={actual}")

    status_path = root / "git-status.txt"
    if status_path.is_file():
        dirty_actual = bool(status_path.read_text(encoding="utf-8", errors="replace").strip())
        dirty_expected = manifest.get("worktree_dirty") == "true"
        if dirty_actual != dirty_expected:
            errors.append(
                f"worktree_dirty={manifest.get('worktree_dirty')} disagrees with git-status.txt",
            )
    before_status_hash = sha256_file(root / "git-status.txt")
    after_status_hash = sha256_file(root / "git-status-after.txt")
    if before_status_hash and after_status_hash and before_status_hash != after_status_hash:
        errors.append("captured git status changed during the source-built evidence run")
    return cycles


def load_artifacts(
    root: Path,
    manifest: Mapping[str, str],
    errors: list[str],
) -> dict[str, dict[str, str]]:
    artifacts: dict[str, dict[str, str]] = {}
    verified_payloads: set[str] = set()
    for profile in PROFILES:
        artifact_dir = root / "artifacts" / profile
        artifact_path = artifact_dir / "manifest.txt"
        artifact, parse_errors = read_key_values(artifact_path, f"{profile} artifact manifest")
        errors.extend(parse_errors)
        errors.extend(require_fields(artifact, ARTIFACT_FIELDS, f"{profile} artifact manifest"))
        artifact = dict(artifact)
        artifact["artifact_manifest_sha256"] = sha256_file(artifact_path) or ""
        artifacts[profile] = artifact

        if artifact.get("profile") != profile:
            errors.append(f"{profile} artifact profile={artifact.get('profile')!r}")
        expected_count = parse_int(
            artifact.get("expected_count"),
            f"{profile} artifact expected_count",
            errors,
        )
        if expected_count != EXPECTED_COUNTS[profile]:
            errors.append(
                f"{profile} artifact expected_count={expected_count} "
                f"expected={EXPECTED_COUNTS[profile]}",
            )
        if artifact.get("source_build") != "true":
            errors.append(f"{profile} artifact source_build must be true")

        for key in (
            "git_sha",
            "worktree_dirty",
            "git_status_sha256",
            "model_manifest_sha256",
            "profile_source_sha256",
            "source_build",
        ):
            expected = manifest.get(key)
            actual = artifact.get(key)
            if expected and actual != expected:
                errors.append(f"{profile} artifact {key}={actual!r} expected={expected!r}")
        for key in (
            "git_status_sha256",
            "model_manifest_sha256",
            "model_payload_sha256",
            "profile_source_sha256",
            "target_apk_sha256",
            "test_apk_sha256",
        ):
            if not is_sha256(artifact.get(key)):
                errors.append(f"{profile} artifact {key}={artifact.get(key)!r} is invalid")

        for key, filename in (
            ("target_apk_sha256", "target.apk"),
            ("test_apk_sha256", "test.apk"),
        ):
            actual = sha256_file(artifact_dir / filename)
            expected = artifact.get(key)
            if actual is None:
                errors.append(f"{profile}: missing {filename}")
            elif expected and actual != expected:
                errors.append(f"{profile}: {filename} hash={actual} expected={expected}")

        payload_hash, payload_errors = verify_apk_model_payloads(
            artifact_dir / "target.apk",
            root / "artifacts/model/manifest.json",
        )
        errors.extend(f"{profile}: {item}" for item in payload_errors)
        artifact["verified_model_payload_sha256"] = payload_hash or ""
        if payload_hash and payload_hash != artifact.get("model_payload_sha256"):
            errors.append(
                f"{profile}: verified model payload={payload_hash} "
                f"expected={artifact.get('model_payload_sha256')}",
            )
        if payload_hash:
            verified_payloads.add(payload_hash)

    if len(verified_payloads) > 1:
        errors.append(f"FULL/PRUNE model payload hashes differ: {sorted(verified_payloads)}")
    return artifacts


def validate_measurement(
    row: Mapping[str, Any],
    run_id: str,
    profile: str,
    artifact: Mapping[str, str],
    errors: list[str],
) -> None:
    prefix = run_id or "unknown run"
    exact_values: tuple[tuple[str, object], ...] = (
        ("schemaVersion", 1),
        ("case", CASE),
        ("runId", run_id),
        ("compiledDefaultProfile", profile),
        ("effectiveHotwordCount", EXPECTED_COUNTS.get(profile)),
        ("applicationClass", "android.app.Application"),
        ("demoBootstrapSuppressed", True),
        ("prepareCallCount", 1),
        ("createCallCount", 1),
        ("resourceSamplerEnabled", False),
        ("audioRecognitionStarted", False),
        ("targetApkSha256", artifact.get("target_apk_sha256")),
        ("testApkSha256", artifact.get("test_apk_sha256")),
        ("modelManifestSha256", artifact.get("model_manifest_sha256")),
        ("modelPayloadSha256", artifact.get("model_payload_sha256")),
    )
    for key, expected in exact_values:
        if row.get(key) != expected:
            errors.append(f"{prefix}: report {key}={row.get(key)!r} expected={expected!r}")
    if not is_sha256(row.get("effectiveHotwordSha256")):
        errors.append(
            f"{prefix}: report effectiveHotwordSha256={row.get('effectiveHotwordSha256')!r} "
            "is invalid",
        )
    for metric, _ in METRICS:
        if numeric(row.get(metric)) is None:
            errors.append(f"{prefix}: report {metric}={row.get(metric)!r} is not non-negative")


def load_runs(
    root: Path,
    cycles: int | None,
    manifest: Mapping[str, str],
    artifacts: Mapping[str, Mapping[str, str]],
    errors: list[str],
    thermal_input_issues: list[str],
) -> list[dict[str, Any]]:
    runs_root = root / "runs"
    run_dirs = sorted(path for path in runs_root.glob("*") if path.is_dir()) \
        if runs_root.is_dir() else []
    if cycles is not None:
        expected_dirs = {
            f"c{cycle:02d}-p{position:02d}-{profile}"
            for cycle in range(1, cycles + 1)
            for position, profile in enumerate(EXPECTED_ABBA, start=1)
        }
        actual_dirs = {path.name for path in run_dirs}
        if actual_dirs != expected_dirs:
            errors.append(
                "run directory set mismatch: "
                f"missing={sorted(expected_dirs - actual_dirs)} "
                f"extra={sorted(actual_dirs - expected_dirs)}",
            )
    elif not run_dirs:
        errors.append(f"no run directories found under {runs_root}")

    rows: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    seen_cycle_positions: set[tuple[int, int]] = set()
    for run_dir in run_dirs:
        meta, meta_errors = read_key_values(run_dir / "meta.txt", f"{run_dir.name} meta")
        errors.extend(meta_errors)
        errors.extend(require_fields(meta, RUN_META_FIELDS, f"{run_dir.name} meta"))
        run_id = meta.get("run_id", "")
        profile = meta.get("profile", "")
        cycle = parse_int(meta.get("cycle"), f"{run_dir.name} meta cycle", errors)
        position = parse_int(meta.get("position"), f"{run_dir.name} meta position", errors)
        expected_profile = (
            EXPECTED_ABBA[position - 1]
            if position is not None and 1 <= position <= len(EXPECTED_ABBA)
            else None
        )
        if run_id != run_dir.name:
            errors.append(f"{run_dir.name}: meta run_id={run_id!r}")
        if run_id in seen_run_ids:
            errors.append(f"duplicate run_id {run_id!r}")
        seen_run_ids.add(run_id)
        if cycle is None or cycles is None or not 1 <= cycle <= cycles:
            errors.append(f"{run_dir.name}: cycle={cycle} is outside evidence range")
        if expected_profile is None:
            errors.append(f"{run_dir.name}: position={position} is invalid")
        elif profile != expected_profile:
            errors.append(
                f"{run_dir.name}: position {position} profile={profile!r} "
                f"expected={expected_profile!r}",
            )
        if profile not in PROFILES:
            errors.append(f"{run_dir.name}: unsupported profile={profile!r}")
        if cycle is not None and position is not None and profile in PROFILES:
            canonical_run_id = f"c{cycle:02d}-p{position:02d}-{profile}"
            if run_id != canonical_run_id:
                errors.append(
                    f"{run_dir.name}: canonical run_id={canonical_run_id!r}, got={run_id!r}",
                )
            cycle_position = (cycle, position)
            if cycle_position in seen_cycle_positions:
                errors.append(f"duplicate cycle/position={cycle_position}")
            seen_cycle_positions.add(cycle_position)

        artifact = artifacts.get(profile, {})
        for key in ARTIFACT_FIELDS:
            expected = artifact.get(key)
            actual = meta.get(key)
            if actual != expected:
                errors.append(f"{run_dir.name}: meta {key}={actual!r} expected={expected!r}")
        expected_manifest_hash = artifact.get("artifact_manifest_sha256")
        if meta.get("artifact_manifest_sha256") != expected_manifest_hash:
            errors.append(
                f"{run_dir.name}: meta artifact_manifest_sha256="
                f"{meta.get('artifact_manifest_sha256')!r} expected={expected_manifest_hash!r}",
            )
        if meta.get("source_build") != "true":
            errors.append(f"{run_dir.name}: meta source_build must be true")
        expected_count = parse_int(
            meta.get("expected_count"),
            f"{run_dir.name} meta expected_count",
            errors,
        )
        if profile in EXPECTED_COUNTS and expected_count != EXPECTED_COUNTS[profile]:
            errors.append(
                f"{run_dir.name}: meta expected_count={expected_count} "
                f"expected={EXPECTED_COUNTS[profile]}",
            )
        if manifest.get("source_build") != meta.get("source_build"):
            errors.append(f"{run_dir.name}: meta source_build disagrees with run manifest")

        report, report_errors = read_report(run_dir / "report.jsonl")
        errors.extend(report_errors)
        errors.extend(validate_instrumentation(run_dir))
        cold_load_count, log_errors = validate_metrics_log(run_dir, run_id)
        errors.extend(log_errors)
        thermal, thermal_errors = read_thermal_evidence(run_dir)
        thermal_input_issues.extend(f"{run_dir.name}: {item}" for item in thermal_errors)

        if report is None:
            report = {}
        validate_measurement(report, run_id, profile, artifact, errors)
        row: dict[str, Any] = dict(report)
        row.update(
            {
                "runDir": run_dir.name,
                "meta": dict(meta),
                "cycle": cycle,
                "position": position,
                "profile": profile,
                "coldModelLoadCount": cold_load_count,
                "thermal": thermal,
            },
        )
        rows.append(row)

    expected_total = cycles * len(EXPECTED_ABBA) if cycles is not None else None
    if expected_total is not None and len(rows) != expected_total:
        errors.append(f"expected {expected_total} runs, found {len(rows)}")
    return rows


def grouped_rows(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("profile", ""))].append(row)
    return dict(grouped)


def build_metric_summaries(
    grouped: Mapping[str, Sequence[dict[str, Any]]],
) -> dict[str, dict[str, dict[str, object]]]:
    result: dict[str, dict[str, dict[str, object]]] = {}
    for profile in PROFILES:
        result[profile] = {}
        for metric, _ in METRICS:
            values = [
                value
                for row in grouped.get(profile, [])
                if (value := numeric(row.get(metric))) is not None
            ]
            if values:
                result[profile][metric] = summarize_values(values)
    return result


def index_cycles(rows: Sequence[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    indexed: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        cycle = row.get("cycle")
        position = row.get("position")
        if isinstance(cycle, int) and isinstance(position, int):
            indexed[(cycle, position)] = row
    return indexed


def build_deltas(
    rows: Sequence[dict[str, Any]],
    cycles: int | None,
) -> tuple[
    dict[str, list[dict[str, object]]],
    dict[str, list[dict[str, object]]],
    dict[str, dict[str, dict[str, object]]],
]:
    indexed = index_cycles(rows)
    paired: dict[str, list[dict[str, object]]] = defaultdict(list)
    cycle_means: dict[str, list[dict[str, object]]] = defaultdict(list)
    cycle_numbers = range(1, cycles + 1) if cycles is not None else sorted(
        {cycle for cycle, _ in indexed},
    )
    for cycle in cycle_numbers:
        for pair, full_position, prune_position in (("A", 1, 2), ("B", 4, 3)):
            full = indexed.get((cycle, full_position))
            prune = indexed.get((cycle, prune_position))
            if full is None or prune is None:
                continue
            for metric, _ in METRICS:
                full_value = numeric(full.get(metric))
                prune_value = numeric(prune.get(metric))
                if full_value is None or prune_value is None:
                    continue
                paired[metric].append(
                    {
                        "cycle": cycle,
                        "pair": pair,
                        "full_run": full.get("runId"),
                        "prune_run": prune.get("runId"),
                        "full": full_value,
                        "prune": prune_value,
                        "delta": prune_value - full_value,
                        "delta_percent": (
                            ((prune_value / full_value) - 1.0) * 100.0
                            if full_value else None
                        ),
                    },
                )

        full_rows = [indexed.get((cycle, 1)), indexed.get((cycle, 4))]
        prune_rows = [indexed.get((cycle, 2)), indexed.get((cycle, 3))]
        if any(row is None for row in (*full_rows, *prune_rows)):
            continue
        for metric, _ in METRICS:
            full_values = [numeric(row.get(metric)) for row in full_rows if row is not None]
            prune_values = [numeric(row.get(metric)) for row in prune_rows if row is not None]
            if any(value is None for value in (*full_values, *prune_values)):
                continue
            full_mean = statistics.fmean(value for value in full_values if value is not None)
            prune_mean = statistics.fmean(value for value in prune_values if value is not None)
            cycle_means[metric].append(
                {
                    "cycle": cycle,
                    "full_mean": full_mean,
                    "prune_mean": prune_mean,
                    "delta": prune_mean - full_mean,
                    "delta_percent": (
                        ((prune_mean / full_mean) - 1.0) * 100.0 if full_mean else None
                    ),
                },
            )

    delta_summaries: dict[str, dict[str, dict[str, object]]] = {}
    for metric, _ in METRICS:
        all_entries = paired.get(metric, [])
        metric_summary: dict[str, dict[str, object]] = {}
        for label, entries in (
            ("all_pairs", all_entries),
            ("pair_A", [entry for entry in all_entries if entry["pair"] == "A"]),
            ("pair_B", [entry for entry in all_entries if entry["pair"] == "B"]),
            ("cycle_means", cycle_means.get(metric, [])),
        ):
            deltas = [float(entry["delta"]) for entry in entries]
            if deltas:
                metric_summary[label] = summarize_values(deltas)
        delta_summaries[metric] = metric_summary
    return dict(paired), dict(cycle_means), delta_summaries


def build_thermal_analysis(
    rows: Sequence[dict[str, Any]],
    cycles: int | None,
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    indexed = index_cycles(rows)
    run_rows: list[dict[str, object]] = []
    for row in rows:
        thermal = row.get("thermal", {})
        assert isinstance(thermal, dict)
        output = {
            "run_id": row.get("runId") or row.get("runDir"),
            "cycle": row.get("cycle"),
            "position": row.get("position"),
            "profile": row.get("profile"),
            **thermal,
        }
        run_rows.append(output)
        for phase in ("before", "after"):
            status = thermal.get(f"thermal_status_{phase}")
            ap_status = thermal.get(f"ap_status_{phase}")
            if status is not None and status != 0:
                issues.append(
                    f"{output['run_id']}: Thermal Status {phase}={status}, expected 0",
                )
            if ap_status is not None and ap_status != 0:
                issues.append(f"{output['run_id']}: AP thermal status {phase}={ap_status}")

    pair_rows: list[dict[str, object]] = []
    cycle_numbers = range(1, cycles + 1) if cycles is not None else sorted(
        {cycle for cycle, _ in indexed},
    )
    for cycle in cycle_numbers:
        for pair, full_position, prune_position in (("A", 1, 2), ("B", 4, 3)):
            full = indexed.get((cycle, full_position))
            prune = indexed.get((cycle, prune_position))
            if full is None or prune is None:
                continue
            full_thermal = full.get("thermal", {})
            prune_thermal = prune.get("thermal", {})
            assert isinstance(full_thermal, dict) and isinstance(prune_thermal, dict)
            pair_row: dict[str, object] = {
                "cycle": cycle,
                "pair": pair,
                "full_run": full.get("runId"),
                "prune_run": prune.get("runId"),
            }
            for sensor in ("battery", "ap"):
                full_value = full_thermal.get(f"{sensor}_before_c")
                prune_value = prune_thermal.get(f"{sensor}_before_c")
                if isinstance(full_value, (int, float)) and isinstance(
                    prune_value,
                    (int, float),
                ):
                    signed = float(prune_value) - float(full_value)
                    pair_row[f"{sensor}_before_delta_c"] = signed
                    pair_row[f"{sensor}_before_abs_skew_c"] = abs(signed)
                    if abs(signed) > MAX_PAIRED_START_TEMPERATURE_SKEW_C:
                        issues.append(
                            f"cycle {cycle} pair {pair} {sensor} start skew={abs(signed):.1f} C "
                            f"> {MAX_PAIRED_START_TEMPERATURE_SKEW_C:.1f} C",
                        )
            pair_rows.append(pair_row)

    profile_summaries: dict[str, dict[str, dict[str, object]]] = {}
    for profile in PROFILES:
        profile_summaries[profile] = {}
        selected = [row for row in run_rows if row.get("profile") == profile]
        for field in ("battery_before_c", "battery_after_c", "ap_before_c", "ap_after_c"):
            values = [
                float(value)
                for row in selected
                if isinstance((value := row.get(field)), (int, float))
            ]
            if values:
                profile_summaries[profile][field] = summarize_values(values)

    return {
        "automatic_validation": True,
        "maximum_paired_start_temperature_skew_c": (
            MAX_PAIRED_START_TEMPERATURE_SKEW_C
        ),
        "runs": run_rows,
        "paired_start_comparisons": pair_rows,
        "profile_summaries": profile_summaries,
    }, list(dict.fromkeys(issues))


def format_number(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    return str(value)


def render_markdown(payload: Mapping[str, Any]) -> str:
    summaries = payload["summaries"]
    paired = payload["paired_cycle_deltas"]
    cycle_means = payload["cycle_mean_deltas"]
    thermal = payload["thermal"]
    metric_labels = dict(METRICS)
    lines = [
        "# Police hotword create-only ABBA",
        "",
        f"Status: **{payload['status']}**",
        "",
        "Status scope: formal evidence validity and thermal comparability only; no performance gate ",
        "or absolute create-time threshold is applied.",
        "",
        f"Evidence valid: **{'yes' if payload['evidence_valid'] else 'no'}**",
        "",
        f"Formal clean build: **{'yes' if payload['formal_build'] else 'no'}**",
        "",
        f"Thermally comparable: **{'yes' if payload['thermal_comparable'] else 'no'}**",
        "",
        f"Runs: {payload['run_count']} "
        f"(FULL={payload['profile_counts'].get('full', 0)}, "
        f"PRUNE_UI28={payload['profile_counts'].get('prune_ui28', 0)})",
        "",
        f"p95 policy: omitted below {MIN_P95_SAMPLES} samples per summary.",
        "",
        "| Metric | FULL n / mean / median / min / max / p95 | "
        "PRUNE n / mean / median / min / max / p95 |",
        "| --- | ---: | ---: |",
    ]
    for metric, label in METRICS:
        cells: list[str] = []
        for profile in PROFILES:
            summary = summaries.get(profile, {}).get(metric)
            if not summary:
                cells.append("n/a")
                continue
            p95 = format_number(summary.get("p95")) if "p95" in summary else "omitted"
            cells.append(
                f"{summary['n']} / {summary['mean']:.3f} / {summary['median']:.3f} / "
                f"{summary['min']:.3f} / {summary['max']:.3f} / {p95}",
            )
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")

    lines += [
        "",
        "## Within-cycle pair deltas",
        "",
        "Delta is PRUNE minus FULL. Pair A is positions 1→2; pair B compares position 4 "
        "FULL with position 3 PRUNE.",
        "",
        "| Cycle | Pair | Metric | FULL | PRUNE | Delta | Delta % |",
        "| ---: | :---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for metric, _ in METRICS:
        for entry in paired.get(metric, []):
            percent = entry.get("delta_percent")
            lines.append(
                f"| {entry['cycle']} | {entry['pair']} | {metric_labels[metric]} | "
                f"{entry['full']:.3f} | {entry['prune']:.3f} | {entry['delta']:+.3f} | "
                f"{format_number(percent)}% |",
            )

    lines += [
        "",
        "## Cycle-mean deltas",
        "",
        "| Cycle | Metric | FULL mean | PRUNE mean | Delta | Delta % |",
        "| ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for metric, _ in METRICS:
        for entry in cycle_means.get(metric, []):
            lines.append(
                f"| {entry['cycle']} | {metric_labels[metric]} | "
                f"{entry['full_mean']:.3f} | {entry['prune_mean']:.3f} | "
                f"{entry['delta']:+.3f} | {format_number(entry.get('delta_percent'))}% |",
            )

    lines += [
        "",
        "## Delta summaries",
        "",
        "| Metric | Scope | n | Mean | Median | Min | Max | p95 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric, scopes in payload["delta_summaries"].items():
        for scope, summary in scopes.items():
            p95 = format_number(summary.get("p95")) if "p95" in summary else "omitted"
            lines.append(
                f"| {metric_labels[metric]} | {scope} | {summary['n']} | "
                f"{summary['mean']:.3f} | {summary['median']:.3f} | "
                f"{summary['min']:.3f} | {summary['max']:.3f} | {p95} |",
            )

    lines += [
        "",
        "## Thermal evidence",
        "",
        "| Run | Profile | Battery before→after °C | AP before→after °C | "
        "Thermal status before→after |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in thermal["runs"]:
        lines.append(
            f"| {row['run_id']} | {row['profile']} | "
            f"{format_number(row.get('battery_before_c'))}→"
            f"{format_number(row.get('battery_after_c'))} | "
            f"{format_number(row.get('ap_before_c'))}→"
            f"{format_number(row.get('ap_after_c'))} | "
            f"{row.get('thermal_status_before', 'n/a')}→"
            f"{row.get('thermal_status_after', 'n/a')} |",
        )

    validation_errors = payload["validation_errors"]
    thermal_issues = payload["thermal_issues"]
    if validation_errors:
        lines += ["", "## Evidence validation errors", ""]
        lines.extend(f"- {item}" for item in validation_errors)
    if thermal_issues:
        lines += ["", "## Thermal comparability issues", ""]
        lines.extend(f"- {item}" for item in thermal_issues)
    evidence_limitations = payload["evidence_limitations"]
    if evidence_limitations:
        lines += ["", "## Evidence limitations", ""]
        lines.extend(f"- {item}" for item in evidence_limitations)
    return "\n".join(lines) + "\n"


def print_model_payload_hash(apk: Path, manifest: Path) -> int:
    payload_hash, errors = verify_apk_model_payloads(apk.resolve(), manifest.resolve())
    if errors or payload_hash is None:
        for error in errors or ["model payload inventory is empty"]:
            print(error, file=sys.stderr)
        return 1
    print(payload_hash)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and summarize create-only FULL/PRUNE ABBA evidence",
    )
    parser.add_argument("evidence_root", nargs="?", type=Path)
    parser.add_argument(
        "--expected-cycles",
        type=int,
        help="optional exact cycle-count check (the manifest must always declare at least five)",
    )
    parser.add_argument(
        "--print-model-payload-hash",
        nargs=2,
        metavar=("APK", "MANIFEST"),
        type=Path,
        help="verify APK model entries and print their canonical combined SHA-256",
    )
    args = parser.parse_args()

    if args.print_model_payload_hash is not None:
        if args.evidence_root is not None:
            parser.error("evidence_root cannot be combined with --print-model-payload-hash")
        raise SystemExit(print_model_payload_hash(*args.print_model_payload_hash))
    if args.evidence_root is None:
        parser.error("evidence_root is required unless --print-model-payload-hash is used")
    if args.expected_cycles is not None and args.expected_cycles < MIN_CYCLES:
        parser.error(f"--expected-cycles must be at least {MIN_CYCLES}")

    root = args.evidence_root.resolve()
    validation_errors: list[str] = []
    manifest, manifest_errors = read_key_values(root / "run-manifest.txt", "run manifest")
    validation_errors.extend(manifest_errors)
    cycles = validate_root_manifest(
        root,
        manifest,
        args.expected_cycles,
        validation_errors,
    )
    artifacts = load_artifacts(root, manifest, validation_errors)
    thermal_input_issues: list[str] = []
    rows = load_runs(
        root,
        cycles,
        manifest,
        artifacts,
        validation_errors,
        thermal_input_issues,
    )
    grouped = grouped_rows(rows)

    for profile in PROFILES:
        expected_samples = cycles * 2 if cycles is not None else None
        actual_samples = len(grouped.get(profile, []))
        if expected_samples is not None and actual_samples != expected_samples:
            validation_errors.append(
                f"{profile}: expected {expected_samples} samples, found {actual_samples}",
            )
        hashes = {
            str(row.get("effectiveHotwordSha256"))
            for row in grouped.get(profile, [])
            if is_sha256(row.get("effectiveHotwordSha256"))
        }
        if len(hashes) != 1:
            validation_errors.append(
                f"{profile}: expected one stable effective hotword hash, found={sorted(hashes)}",
            )
        for metric, _ in METRICS:
            sample_count = sum(
                numeric(row.get(metric)) is not None for row in grouped.get(profile, [])
            )
            if sample_count != actual_samples:
                validation_errors.append(
                    f"{profile}/{metric}: {sample_count}/{actual_samples} valid samples",
                )

    hashes_by_profile = {
        profile: {
            str(row.get("effectiveHotwordSha256"))
            for row in grouped.get(profile, [])
            if is_sha256(row.get("effectiveHotwordSha256"))
        }
        for profile in PROFILES
    }
    if all(len(hashes_by_profile[profile]) == 1 for profile in PROFILES):
        if hashes_by_profile["full"] == hashes_by_profile["prune_ui28"]:
            validation_errors.append("FULL and PRUNE_UI28 effective hotword hashes are identical")

    summaries = build_metric_summaries(grouped)
    paired, cycle_means, delta_summaries = build_deltas(rows, cycles)
    if cycles is not None:
        for metric, _ in METRICS:
            pair_count = len(paired.get(metric, []))
            cycle_mean_count = len(cycle_means.get(metric, []))
            if pair_count != cycles * 2:
                validation_errors.append(
                    f"{metric}: expected {cycles * 2} paired deltas, found {pair_count}",
                )
            if cycle_mean_count != cycles:
                validation_errors.append(
                    f"{metric}: expected {cycles} cycle-mean deltas, found {cycle_mean_count}",
                )
    thermal, thermal_comparison_issues = build_thermal_analysis(rows, cycles)
    thermal_issues = list(dict.fromkeys((*thermal_input_issues, *thermal_comparison_issues)))
    validation_errors = list(dict.fromkeys(validation_errors))
    evidence_valid = not validation_errors
    formal_build = manifest.get("worktree_dirty") == "false"
    evidence_limitations: list[str] = []
    if manifest.get("worktree_dirty") == "true":
        evidence_limitations.append(
            "worktree was dirty under PERF_ALLOW_DIRTY=1; evidence is non-formal",
        )
    thermal_complete = all(
        all(
            row.get("thermal", {}).get(field) is not None
            for field in (
                "battery_before_c",
                "battery_after_c",
                "thermal_status_before",
                "thermal_status_after",
                "ap_before_c",
                "ap_after_c",
                "ap_status_before",
                "ap_status_after",
            )
        )
        for row in rows
    ) and bool(rows)
    thermal_comparable = thermal_complete and not thermal_issues
    status = (
        "FAIL"
        if not evidence_valid
        else ("PASS" if thermal_comparable and formal_build else "INCONCLUSIVE")
    )

    payload: dict[str, object] = {
        "schema_version": 1,
        "case": MANIFEST_CASE,
        "status": status,
        "status_scope": (
            "formal evidence validity and thermal comparability only; no performance gate applied"
        ),
        "performance_gate_applied": False,
        "absolute_create_threshold_applied": False,
        "evidence_valid": evidence_valid,
        "formal_build": formal_build,
        "thermal_comparable": thermal_comparable,
        "p95_minimum_samples": MIN_P95_SAMPLES,
        "cycles": cycles,
        "run_count": len(rows),
        "profile_counts": {profile: len(grouped.get(profile, [])) for profile in PROFILES},
        "evidence_bindings": {
            "run_manifest": manifest,
            "artifact_manifests": artifacts,
        },
        "summaries": summaries,
        "paired_cycle_deltas": paired,
        "cycle_mean_deltas": cycle_means,
        "delta_summaries": delta_summaries,
        "thermal": thermal,
        "validation_errors": validation_errors,
        "thermal_issues": thermal_issues,
        "evidence_limitations": evidence_limitations,
    }
    json_path = root / "create-only-summary.json"
    markdown_path = root / "create-only-summary.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "evidence_valid": evidence_valid,
                "thermal_comparable": thermal_comparable,
                "summary": str(json_path),
            },
            ensure_ascii=False,
        ),
    )
    if status == "FAIL":
        raise SystemExit(1)
    if status == "INCONCLUSIVE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
