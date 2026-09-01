#!/usr/bin/env python3
"""Track ASR SDK deliveries and render commit-backed release notes."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.delivery.asr_release_evidence_contract import (
    HARMONY_FINISH_COMPAT_MODES,
    HARMONY_RELEASE_MODES,
    MIN_LONG_RUN_SECONDS,
    SCHEMA_VERSION as EVIDENCE_SCHEMA_VERSION,
)


SCHEMA_VERSION = 2
PLATFORMS = {"android": "Android", "harmony": "HarmonyOS"}
COMMON_SOURCE_PREFIXES = (
    "asr/common/",
    "shared/",
    "third_party/patches/sherpa-amphion/",
    "tools/delivery/",
)
PLATFORM_SOURCE_PREFIXES = {
    "android": (
        "asr/android/",
        "asr/tools/delivery/",
        "asr/tools/04_build_android_so.sh",
        "asr/tools/05_package_aar_libs.sh",
        "asr/tools/08_pack_sdk_assets.sh",
        "asr/tools/requirements-android-ort.txt",
        "asr/tools/license/issue_android_asr_eval.sh",
        "asr/tools/verify_packed_model_assets.py",
        "asr/tools/tests/test_verify_packed_model_assets.py",
    ),
    "harmony": (
        "asr/harmony/",
        "delivery/harmony-dingqiao/",
        "asr/tools/demo-model/",
        "asr/tools/04_build_harmony_so.sh",
        "asr/tools/05_package_har_libs.sh",
        "asr/tools/08_pack_harmony_assets.sh",
        "asr/tools/build_harmony_asset_manifest.py",
        "asr/tools/convert_harmony_ort.py",
        "asr/tools/requirements-harmony-ort.txt",
        "asr/tools/sync_harmony_police_assets.py",
        "asr/tools/test_harmony_police_parity.py",
        "asr/tools/tests/test_build_harmony_asset_manifest.py",
        "asr/tools/tests/test_convert_harmony_ort.py",
        "asr/tools/tests/test_harmony_",
        "asr/tools/license/issue_harmony_asr_eval.sh",
    ),
}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLATFORM_SCOPE = re.compile(r"^[a-z0-9-]+(?:!)?\((android|harmony)\)(?:!)?:")
REQUIRED_ENTRY_FIELDS = {
    "platform",
    "version",
    "source_commit",
    "delivered_at",
    "artifact",
    "artifact_sha256",
    "artifact_size_bytes",
    "provenance_sha256",
}
EVIDENCE_ENTRY_FIELDS = {"evidence_report", "evidence_sha256"}
INTEGRATION_ENTRY_FIELDS = {"integration_commit"}
ALLOWED_ENTRY_FIELDS = REQUIRED_ENTRY_FIELDS | EVIDENCE_ENTRY_FIELDS | INTEGRATION_ENTRY_FIELDS


class ReleaseTrackerError(RuntimeError):
    pass


def _run_git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip()
        raise ReleaseTrackerError(f"git {' '.join(args)} failed: {detail}") from error
    return result.stdout.strip()


def resolve_commit(repo: Path, commit: str) -> str:
    resolved = _run_git(repo, "rev-parse", f"{commit}^{{commit}}")
    if not FULL_COMMIT.fullmatch(resolved):
        raise ReleaseTrackerError(f"invalid resolved commit: {resolved}")
    return resolved


def load_history(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseTrackerError(f"cannot read release history {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseTrackerError(f"release history schema_version must be {SCHEMA_VERSION}")
    deliveries = payload.get("deliveries")
    if not isinstance(deliveries, list):
        raise ReleaseTrackerError("release history deliveries must be a list")
    seen = set()
    latest_versions: Dict[str, tuple[int, int, int]] = {}
    for index, entry in enumerate(deliveries):
        if (
            not isinstance(entry, dict)
            or not REQUIRED_ENTRY_FIELDS.issubset(entry)
            or not set(entry).issubset(ALLOWED_ENTRY_FIELDS)
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid fields")
        evidence_fields = EVIDENCE_ENTRY_FIELDS.intersection(entry)
        if evidence_fields and evidence_fields != EVIDENCE_ENTRY_FIELDS:
            raise ReleaseTrackerError(
                f"delivery #{index + 1} evidence fields must be recorded together"
            )
        platform = entry["platform"]
        version = entry["version"]
        key = (platform, version)
        if platform not in PLATFORMS:
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid platform {platform!r}")
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid version {version!r}")
        version_key = _semver_key(version)
        previous_key = latest_versions.get(platform)
        if previous_key is not None and version_key <= previous_key:
            raise ReleaseTrackerError(
                f"{platform} delivery versions must strictly increase in ledger order"
            )
        latest_versions[platform] = version_key
        if key in seen:
            raise ReleaseTrackerError(f"{platform} {version} is already recorded")
        seen.add(key)
        if not isinstance(entry["source_commit"], str) or not FULL_COMMIT.fullmatch(
            entry["source_commit"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid source_commit")
        if "integration_commit" in entry and (
            not isinstance(entry["integration_commit"], str)
            or not FULL_COMMIT.fullmatch(entry["integration_commit"])
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid integration_commit")
        if not isinstance(entry["delivered_at"], str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", entry["delivered_at"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid delivered_at")
        if not isinstance(entry["artifact"], str) or not entry["artifact"]:
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid artifact")
        if Path(entry["artifact"]).name != entry["artifact"] or not entry["artifact"].endswith(
            ".zip"
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} artifact must be a ZIP basename")
        if not isinstance(entry["artifact_sha256"], str) or not SHA256.fullmatch(
            entry["artifact_sha256"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid artifact_sha256")
        if not isinstance(entry["artifact_size_bytes"], int) or entry[
            "artifact_size_bytes"
        ] <= 0:
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid artifact_size_bytes")
        if not isinstance(entry["provenance_sha256"], str) or not SHA256.fullmatch(
            entry["provenance_sha256"]
        ):
            raise ReleaseTrackerError(f"delivery #{index + 1} has invalid provenance_sha256")
        if evidence_fields:
            evidence_report = entry["evidence_report"]
            if not isinstance(evidence_report, str):
                raise ReleaseTrackerError(f"delivery #{index + 1} has invalid evidence_report")
            evidence_path = Path(evidence_report)
            if (
                evidence_path.is_absolute()
                or ".." in evidence_path.parts
                or not evidence_report.startswith("delivery/")
                or evidence_path.name != "report.json"
            ):
                raise ReleaseTrackerError(
                    f"delivery #{index + 1} evidence_report must be a safe repo-relative report.json"
                )
            if not isinstance(entry["evidence_sha256"], str) or not SHA256.fullmatch(
                entry["evidence_sha256"]
            ):
                raise ReleaseTrackerError(f"delivery #{index + 1} has invalid evidence_sha256")
    return payload


def _semver_key(version: str) -> tuple[int, int, int]:
    if not SEMVER.fullmatch(version):
        raise ReleaseTrackerError(f"version must be SemVer MAJOR.MINOR.PATCH: {version}")
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def _previous_delivery(history: Dict[str, Any], platform: str) -> Optional[Dict[str, str]]:
    matches = [entry for entry in history["deliveries"] if entry["platform"] == platform]
    return matches[-1] if matches else None


def _require_newer_version(
    platform: str, version: str, previous: Optional[Dict[str, str]]
) -> None:
    requested = _semver_key(version)
    if previous is None:
        return
    previous_key = _semver_key(previous["version"])
    if requested == previous_key:
        raise ReleaseTrackerError(
            f"{platform} {version} is already recorded; the next release must be "
            f"newer than {previous['version']}"
        )
    if requested < previous_key:
        raise ReleaseTrackerError(
            f"{platform} release version {version} must be newer than {previous['version']}"
        )


def verify_next_version(*, history_path: Path, platform: str, version: str) -> None:
    if platform not in PLATFORMS:
        raise ReleaseTrackerError(f"unsupported platform: {platform}")
    previous = _previous_delivery(load_history(history_path), platform)
    _require_newer_version(platform, version, previous)


def verify_current_version(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
) -> None:
    if platform not in PLATFORMS:
        raise ReleaseTrackerError(f"unsupported platform: {platform}")
    _semver_key(version)
    latest = _previous_delivery(load_history(history_path), platform)
    if latest is None or latest["version"] != version:
        recorded = "none" if latest is None else latest["version"]
        raise ReleaseTrackerError(
            f"{platform} runtime version {version} does not match latest recorded delivery {recorded}"
        )
    recorded_commit = resolve_commit(repo, latest["source_commit"])
    current = resolve_commit(repo, source_commit)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", recorded_commit, current], cwd=repo
    )
    if ancestor.returncode != 0:
        raise ReleaseTrackerError(
            f"latest recorded {platform} delivery commit {recorded_commit} "
            f"is not an ancestor of {current}"
        )


def verify_packaging_version(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
) -> str:
    if platform not in PLATFORMS:
        raise ReleaseTrackerError(f"unsupported platform: {platform}")
    requested = _semver_key(version)
    latest = _previous_delivery(load_history(history_path), platform)
    if latest is not None and requested == _semver_key(latest["version"]):
        recorded_commit = resolve_commit(repo, latest["source_commit"])
        package_commit = resolve_commit(repo, source_commit)
        if package_commit != recorded_commit:
            raise ReleaseTrackerError(
                f"recorded {platform} {version} must be rebuilt from exact source "
                f"{recorded_commit}, not {package_commit}"
            )
        return "current"
    _require_newer_version(platform, version, latest)
    return "next"


def verify_recorded_packaging_version(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
) -> None:
    state = verify_packaging_version(
        repo=repo,
        history_path=history_path,
        platform=platform,
        version=version,
        source_commit=source_commit,
    )
    if state != "current":
        raise ReleaseTrackerError(
            f"{platform} {version} is not an exact recorded delivery; "
            "package it as PREVIEW / NON-CANONICAL until the release gate and ledger are complete"
        )


def _changed_paths(repo: Path, commit: str) -> List[str]:
    return _run_git(
        repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit
    ).splitlines()


def _commit_affects_platform(
    repo: Path, commit: str, subject: str, history_path: Path, platform: str
) -> bool:
    scoped_platform = PLATFORM_SCOPE.match(subject)
    if scoped_platform is not None and scoped_platform.group(1) != platform:
        return False
    try:
        relative_history = history_path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        relative_history = ""
    changed = _changed_paths(repo, commit)
    if not changed or (relative_history and set(changed) == {relative_history}):
        return False
    prefixes = COMMON_SOURCE_PREFIXES + PLATFORM_SOURCE_PREFIXES[platform]
    return any(path.startswith(prefixes) for path in changed)


def render_changelog(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
) -> str:
    if platform not in PLATFORMS:
        raise ReleaseTrackerError(f"unsupported platform: {platform}")
    if not SEMVER.fullmatch(version):
        raise ReleaseTrackerError(f"version must be SemVer MAJOR.MINOR.PATCH: {version}")
    history = load_history(history_path)
    current = resolve_commit(repo, source_commit)
    deliveries = [entry for entry in history["deliveries"] if entry["platform"] == platform]
    latest = deliveries[-1] if deliveries else None
    if latest is not None and latest["version"] == version:
        verify_packaging_version(
            repo=repo,
            history_path=history_path,
            platform=platform,
            version=version,
            source_commit=source_commit,
        )
        previous = deliveries[-2] if len(deliveries) > 1 else None
    else:
        verify_next_version(history_path=history_path, platform=platform, version=version)
        previous = latest

    lines = [
        "# ASR SDK 更新日志",
        "",
        f"## {PLATFORMS[platform]} ASR SDK {version}",
        "",
        f"- 构建 commit：`{current}`",
    ]
    if previous is None:
        lines.extend(["- 上一交付：无", "", "### Commit 变更", ""])
        commit_range = current
    else:
        previous_commit = resolve_commit(repo, previous["source_commit"])
        previous_range_commit = resolve_commit(
            repo, previous.get("integration_commit", previous["source_commit"])
        )
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", previous_range_commit, current], cwd=repo
        )
        if ancestor.returncode != 0:
            raise ReleaseTrackerError(
                f"previous delivery integration commit {previous_range_commit} "
                f"is not an ancestor of {current}"
            )
        lines.extend(
            [
                f"- 上一交付：{previous['version']} (`{previous_commit}`)",
                "",
                "### Commit 变更",
                "",
            ]
        )
        commit_range = f"{previous_range_commit}..{current}"

    raw_log = _run_git(repo, "log", "--reverse", "--format=%H%x1f%s", commit_range)
    changes: List[str] = []
    for row in raw_log.splitlines():
        if not row:
            continue
        commit, subject = row.split("\x1f", 1)
        if not _commit_affects_platform(repo, commit, subject, history_path, platform):
            continue
        changes.append(f"- `{commit[:12]}` {subject}")
    lines.extend(changes or ["- 本次交付没有新的源码 commit。"])
    return "\n".join(lines) + "\n"


def _read_provenance(payload_bytes: bytes, name: str) -> Dict[str, str]:
    if name.lower().endswith(".json"):
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
            return {
                "version": payload["delivery_version"],
                "commit": payload["source"]["commit"],
            }
        except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ReleaseTrackerError(f"invalid Harmony provenance in {name}: {error}") from error
    try:
        fields = {}
        for line in payload_bytes.decode("utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key] = value
        return {"version": fields["delivery_version"], "commit": fields["git_commit_full"]}
    except (UnicodeError, KeyError) as error:
        raise ReleaseTrackerError(f"invalid Android provenance in {name}: {error}") from error


def _read_artifact_provenance(artifact_path: Path, platform: str) -> tuple[Dict[str, str], bytes]:
    if not artifact_path.is_file() or artifact_path.suffix.lower() != ".zip":
        raise ReleaseTrackerError("artifact must be an existing final ZIP")
    suffix = "VERSION.txt" if platform == "android" else "docs/BUILD_PROVENANCE.json"
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise ReleaseTrackerError(f"artifact ZIP CRC failed: {bad}")
            matches = [name for name in archive.namelist() if name.endswith(f"/{suffix}")]
            if len(matches) != 1:
                raise ReleaseTrackerError(
                    f"artifact must contain exactly one {suffix}, found {len(matches)}"
                )
            name = matches[0]
            payload = archive.read(name)
    except (OSError, zipfile.BadZipFile) as error:
        raise ReleaseTrackerError(f"cannot read artifact ZIP {artifact_path}: {error}") from error
    return _read_provenance(payload, name), payload


def _history_lock_path(history_path: Path) -> Path:
    identity = hashlib.sha256(str(history_path.resolve()).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"amphion-asr-release-history-{identity}.lock"


def _write_history_atomic(history_path: Path, history: Dict[str, Any]) -> None:
    temporary_path: Optional[Path] = None
    original_mode = stat.S_IMODE(history_path.stat().st_mode)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=history_path.parent,
            prefix=f".{history_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(history, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, history_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def attach_evidence(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    report_path: Path,
) -> Dict[str, Any]:
    if report_path.is_symlink():
        raise ReleaseTrackerError("evidence report must not be a symlink")
    report_path = report_path.resolve()
    try:
        relative_report = report_path.relative_to(repo.resolve()).as_posix()
    except ValueError as error:
        raise ReleaseTrackerError("evidence report must be inside the repository") from error
    if (
        not report_path.is_file()
        or report_path.name != "report.json"
        or not relative_report.startswith("delivery/")
    ):
        raise ReleaseTrackerError("evidence report must be an existing report.json")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseTrackerError(f"cannot read evidence report: {error}") from error
    if not isinstance(report, dict) or report.get("overall_status") != "PASS":
        raise ReleaseTrackerError("release evidence report must have overall_status=PASS")
    report_digest = hashlib.sha256(report_path.read_bytes()).hexdigest()

    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _history_lock_path(history_path)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        history = load_history(history_path)
        matches = [
            delivery
            for delivery in history["deliveries"]
            if delivery["platform"] == platform and delivery["version"] == version
        ]
        if len(matches) != 1:
            raise ReleaseTrackerError(f"delivery {platform} {version} is not recorded")
        entry = matches[0]
        if EVIDENCE_ENTRY_FIELDS.intersection(entry):
            raise ReleaseTrackerError(f"delivery {platform} {version} already has evidence")
        _validate_evidence_report(entry, report)
        _validate_evidence_files(report_path, report)
        entry["evidence_report"] = relative_report
        entry["evidence_sha256"] = report_digest
        _write_history_atomic(history_path, history)
        return dict(entry)


def verify_history_evidence(*, repo: Path, history_path: Path) -> None:
    history = load_history(history_path)
    for entry in history["deliveries"]:
        if not EVIDENCE_ENTRY_FIELDS.issubset(entry):
            continue
        report = repo.resolve() / entry["evidence_report"]
        if report.is_symlink() or not report.is_file():
            raise ReleaseTrackerError(
                f"evidence report is missing for {entry['platform']} {entry['version']}: {report}"
            )
        try:
            report.resolve().relative_to(repo.resolve())
        except ValueError as error:
            raise ReleaseTrackerError(
                f"evidence report escapes the repository for {entry['platform']} {entry['version']}"
            ) from error
        actual = hashlib.sha256(report.read_bytes()).hexdigest()
        if actual != entry["evidence_sha256"]:
            raise ReleaseTrackerError(
                f"evidence digest mismatch for {entry['platform']} {entry['version']}"
            )
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseTrackerError(f"cannot read evidence report {report}: {error}") from error
        _validate_evidence_report(entry, payload)
        _validate_evidence_files(report, payload)


def _validate_evidence_report(entry: Dict[str, Any], report: Any) -> None:
    if not isinstance(report, dict) or report.get("overall_status") != "PASS":
        raise ReleaseTrackerError("release evidence report must have overall_status=PASS")
    expected = {
        "release_version": entry["version"],
        "source_commit": entry["source_commit"],
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise ReleaseTrackerError(f"release evidence {field} does not match delivery ledger")
    artifact = report.get("release_artifact")
    if not isinstance(artifact, dict):
        raise ReleaseTrackerError("release evidence artifact is missing")
    expected_artifact = {
        "name": entry["artifact"],
        "sha256": entry["artifact_sha256"],
        "size_bytes": entry["artifact_size_bytes"],
        "provenance_sha256": entry["provenance_sha256"],
    }
    for field, value in expected_artifact.items():
        if artifact.get(field) != value:
            raise ReleaseTrackerError(
                f"release evidence artifact {field} does not match delivery ledger"
            )
    if entry["platform"] == "harmony":
        if report.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
            raise ReleaseTrackerError("Harmony release evidence has an unsupported schema")
        if report.get("required_modes") != list(HARMONY_RELEASE_MODES):
            raise ReleaseTrackerError("Harmony release evidence required_modes are incomplete")
        modes = report.get("modes")
        mode_names = (
            [item.get("mode") for item in modes if isinstance(item, dict)]
            if isinstance(modes, list)
            else []
        )
        if mode_names != list(HARMONY_RELEASE_MODES):
            raise ReleaseTrackerError("Harmony release evidence modes are incomplete")
        long_run = report.get("long_run")
        if (
            not isinstance(long_run, dict)
            or long_run.get("mode") not in HARMONY_RELEASE_MODES
            or not isinstance(long_run.get("duration_seconds"), (int, float))
            or long_run["duration_seconds"] <= MIN_LONG_RUN_SECONDS
        ):
            raise ReleaseTrackerError("Harmony release evidence has no run longer than 60 seconds")


def _validate_evidence_files(report_path: Path, report: Dict[str, Any]) -> None:
    evidence_root = report_path.parent.resolve()
    declared = {"report.json"}

    def verify_entry(entry: Any, prefix: str = "") -> Path:
        if not isinstance(entry, dict):
            raise ReleaseTrackerError("release evidence contains an invalid file manifest")
        relative = entry.get("path")
        if not isinstance(relative, str):
            raise ReleaseTrackerError("release evidence file manifest has no path")
        joined = Path(prefix) / relative
        if joined.is_absolute() or ".." in joined.parts:
            raise ReleaseTrackerError(f"unsafe release evidence file path: {joined}")
        normalized = joined.as_posix()
        if normalized in declared:
            raise ReleaseTrackerError(f"duplicate release evidence file path: {normalized}")
        path = evidence_root / joined
        if path.is_symlink() or not path.is_file():
            raise ReleaseTrackerError(f"release evidence file is missing: {normalized}")
        try:
            path.resolve().relative_to(evidence_root)
        except ValueError as error:
            raise ReleaseTrackerError(
                f"release evidence file escapes its archive: {normalized}"
            ) from error
        if entry.get("size_bytes") != path.stat().st_size:
            raise ReleaseTrackerError(f"release evidence size mismatch: {normalized}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if entry.get("sha256") != actual:
            raise ReleaseTrackerError(f"release evidence digest mismatch: {normalized}")
        declared.add(normalized)
        return path

    verify_entry(report.get("android_tests_artifact"))
    if report.get("finish_compat_summary") is not None:
        verify_entry(report.get("finish_compat_summary"))
    if report.get("numeric_identity_gate") is not None:
        verify_entry(report.get("numeric_identity_gate"))
    release_version = report.get("release_version")
    harmony_archive = (
        isinstance(report.get("required_modes"), list)
        and isinstance(release_version, str)
        and _semver_key(release_version) >= _semver_key("0.3.6")
    )
    finish_runs = report.get("finish_compat_runs", [])
    if not isinstance(finish_runs, list):
        raise ReleaseTrackerError("release evidence finish compatibility runs must be a list")
    finish_modes = []
    for run in finish_runs:
        if not isinstance(run, dict) or not isinstance(run.get("mode"), str):
            raise ReleaseTrackerError("release evidence contains an invalid finish compatibility run")
        mode = run["mode"]
        finish_modes.append(mode)
        files = run.get("files")
        if not isinstance(files, list) or not files:
            raise ReleaseTrackerError(
                f"release evidence finish compatibility run has no files: {mode}"
            )
        for entry in files:
            verify_entry(entry, f"finish-compat-runs/{mode}")
    if harmony_archive and finish_modes != list(HARMONY_FINISH_COMPAT_MODES):
        raise ReleaseTrackerError("release evidence finish compatibility modes are incomplete")
    android_results = report.get("android_test_results")
    if not isinstance(android_results, list) or not android_results:
        raise ReleaseTrackerError("release evidence has no Android test result manifests")
    for entry in android_results:
        xml_path = verify_entry(entry)
        _validate_android_test_xml(xml_path)
    for mode in report.get("modes", []):
        if not isinstance(mode, dict) or not isinstance(mode.get("mode"), str):
            raise ReleaseTrackerError("release evidence contains an invalid mode manifest")
        prefix = f"modes/{mode['mode']}"
        files = mode.get("files")
        if not isinstance(files, list) or not files:
            raise ReleaseTrackerError(f"release evidence mode has no files: {mode['mode']}")
        for entry in files:
            verify_entry(entry, prefix)
    diagnostics = report.get("diagnostics", [])
    if not isinstance(diagnostics, list):
        raise ReleaseTrackerError("release evidence diagnostics must be a list")
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict) or not isinstance(diagnostic.get("path"), str):
            raise ReleaseTrackerError("release evidence contains an invalid diagnostic manifest")
        files = diagnostic.get("files")
        if not isinstance(files, list) or not files:
            raise ReleaseTrackerError("release evidence diagnostic has no files")
        for entry in files:
            verify_entry(entry, diagnostic["path"])
    actual = {
        path.relative_to(evidence_root).as_posix()
        for path in evidence_root.rglob("*")
        if path.is_file()
    }
    symlinks = [path for path in evidence_root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise ReleaseTrackerError(
            f"release evidence archive contains a symlink: {symlinks[0].relative_to(evidence_root)}"
        )
    if actual != declared:
        extra = sorted(actual - declared)
        missing = sorted(declared - actual)
        detail = extra[0] if extra else missing[0]
        raise ReleaseTrackerError(f"release evidence contains an unmanifested file: {detail}")


def _validate_android_test_xml(xml_path: Path) -> None:
    try:
        suite = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ReleaseTrackerError(
            f"release evidence has invalid Android test XML: {xml_path.name}"
        ) from error
    if suite.tag != "testsuite" or suite.attrib.get("hostname") != "redacted":
        raise ReleaseTrackerError(
            f"release evidence has invalid Android testsuite metadata: {xml_path.name}"
        )
    for field in ("tests", "failures", "errors", "skipped"):
        try:
            int(suite.attrib.get(field, "0"))
        except ValueError as error:
            raise ReleaseTrackerError(
                f"release evidence has invalid Android testsuite counts: {xml_path.name}"
            ) from error


def record_delivery(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
    delivered_at: str,
    artifact_path: Path,
) -> Dict[str, Any]:
    entry = build_delivery_entry(
        repo=repo,
        platform=platform,
        version=version,
        source_commit=source_commit,
        delivered_at=delivered_at,
        artifact_path=artifact_path,
    )
    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _history_lock_path(history_path)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        history = load_history(history_path)
        previous = _previous_delivery(history, platform)
        _require_newer_version(platform, version, previous)
        history["deliveries"].append(entry)
        _write_history_atomic(history_path, history)
    return entry


def build_delivery_entry(
    *,
    repo: Path,
    platform: str,
    version: str,
    source_commit: str,
    delivered_at: str,
    artifact_path: Path,
) -> Dict[str, Any]:
    if platform not in PLATFORMS:
        raise ReleaseTrackerError(f"unsupported platform: {platform}")
    if not SEMVER.fullmatch(version):
        raise ReleaseTrackerError(f"version must be SemVer MAJOR.MINOR.PATCH: {version}")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", delivered_at):
        raise ReleaseTrackerError(f"delivered_at must be YYYY-MM-DD: {delivered_at}")
    resolved = resolve_commit(repo, source_commit)
    artifact_path = artifact_path.resolve()
    provenance, provenance_payload = _read_artifact_provenance(artifact_path, platform)
    if provenance["version"] != version:
        raise ReleaseTrackerError(
            f"provenance version {provenance['version']} does not match {version}"
        )
    provenance_commit = resolve_commit(repo, provenance["commit"])
    if provenance_commit != resolved:
        raise ReleaseTrackerError(
            f"provenance commit {provenance_commit} does not match {resolved}"
        )
    artifact = artifact_path.name
    artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    provenance_digest = hashlib.sha256(provenance_payload).hexdigest()
    entry = {
        "platform": platform,
        "version": version,
        "source_commit": resolved,
        "delivered_at": delivered_at,
        "artifact": artifact,
        "artifact_sha256": artifact_digest,
        "artifact_size_bytes": artifact_path.stat().st_size,
        "provenance_sha256": provenance_digest,
    }
    return entry


def record_delivery_with_evidence(
    *,
    repo: Path,
    history_path: Path,
    platform: str,
    version: str,
    source_commit: str,
    delivered_at: str,
    artifact_path: Path,
    report_path: Path,
) -> Dict[str, Any]:
    entry = build_delivery_entry(
        repo=repo,
        platform=platform,
        version=version,
        source_commit=source_commit,
        delivered_at=delivered_at,
        artifact_path=artifact_path,
    )
    if report_path.is_symlink():
        raise ReleaseTrackerError("evidence report must not be a symlink")
    report_path = report_path.resolve()
    try:
        relative_report = report_path.relative_to(repo.resolve()).as_posix()
    except ValueError as error:
        raise ReleaseTrackerError("evidence report must be inside the repository") from error
    if not report_path.is_file() or report_path.name != "report.json" or not relative_report.startswith("delivery/"):
        raise ReleaseTrackerError("evidence report must be an existing delivery report.json")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseTrackerError(f"cannot read evidence report: {error}") from error
    _validate_evidence_report(entry, report)
    _validate_evidence_files(report_path, report)
    entry["evidence_report"] = relative_report
    entry["evidence_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()

    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _history_lock_path(history_path)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        history = load_history(history_path)
        previous = _previous_delivery(history, platform)
        _require_newer_version(platform, version, previous)
        history["deliveries"].append(entry)
        _write_history_atomic(history_path, history)
    return entry


def _default_repo() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=_default_repo())
    parser.add_argument("--history", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    changelog = subparsers.add_parser("changelog")
    changelog.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    changelog.add_argument("--version", required=True)
    changelog.add_argument("--source-commit", default="HEAD")
    changelog.add_argument("--output", type=Path, required=True)

    verify_next = subparsers.add_parser("verify-next")
    verify_next.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    verify_next.add_argument("--version", required=True)

    verify_current = subparsers.add_parser("verify-current")
    verify_current.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    verify_current.add_argument("--version", required=True)
    verify_current.add_argument("--source-commit", default="HEAD")

    verify_package = subparsers.add_parser("verify-package")
    verify_package.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    verify_package.add_argument("--version", required=True)
    verify_package.add_argument("--source-commit", default="HEAD")
    verify_package.add_argument(
        "--require-recorded",
        action="store_true",
        help="require an exact version and source_commit match in the delivery ledger",
    )

    record = subparsers.add_parser("record")
    record.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    record.add_argument("--version", required=True)
    record.add_argument("--source-commit", default="HEAD")
    record.add_argument("--delivered-at", required=True)
    record.add_argument("--artifact", type=Path, required=True)

    attach = subparsers.add_parser("attach-evidence")
    attach.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    attach.add_argument("--version", required=True)
    attach.add_argument("--report", type=Path, required=True)

    record_evidence = subparsers.add_parser("record-evidence")
    record_evidence.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    record_evidence.add_argument("--version", required=True)
    record_evidence.add_argument("--source-commit", default="HEAD")
    record_evidence.add_argument("--delivered-at", required=True)
    record_evidence.add_argument("--artifact", type=Path, required=True)
    record_evidence.add_argument("--report", type=Path, required=True)

    subparsers.add_parser("verify-evidence")

    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    history_path = (args.history or repo / "delivery/asr-sdk-release-history.json").resolve()
    try:
        if args.command == "changelog":
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                render_changelog(
                    repo=repo,
                    history_path=history_path,
                    platform=args.platform,
                    version=args.version,
                    source_commit=args.source_commit,
                ),
                encoding="utf-8",
            )
            print(f"[OK] wrote release changelog: {output}")
        elif args.command == "verify-next":
            verify_next_version(
                history_path=history_path,
                platform=args.platform,
                version=args.version,
            )
            print(f"[OK] {args.platform} {args.version} is newer than the delivery ledger")
        elif args.command == "verify-current":
            verify_current_version(
                repo=repo,
                history_path=history_path,
                platform=args.platform,
                version=args.version,
                source_commit=args.source_commit,
            )
            print(f"[OK] {args.platform} {args.version} matches the latest delivery ledger")
        elif args.command == "verify-package":
            if args.require_recorded:
                verify_recorded_packaging_version(
                    repo=repo,
                    history_path=history_path,
                    platform=args.platform,
                    version=args.version,
                    source_commit=args.source_commit,
                )
                print(
                    f"[OK] {args.platform} {args.version} packaging source is exactly recorded"
                )
            else:
                state = verify_packaging_version(
                    repo=repo,
                    history_path=history_path,
                    platform=args.platform,
                    version=args.version,
                    source_commit=args.source_commit,
                )
                print(f"[OK] {args.platform} {args.version} packaging version is {state}")
        elif args.command == "record":
            entry = record_delivery(
                repo=repo,
                history_path=history_path,
                platform=args.platform,
                version=args.version,
                source_commit=args.source_commit,
                delivered_at=args.delivered_at,
                artifact_path=args.artifact,
            )
            print(
                f"[OK] recorded {entry['platform']} {entry['version']} "
                f"at {entry['source_commit']}"
            )
        elif args.command == "record-evidence":
            entry = record_delivery_with_evidence(
                repo=repo,
                history_path=history_path,
                platform=args.platform,
                version=args.version,
                source_commit=args.source_commit,
                delivered_at=args.delivered_at,
                artifact_path=args.artifact,
                report_path=args.report,
            )
            print(
                f"[OK] atomically recorded and attached evidence to "
                f"{entry['platform']} {entry['version']}"
            )
        elif args.command == "attach-evidence":
            entry = attach_evidence(
                repo=repo,
                history_path=history_path,
                platform=args.platform,
                version=args.version,
                report_path=args.report,
            )
            print(
                f"[OK] attached evidence to {entry['platform']} {entry['version']}: "
                f"{entry['evidence_report']}"
            )
        else:
            verify_history_evidence(repo=repo, history_path=history_path)
            print("[OK] release evidence digests verified")
    except ReleaseTrackerError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
