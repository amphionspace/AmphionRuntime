#!/usr/bin/env python3
"""Aggregate FULL/PRUNE_UI28 Android ABBA performance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


PROFILES = ("full", "prune_ui28")
EXPECTED_COUNTS = {"full": 370, "prune_ui28": 342}
EXPECTED_ABBA = ("full", "prune_ui28", "prune_ui28", "full")

METRICS: tuple[tuple[str, str], ...] = (
    ("prepareMs", "prepare ms"),
    ("createMs", "create ms"),
    ("startToOnStartMs", "start→onStart ms"),
    ("firstPartialMs", "first partial ms"),
    ("firstPartialOverheadMs", "first partial overhead ms"),
    ("finalE2eWallMs", "final E2E wall ms"),
    ("cpuRtf", "process CPU RTF"),
    ("pssPeakDeltaKb", "peak ΔPSS KiB"),
    ("rssPeakDeltaKb", "peak ΔRSS KiB"),
    ("sdk_engineReadyMs", "SDK engine ready ms"),
    ("sdk_firstPartialLatencyMs", "SDK first partial ms"),
    ("sdk_utteranceE2eLatencyMs", "SDK utterance E2E ms"),
    ("sdk_rtf", "SDK RTF"),
    ("sdk_nativeRssMbAtReady", "SDK RSS at ready MiB"),
)

# Candidate p95 must stay below max(FULL * ratio, FULL + absolute noise floor).
RELATIVE_GATES: dict[str, tuple[float, float]] = {
    "prepareMs": (1.05, 20.0),
    "createMs": (1.05, 20.0),
    "startToOnStartMs": (1.05, 20.0),
    "firstPartialMs": (1.05, 20.0),
    "firstPartialOverheadMs": (1.05, 20.0),
    "finalE2eWallMs": (1.05, 20.0),
    "cpuRtf": (1.05, 0.02),
    "pssPeakDeltaKb": (1.05, 10_240.0),
    "rssPeakDeltaKb": (1.05, 10_240.0),
    "sdk_engineReadyMs": (1.05, 20.0),
    "sdk_firstPartialLatencyMs": (1.05, 20.0),
    "sdk_utteranceE2eLatencyMs": (1.05, 20.0),
    "sdk_rtf": (1.05, 0.02),
    "sdk_nativeRssMbAtReady": (1.05, 10.0),
}

ABSOLUTE_GATES: dict[str, float] = {
    "createMs": 500.0,
    "firstPartialOverheadMs": 500.0,
    "cpuRtf": 0.8,
    "sdk_engineReadyMs": 500.0,
}
GATED_METRICS = frozenset((*RELATIVE_GATES.keys(), *ABSOLUTE_GATES.keys()))


def parse_scalar(raw: str) -> Any:
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def parse_meta(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def read_measurement(path: Path) -> tuple[dict[str, Any] | None, int, str | None]:
    if not path.is_file():
        return None, 0, None
    selected: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                return None, 0, f"line {line_number} is not a JSON object"
            if row.get("case") == "police-hotword-performance":
                selected.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, 0, str(error)
    return (selected[-1] if selected else None), len(selected), None


def verify_apk_model_payloads(
    apk_path: Path,
    model_manifest_path: Path,
) -> tuple[str | None, list[str]]:
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
                for entry in sorted(
                    entries,
                    key=lambda item: (
                        str(item.get("name", "")) if isinstance(item, dict) else str(item)
                    ),
                ):
                    name = entry.get("name") if isinstance(entry, dict) else None
                    expected = entry.get("output_sha256") if isinstance(entry, dict) else None
                    if not isinstance(name, str) or not is_sha256(expected):
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


def sha256_zip_entry(apk_path: Path, entry_name: str) -> tuple[str | None, str | None]:
    try:
        digest = hashlib.sha256()
        with zipfile.ZipFile(apk_path) as archive, archive.open(entry_name) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), None
    except KeyError:
        return None, f"APK is missing {entry_name}"
    except (OSError, zipfile.BadZipFile) as error:
        return None, f"cannot inspect APK entry {entry_name}: {error}"


def read_sdk_metrics(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.is_file():
        return {}, False
    text = path.read_text(encoding="utf-8", errors="replace")
    utterances: list[dict[str, Any]] = []
    for line in text.splitlines():
        marker = line.find("kind=UTTERANCE")
        if marker < 0:
            continue
        row: dict[str, Any] = {}
        for token in line[marker:].split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            row[key] = parse_scalar(value)
        utterances.append(row)
    def has_engine_ready(row: dict[str, Any]) -> bool:
        value = row.get("engineReadyMs")
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value >= 0
        )

    first = next(
        (row for row in utterances if has_engine_ready(row)),
        utterances[0] if utterances else {},
    )
    return {f"sdk_{key}": value for key, value in first.items()}, (
        "pooled but config mismatch" in text
    )


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value >= 0
        ):
            values.append(float(value))
    return values


def summarize(rows: list[dict[str, Any]], key: str) -> dict[str, float | int] | None:
    values = numeric_values(rows, key)
    if not values:
        return None
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def read_instrument_result(run_dir: Path) -> tuple[int, bool, str]:
    exit_path = run_dir / "instrument-exit-code.txt"
    try:
        exit_code = int(exit_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        exit_code = -1
    instrument_path = run_dir / "instrument.txt"
    text = instrument_path.read_text(encoding="utf-8", errors="replace") \
        if instrument_path.is_file() else ""
    failure_markers = (
        "FAILURES!!!",
        "INSTRUMENTATION_FAILED",
        "INSTRUMENTATION_ABORTED",
        "shortMsg=Process crashed",
    )
    marker = next((item for item in failure_markers if item in text), "")
    succeeded = exit_code == 0 and "OK (1 test)" in text and not marker
    reason = marker or ("missing OK (1 test)" if "OK (1 test)" not in text else "")
    return exit_code, succeeded, reason


def load_runs(root: Path) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    infrastructure_failures: list[str] = []
    for run_dir in sorted((root / "runs").glob("*")):
        if not run_dir.is_dir():
            continue
        meta = parse_meta(run_dir / "meta.txt")
        exit_code, instrument_succeeded, instrument_reason = read_instrument_result(run_dir)
        measurement, measurement_count, measurement_error = read_measurement(
            run_dir / "report.jsonl",
        )
        if measurement_error:
            infrastructure_failures.append(
                f"{run_dir.name}: invalid performance report: {measurement_error}",
            )
        if measurement_count > 1:
            infrastructure_failures.append(
                f"{run_dir.name}: expected exactly one performance row, found {measurement_count}",
            )
        if measurement is None:
            message = f"{run_dir.name}: missing performance report"
            if instrument_succeeded:
                missing.append(message)
            else:
                infrastructure_failures.append(
                    f"{message}; instrumentation exit={exit_code} reason={instrument_reason}",
                )
            continue
        sdk, pool_mismatch = read_sdk_metrics(run_dir / "metrics.log")
        row = {**measurement, **sdk}
        for key, value in meta.items():
            row[f"meta_{key}"] = value
        row["runDir"] = run_dir.name
        row["measurementCount"] = measurement_count
        row["poolMismatch"] = pool_mismatch
        row["instrumentExitCode"] = exit_code
        row["instrumentSucceeded"] = instrument_succeeded
        row["instrumentReason"] = instrument_reason
        rows.append(row)
    return rows, missing, infrastructure_failures


def validate_evidence_bindings(
    root: Path,
    manifest: dict[str, str],
    failures: list[str],
    inconclusive: list[str],
) -> tuple[dict[str, dict[str, str]], bool]:
    for key in (
        "git_sha",
        "worktree_dirty",
        "git_status_sha256",
        "git_status_after_sha256",
        "audio_asset",
        "audio_sha256",
        "model_manifest_sha256",
        "profile_source_sha256",
    ):
        if not manifest.get(key):
            inconclusive.append(f"run manifest is missing {key}")

    dirty_raw = manifest.get("worktree_dirty")
    formal_build = False
    if dirty_raw == "true":
        inconclusive.append("worktree was dirty: evidence is explicitly non-formal")
    elif dirty_raw != "false":
        inconclusive.append("worktree cleanliness is not bound")

    status_path = root / "git-status.txt"
    status_has_changes = bool(
        status_path.read_text(encoding="utf-8", errors="replace").strip()
    ) if status_path.is_file() else None
    if status_has_changes is not None and status_has_changes != (dirty_raw == "true"):
        failures.append(
            f"worktree_dirty={dirty_raw} disagrees with captured git status",
        )
    status_after_path = root / "git-status-after.txt"
    status_after_has_changes = bool(
        status_after_path.read_text(encoding="utf-8", errors="replace").strip()
    ) if status_after_path.is_file() else None
    if dirty_raw == "false" and status_after_has_changes:
        failures.append("worktree changed during the supposedly clean formal run")
    formal_build = (
        dirty_raw == "false"
        and status_has_changes is False
        and status_after_has_changes is False
    )

    expected_evidence_paths = {
        "audio_evidence": "artifacts/audio/input.wav",
        "model_manifest_evidence": "artifacts/model/manifest.json",
        "profile_source_evidence": "artifacts/profile-source-sha256.txt",
    }
    for key, expected_path in expected_evidence_paths.items():
        actual_path = manifest.get(key)
        if not actual_path:
            inconclusive.append(f"run manifest is missing {key}")
        elif actual_path != expected_path:
            failures.append(f"{key}={manifest.get(key)} expected={expected_path}")

    evidence_files = (
        ("git_status_sha256", root / "git-status.txt"),
        ("git_status_after_sha256", root / "git-status-after.txt"),
        ("audio_sha256", root / "artifacts/audio/input.wav"),
        ("model_manifest_sha256", root / "artifacts/model/manifest.json"),
        ("profile_source_sha256", root / "artifacts/profile-source-sha256.txt"),
    )
    for key, path in evidence_files:
        expected = manifest.get(key)
        actual = sha256_file(path)
        if actual is None:
            inconclusive.append(f"missing bound evidence file for {key}: {path}")
        elif expected and actual != expected:
            failures.append(f"{key} mismatch: manifest={expected} actual={actual}")

    artifact_manifests: dict[str, dict[str, str]] = {}
    shared_keys = (
        "git_sha",
        "worktree_dirty",
        "git_status_sha256",
        "audio_asset",
        "audio_sha256",
        "model_manifest_sha256",
        "profile_source_sha256",
    )
    for profile in PROFILES:
        artifact_dir = root / "artifacts" / profile
        artifact_manifest_path = artifact_dir / "manifest.txt"
        artifact = parse_meta(artifact_manifest_path)
        if not artifact:
            inconclusive.append(f"{profile}: missing artifact manifest")
            continue
        artifact["artifact_manifest_sha256"] = sha256_file(artifact_manifest_path) or ""
        artifact_manifests[profile] = artifact
        if artifact.get("profile") != profile:
            failures.append(
                f"{profile}: artifact manifest profile={artifact.get('profile')}",
            )
        for key in shared_keys:
            expected = manifest.get(key)
            actual = artifact.get(key)
            if not actual:
                inconclusive.append(f"{profile}: artifact manifest missing {key}")
            elif expected and actual != expected:
                failures.append(
                    f"{profile}: artifact {key}={actual} expected={expected}",
                )
        for key, filename in (
            ("target_apk_sha256", "target.apk"),
            ("test_apk_sha256", "test.apk"),
        ):
            expected = artifact.get(key)
            actual = sha256_file(artifact_dir / filename)
            if actual is None:
                inconclusive.append(f"{profile}: missing {filename}")
            elif not expected:
                inconclusive.append(f"{profile}: artifact manifest missing {key}")
            elif actual != expected:
                failures.append(
                    f"{profile}: {filename} hash={actual} expected={expected}",
                )
        model_payload_hash, model_errors = verify_apk_model_payloads(
            artifact_dir / "target.apk",
            root / "artifacts/model/manifest.json",
        )
        artifact["verified_model_payload_sha256"] = model_payload_hash or ""
        failures.extend(f"{profile}: {error}" for error in model_errors)
        audio_asset = manifest.get("audio_asset", "")
        embedded_audio_hash, embedded_audio_error = sha256_zip_entry(
            artifact_dir / "test.apk",
            f"assets/{audio_asset}",
        )
        artifact["verified_audio_sha256"] = embedded_audio_hash or ""
        if embedded_audio_error:
            failures.append(f"{profile}: {embedded_audio_error}")
        elif embedded_audio_hash != manifest.get("audio_sha256"):
            failures.append(
                f"{profile}: embedded audio hash={embedded_audio_hash} "
                f"expected={manifest.get('audio_sha256')}",
            )
    verified_model_hashes = {
        artifact.get("verified_model_payload_sha256")
        for artifact in artifact_manifests.values()
        if artifact.get("verified_model_payload_sha256")
    }
    if len(verified_model_hashes) > 1:
        failures.append(
            f"FULL/PRUNE target APK model payload hashes differ: {sorted(verified_model_hashes)}",
        )
    return artifact_manifests, formal_build


def paired_cycle_deltas(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_cycle_position: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        try:
            key = (int(row["meta_cycle"]), int(row["meta_position"]))
        except (KeyError, TypeError, ValueError):
            continue
        by_cycle_position[key] = row

    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cycle in sorted({key[0] for key in by_cycle_position}):
        for pair, full_position, prune_position in (("A", 1, 2), ("B", 4, 3)):
            full = by_cycle_position.get((cycle, full_position))
            prune = by_cycle_position.get((cycle, prune_position))
            if full is None or prune is None:
                continue
            for metric, _ in METRICS:
                full_values = numeric_values([full], metric)
                prune_values = numeric_values([prune], metric)
                if len(full_values) != 1 or len(prune_values) != 1:
                    continue
                full_value = full_values[0]
                prune_value = prune_values[0]
                result[metric].append(
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
                            if full_value else 0.0
                        ),
                    },
                )
    return dict(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    rows, missing, infrastructure_failures = load_runs(root)
    manifest = parse_meta(root / "run-manifest.txt")
    failures: list[str] = list(infrastructure_failures)
    inconclusive: list[str] = list(missing)
    artifact_manifests, formal_build = validate_evidence_bindings(
        root,
        manifest,
        failures,
        inconclusive,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("compiledDefaultProfile", ""))].append(row)

    try:
        expected_run_count = int(manifest["abba_cycles"]) * len(EXPECTED_ABBA)
        if len(rows) != expected_run_count:
            failures.append(f"expected {expected_run_count} complete runs, found {len(rows)}")
    except (KeyError, TypeError, ValueError):
        inconclusive.append("run manifest is missing a valid abba_cycles value")

    expected_git_sha = manifest.get("git_sha")
    expected_audio_asset = manifest.get("audio_asset")

    for row in rows:
        run_dir = str(row.get("runDir", ""))
        measurement_run_id = str(row.get("runId", ""))
        meta_run_id = str(row.get("meta_run_id", ""))
        meta_profile = str(row.get("meta_profile", ""))
        compiled_profile = str(row.get("compiledDefaultProfile", ""))
        if not run_dir or measurement_run_id != run_dir or meta_run_id != run_dir:
            failures.append(
                f"run identity mismatch: dir={run_dir} meta={meta_run_id} "
                f"measurement={measurement_run_id}",
            )
        try:
            cycle = int(row["meta_cycle"])
            position = int(row["meta_position"])
            expected_run_dir = f"c{cycle:02d}-p{position:02d}-{meta_profile}"
            if run_dir != expected_run_dir:
                failures.append(
                    f"{run_dir}: expected directory identity {expected_run_dir}",
                )
        except (KeyError, TypeError, ValueError):
            failures.append(f"{run_dir or 'unknown'}: invalid cycle/position metadata")
        if meta_profile not in PROFILES or compiled_profile not in PROFILES:
            failures.append(
                f"{run_dir}: invalid profile meta={meta_profile} compiled={compiled_profile}",
            )
        elif meta_profile != compiled_profile:
            failures.append(
                f"{run_dir}: planned profile={meta_profile} compiled={compiled_profile}",
            )

        artifact = artifact_manifests.get(meta_profile)
        if artifact is None:
            inconclusive.append(f"{run_dir}: no bound artifact manifest for {meta_profile}")
        else:
            expected_bindings = {
                "git_sha": artifact.get("git_sha"),
                "worktree_dirty": artifact.get("worktree_dirty"),
                "git_status_sha256": artifact.get("git_status_sha256"),
                "audio_sha256": artifact.get("audio_sha256"),
                "model_manifest_sha256": artifact.get("model_manifest_sha256"),
                "profile_source_sha256": artifact.get("profile_source_sha256"),
                "target_apk_sha256": artifact.get("target_apk_sha256"),
                "test_apk_sha256": artifact.get("test_apk_sha256"),
                "artifact_manifest_sha256": artifact.get("artifact_manifest_sha256"),
            }
            for key, expected in expected_bindings.items():
                actual = row.get(f"meta_{key}")
                if not actual or not expected:
                    inconclusive.append(f"{run_dir}: missing bound {key}")
                elif actual != expected:
                    failures.append(
                        f"{run_dir}: {key}={actual} expected={expected}",
                    )

    cycles: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for row in rows:
        try:
            cycles[int(row["meta_cycle"])].append(
                (int(row["meta_position"]), str(row["compiledDefaultProfile"])),
            )
        except (KeyError, TypeError, ValueError):
            inconclusive.append(f"{row.get('runId', 'unknown')}: missing ABBA metadata")
    for cycle, items in sorted(cycles.items()):
        order = tuple(profile for _, profile in sorted(items))
        if order != EXPECTED_ABBA:
            failures.append(f"cycle {cycle}: expected ABBA {EXPECTED_ABBA}, got {order}")

    for profile in PROFILES:
        profile_rows = grouped.get(profile, [])
        if len(profile_rows) < 4:
            inconclusive.append(f"{profile}: only {len(profile_rows)} runs; require at least 4")
        for row in profile_rows:
            run_id = row.get("runId", "unknown")
            if expected_git_sha and row.get("meta_git_sha") != expected_git_sha:
                failures.append(
                    f"{run_id}: git_sha={row.get('meta_git_sha')} expected={expected_git_sha}",
                )
            if expected_audio_asset and row.get("audioAsset") != expected_audio_asset:
                failures.append(
                    f"{run_id}: audioAsset={row.get('audioAsset')} expected={expected_audio_asset}",
                )
            if expected_audio_asset and row.get("meta_audio_asset") != expected_audio_asset:
                failures.append(
                    f"{run_id}: meta audio={row.get('meta_audio_asset')} "
                    f"expected={expected_audio_asset}",
                )
            if row.get("effectiveHotwordCount") != EXPECTED_COUNTS[profile]:
                failures.append(
                    f"{run_id}: {profile} count={row.get('effectiveHotwordCount')} "
                    f"expected={EXPECTED_COUNTS[profile]}"
                )
            if row.get("instrumentExitCode") != 0:
                failures.append(f"{run_id}: instrumentation exit={row.get('instrumentExitCode')}")
            if not row.get("instrumentSucceeded"):
                failures.append(
                    f"{run_id}: instrumentation did not pass: {row.get('instrumentReason')}",
                )
            if row.get("errors"):
                failures.append(f"{run_id}: recognition errors={row.get('errors')}")
            if row.get("poolMismatch"):
                failures.append(f"{run_id}: recognizer pool mismatch logged")
            if row.get("lastCount") != 1:
                failures.append(f"{run_id}: lastCount={row.get('lastCount')} expected=1")
            if row.get("rssAvailable") is not True:
                inconclusive.append(f"{run_id}: RSS unavailable; zero must not be imputed")

        hotword_hashes = {
            str(row.get("effectiveHotwordSha256"))
            for row in profile_rows
            if is_sha256(row.get("effectiveHotwordSha256"))
        }
        if not hotword_hashes:
            inconclusive.append(
                f"{profile}: effective hotword hash is missing",
            )
        elif len(hotword_hashes) != 1:
            failures.append(
                f"{profile}: effective hotword hashes differ: {sorted(hotword_hashes)}",
            )

    effective_hash_by_profile = {
        profile: {
            str(row.get("effectiveHotwordSha256"))
            for row in grouped.get(profile, [])
            if is_sha256(row.get("effectiveHotwordSha256"))
        }
        for profile in PROFILES
    }
    if all(len(effective_hash_by_profile[profile]) == 1 for profile in PROFILES):
        if effective_hash_by_profile["full"] == effective_hash_by_profile["prune_ui28"]:
            failures.append("FULL and PRUNE_UI28 effective hotword hashes are identical")

    summaries: dict[str, dict[str, Any]] = {}
    for profile in PROFILES:
        summaries[profile] = {
            key: value
            for key, _ in METRICS
            if (value := summarize(grouped.get(profile, []), key)) is not None
        }
        expected_samples = len(grouped.get(profile, []))
        for key in sorted(GATED_METRICS):
            actual_samples = int(summaries[profile].get(key, {}).get("n", 0))
            if actual_samples != expected_samples:
                inconclusive.append(
                    f"{profile}/{key}: {actual_samples}/{expected_samples} non-negative samples; "
                    "every gated metric must be present in every run",
                )

    comparisons: dict[str, dict[str, float]] = {}
    for key, _ in METRICS:
        full = summaries.get("full", {}).get(key)
        prune = summaries.get("prune_ui28", {}).get(key)
        if full is None or prune is None:
            if key.startswith("sdk_"):
                inconclusive.append(f"{key}: missing AmphionMetrics values")
            continue
        full_p95 = float(full["p95"])
        prune_p95 = float(prune["p95"])
        comparisons[key] = {
            "full_p95": full_p95,
            "prune_p95": prune_p95,
            "delta": prune_p95 - full_p95,
            "delta_percent": ((prune_p95 / full_p95) - 1.0) * 100.0 if full_p95 else 0.0,
        }

    for key, (ratio, floor) in RELATIVE_GATES.items():
        comparison = comparisons.get(key)
        if comparison is None:
            inconclusive.append(f"{key}: cannot apply relative gate")
            continue
        full_p95 = comparison["full_p95"]
        prune_p95 = comparison["prune_p95"]
        allowed = max(full_p95 * ratio, full_p95 + floor)
        comparison["allowed_p95"] = allowed
        if prune_p95 > allowed:
            failures.append(
                f"{key}: prune p95={prune_p95:.3f} exceeds allowed={allowed:.3f} "
                f"(full={full_p95:.3f})"
            )

    prune_summary = summaries.get("prune_ui28", {})
    for key, limit in ABSOLUTE_GATES.items():
        metric = prune_summary.get(key)
        if metric is None:
            inconclusive.append(f"{key}: cannot apply absolute gate")
        elif float(metric["p95"]) > limit:
            failures.append(f"{key}: prune p95={metric['p95']:.3f} exceeds {limit:.3f}")

    paired_deltas = paired_cycle_deltas(rows)

    # These are explicit decision blockers, not footnotes. Until automated thermal comparison and
    # split CPU/memory probes exist, a numerically clean run may be useful evidence but cannot PASS.
    inconclusive.append(
        "thermal evidence is archived but not automatically validated; automatic PASS is disabled",
    )
    if rows and all(row.get("cpuIncludesResourceSampler") is True for row in rows):
        inconclusive.append(
            "CPU RTF and PSS/RSS sampling share one run; sampler CPU contaminates process CPU",
        )
    elif rows:
        inconclusive.append("CPU/PSS sampling-coupling metadata is incomplete")

    inconclusive = list(dict.fromkeys(inconclusive))
    status = "FAIL" if failures else ("INCONCLUSIVE" if inconclusive else "PASS")
    payload = {
        "schema_version": 2,
        "status": status,
        "formal_build": formal_build,
        "automatic_thermal_validation": False,
        "cpu_memory_probes_split": False,
        "run_count": len(rows),
        "profile_counts": {profile: len(grouped.get(profile, [])) for profile in PROFILES},
        "evidence_bindings": {
            "run_manifest": manifest,
            "artifact_manifests": artifact_manifests,
        },
        "summaries": summaries,
        "comparisons": comparisons,
        "paired_cycle_deltas": paired_deltas,
        "failures": failures,
        "inconclusive": inconclusive,
        "manual_review": [
            "Compare battery temperature and thermalservice dumps; rerun if profiles differ by >3 C.",
            "Process CPU RTF includes the 50 ms PSS/RSS sampler and is diagnostic until probes split.",
            "SDK RTF is wall-time based for this paced probe and includes paced input waits.",
        ],
    }
    (root / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Police hotword performance ABBA",
        "",
        f"Status: **{status}**",
        "",
        f"Formal clean build: **{'yes' if formal_build else 'no'}**",
        "",
        "Automatic thermal validation: **not implemented (PASS disabled)**",
        "",
        f"Runs: {len(rows)} (FULL={len(grouped.get('full', []))}, "
        f"PRUNE_UI28={len(grouped.get('prune_ui28', []))})",
        "",
        "| Metric | FULL median / p95 | PRUNE median / p95 | p95 delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, label in METRICS:
        full = summaries.get("full", {}).get(key)
        prune = summaries.get("prune_ui28", {}).get(key)
        comparison = comparisons.get(key)
        if full is None or prune is None or comparison is None:
            lines.append(f"| {label} | n/a | n/a | n/a |")
            continue
        lines.append(
            f"| {label} | {full['median']:.3f} / {full['p95']:.3f} | "
            f"{prune['median']:.3f} / {prune['p95']:.3f} | "
            f"{comparison['delta']:+.3f} ({comparison['delta_percent']:+.2f}%) |"
        )
    lines += [
        "",
        "## Within-cycle paired deltas",
        "",
        "Pair A is position 1 FULL versus position 2 PRUNE; pair B is position 4 FULL versus "
        "position 3 PRUNE.",
        "",
        "| Cycle | Pair | Metric | FULL | PRUNE | Delta |",
        "| ---: | :---: | --- | ---: | ---: | ---: |",
    ]
    metric_labels = dict(METRICS)
    for metric, entries in paired_deltas.items():
        for entry in entries:
            lines.append(
                f"| {entry['cycle']} | {entry['pair']} | {metric_labels[metric]} | "
                f"{entry['full']:.3f} | {entry['prune']:.3f} | "
                f"{entry['delta']:+.3f} ({entry['delta_percent']:+.2f}%) |"
            )
    if failures:
        lines += ["", "## Failures", ""] + [f"- {item}" for item in failures]
    if inconclusive:
        lines += ["", "## Inconclusive", ""] + [f"- {item}" for item in inconclusive]
    lines += [
        "",
        "## Manual review",
        "",
        "- Compare battery/thermal dumps; a >3 °C profile skew invalidates the comparison.",
        "- Process CPU RTF currently includes the 50 ms memory sampler; treat it as diagnostic.",
        "- SDK RTF is wall-time based under paced input and includes paced waits.",
    ]
    (root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "summary": str(root / "summary.json")}, ensure_ascii=False))
    if status == "FAIL":
        raise SystemExit(1)
    if status == "INCONCLUSIVE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
