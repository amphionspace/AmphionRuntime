#!/usr/bin/env python3
"""Create an immutable, redacted archive of Harmony release-gate artifacts."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Sequence
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.delivery.asr_release_evidence_contract import (  # noqa: E402
    HARMONY_RELEASE_MODES,
    MIN_LONG_RUN_SECONDS,
    SCHEMA_VERSION,
)


ARCHIVE_FILES = (
    "report.json",
    "result.txt",
    "memory.csv",
    "hilog.txt",
    "inventory.json",
    "payload/corpus.json",
    "payload/manifest.txt",
)
REQUIRED_RELEASE_MODES = HARMONY_RELEASE_MODES
REQUIRED_ANDROID_SUITES = {
    ("sdk", "debug"): 32,
    ("sdk", "release"): 32,
    ("sdk-dingqiao", "debug"): 52,
    ("sdk-dingqiao", "release"): 52,
}
ANDROID_RESULT_DIRECTORIES = {
    ("sdk", "debug"): "sdk/build/test-results/testDebugUnitTest",
    ("sdk", "release"): "sdk/build/test-results/testReleaseUnitTest",
    ("sdk-dingqiao", "debug"): "sdk-dingqiao/build/test-results/testDebugUnitTest",
    ("sdk-dingqiao", "release"): "sdk-dingqiao/build/test-results/testReleaseUnitTest",
}
SAFE_HILOG_MARKERS = (
    "ASR_STRESS|",
    "AmphionRuntime",
    "AmphionMetrics",
    "libsherpa",
    "sherpa_onnx",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
LOCAL_PATH = re.compile(r"/(?:Users|home)/[^\s\"'<>|]+")
MAC_TEMP_PATH = re.compile(r"/(?:private/)?var/folders/[^\s\"'<>|]+")
RESULT_HEX = re.compile(r"(?i)(resultHex(?:\s*[=:]\s*|\"\s*:\s*\"))[0-9a-f]+")
HOSTNAME_ATTRIBUTE = re.compile(r'(?i)(hostname\s*=\s*")[^"]*(")')
FORBIDDEN_ARCHIVE_TEXT = (
    ("local home path", LOCAL_PATH),
    ("macOS temporary path", MAC_TEMP_PATH),
    ("network client identifier", re.compile(r"(?i)\bclient\s*id\b|\bclientID\b")),
    ("access token identifier", re.compile(r"(?i)access\s+token(?:ID)?")),
    ("IPv4 address", re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")),
    ("UUID", re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")),
    ("unredacted recognition text", re.compile(r"(?i)resultHex(?:\s*[=:]\s*|\"\s*:\s*\")[0-9a-f]+")),
    ("unredacted hostname", re.compile(r'(?i)hostname\s*=\s*"(?!redacted")')),
)


class ArchiveFailure(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_report(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArchiveFailure(f"cannot read report {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ArchiveFailure(f"report must be an object: {path}")
    return payload


def device_alias(serial: str) -> str:
    return "device-" + hashlib.sha256(serial.encode("utf-8")).hexdigest()[:12]


def redact_text(text: str, replacements: Mapping[str, str]) -> str:
    for source, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
        if source:
            text = text.replace(source, replacement)
    text = LOCAL_PATH.sub("<LOCAL_PATH>", text)
    text = MAC_TEMP_PATH.sub("<LOCAL_TEMP>", text)
    text = RESULT_HEX.sub(r"\1<redacted>", text)
    return HOSTNAME_ATTRIBUTE.sub(r"\1redacted\2", text)


def _redact_json(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key.lower() == "resulthex" else _redact_json(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json(item, replacements) for item in value]
    if isinstance(value, str):
        return redact_text(value, replacements)
    return value


def sanitize_artifact(relative: str, text: str, replacements: Mapping[str, str]) -> str:
    if relative.endswith(".json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ArchiveFailure(f"invalid JSON artifact {relative}: {error}") from error
        return json.dumps(
            _redact_json(payload, replacements),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
    redacted = redact_text(text, replacements)
    if relative == "hilog.txt":
        redacted = "\n".join(
            line for line in redacted.splitlines() if any(marker in line for marker in SAFE_HILOG_MARKERS)
        )
        if redacted:
            redacted += "\n"
    return redacted


def scan_archive_text(root: Path, forbidden_values: Iterable[str]) -> None:
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        text = path.read_text(encoding="utf-8")
        for value in forbidden_values:
            if value and value in text:
                raise ArchiveFailure(f"sensitive source value remains in {path.relative_to(root)}")
        for label, pattern in FORBIDDEN_ARCHIVE_TEXT:
            if pattern.search(text):
                raise ArchiveFailure(f"{label} remains in {path.relative_to(root)}")


def copy_redacted_artifacts(
    source: Path,
    destination: Path,
    replacements: Mapping[str, str],
    *,
    require_complete: bool,
) -> List[Dict[str, object]]:
    manifest: List[Dict[str, object]] = []
    for relative in ARCHIVE_FILES:
        source_file = source / relative
        if not source_file.is_file():
            continue
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = source_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ArchiveFailure(f"archive input is not UTF-8 text: {source_file}") from error
        destination_file.write_text(
            sanitize_artifact(relative, text, replacements), encoding="utf-8"
        )
        manifest.append(
            {
                "path": relative,
                "sha256": sha256_file(destination_file),
                "size_bytes": destination_file.stat().st_size,
            }
        )
    if require_complete:
        missing = [relative for relative in ARCHIVE_FILES if not (source / relative).is_file()]
        if missing:
            raise ArchiveFailure(
                f"canonical run is missing required artifact {missing[0]}: {source}"
            )
    if not manifest:
        raise ArchiveFailure(f"run has no archivable artifacts: {source}")
    return manifest


def validate_android_summary(path: Path, source_commit: str) -> Dict[str, Any]:
    payload = load_report(path)
    if payload.get("overall_status") != "PASS":
        raise ArchiveFailure("Android summary must have overall_status=PASS")
    if payload.get("source_commit") != source_commit:
        raise ArchiveFailure("Android summary source_commit does not match release source")
    if payload.get("rerun_tasks") is not True:
        raise ArchiveFailure("Android summary must declare rerun_tasks=true")
    sherpa_commit = payload.get("sherpa_submodule_commit")
    if not isinstance(sherpa_commit, str) or not FULL_COMMIT.fullmatch(sherpa_commit):
        raise ArchiveFailure("Android summary has no valid sherpa_submodule_commit")
    suites = payload.get("suites")
    if not isinstance(suites, list):
        raise ArchiveFailure("Android summary has no suites")
    actual: Dict[tuple[str, str], int] = {}
    for suite in suites:
        if not isinstance(suite, dict):
            raise ArchiveFailure("Android summary contains an invalid suite")
        key = (suite.get("module"), suite.get("variant"))
        if key in actual or key not in REQUIRED_ANDROID_SUITES:
            raise ArchiveFailure(f"Android summary contains an unexpected suite: {key}")
        if any(suite.get(field) != 0 for field in ("errors", "failures", "skipped")):
            raise ArchiveFailure(f"Android suite did not fully pass: {key}")
        tests = suite.get("tests")
        if not isinstance(tests, int) or tests < REQUIRED_ANDROID_SUITES[key]:
            raise ArchiveFailure(f"Android suite has too few tests: {key}")
        actual[key] = tests
    if set(actual) != set(REQUIRED_ANDROID_SUITES):
        raise ArchiveFailure("Android summary does not contain the full Debug/Release matrix")
    if payload.get("total_errors") != 0 or payload.get("total_failures") != 0:
        raise ArchiveFailure("Android summary totals are not clean")
    if payload.get("total_tests") != sum(actual.values()):
        raise ArchiveFailure("Android summary total_tests does not match its suites")
    return payload


def commit_timestamp_utc(
    raw_root: Path, source_commit: str, expected_sherpa_commit: str
) -> datetime:
    try:
        head = subprocess.run(
            ["git", "-C", str(raw_root), "rev-parse", "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        committed_at = subprocess.run(
            ["git", "-C", str(raw_root), "show", "-s", "--format=%cI", source_commit],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        repo_root = subprocess.run(
            ["git", "-C", str(raw_root), "rev-parse", "--show-toplevel"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        sherpa_head = subprocess.run(
            [
                "git",
                "-C",
                str(Path(repo_root) / "third_party/sherpa-onnx"),
                "rev-parse",
                "HEAD",
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ArchiveFailure("cannot resolve release source commit time") from error
    if head != source_commit:
        raise ArchiveFailure(f"raw evidence worktree HEAD {head} does not match {source_commit}")
    if sherpa_head != expected_sherpa_commit:
        raise ArchiveFailure(
            f"Android sherpa commit {sherpa_head} does not match summary {expected_sherpa_commit}"
        )
    try:
        return datetime.fromisoformat(committed_at).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError as error:
        raise ArchiveFailure("release source commit has an invalid timestamp") from error


def archive_android_results(
    source_root: Path,
    destination_root: Path,
    replacements: Mapping[str, str],
    expected_summary: Mapping[str, Any],
    not_before: datetime,
) -> List[Dict[str, object]]:
    expected = {
        (suite["module"], suite["variant"]): suite
        for suite in expected_summary["suites"]
    }
    manifest: List[Dict[str, object]] = []
    for key, relative_directory in ANDROID_RESULT_DIRECTORIES.items():
        source_directory = source_root / relative_directory
        xml_files = sorted(source_directory.glob("TEST-*.xml"))
        if not xml_files:
            raise ArchiveFailure(f"Android test results are missing for {key}")
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for source_file in xml_files:
            try:
                suite = ET.fromstring(source_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ET.ParseError) as error:
                raise ArchiveFailure(f"invalid Android test XML {source_file}: {error}") from error
            if suite.tag != "testsuite":
                raise ArchiveFailure(f"Android test XML root is not testsuite: {source_file}")
            try:
                test_timestamp = datetime.fromisoformat(suite.attrib["timestamp"])
            except (KeyError, ValueError) as error:
                raise ArchiveFailure(
                    f"Android test XML has no valid timestamp: {source_file}"
                ) from error
            if test_timestamp < not_before:
                raise ArchiveFailure(
                    f"Android test XML predates release source commit: {source_file}"
                )
            for field in totals:
                try:
                    totals[field] += int(suite.attrib.get(field, "0"))
                except ValueError as error:
                    raise ArchiveFailure(
                        f"Android test XML has invalid {field}: {source_file}"
                    ) from error
            destination = destination_root / key[0] / key[1] / source_file.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                redact_text(source_file.read_text(encoding="utf-8"), replacements),
                encoding="utf-8",
            )
            manifest.append(
                {
                    "path": destination.relative_to(destination_root.parent).as_posix(),
                    "sha256": sha256_file(destination),
                    "size_bytes": destination.stat().st_size,
                }
            )
        summary = expected[key]
        for field, actual in totals.items():
            if summary.get(field) != actual:
                raise ArchiveFailure(
                    f"Android XML {key} {field}={actual} does not match summary {summary.get(field)}"
                )
    return manifest


def canonical_passes(
    raw_root: Path, required_modes: Sequence[str]
) -> tuple[Dict[str, tuple[Path, Dict[str, Any]]], List[tuple[Path, Dict[str, Any]]]]:
    passes: Dict[str, List[tuple[Path, Dict[str, Any]]]] = {
        mode: [] for mode in required_modes
    }
    reports: List[tuple[Path, Dict[str, Any]]] = []
    for report_path in sorted(raw_root.glob("*/report.json")):
        report = load_report(report_path)
        reports.append((report_path.parent, report))
        mode = report.get("mode")
        if mode in passes and report.get("overall_status") == "PASS":
            passes[mode].append((report_path.parent, report))
    missing = sorted(mode for mode, matches in passes.items() if not matches)
    if missing:
        raise ArchiveFailure(f"missing PASS reports for required modes: {', '.join(missing)}")
    canonical = {
        mode: sorted(matches, key=lambda item: str(item[1].get("run_id", item[0].name)))[-1]
        for mode, matches in passes.items()
    }
    return canonical, reports


def identity_tuple(report: Mapping[str, Any]) -> tuple[str, str, str, str]:
    identity = report.get("build_identity")
    if not isinstance(identity, dict):
        raise ArchiveFailure(f"report {report.get('run_id')} has no build_identity")
    artifacts = identity.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ArchiveFailure(f"report {report.get('run_id')} has no build artifacts")
    hap = artifacts.get("amphion_asr_demo.hap")
    if not isinstance(hap, dict):
        raise ArchiveFailure(f"report {report.get('run_id')} has no HAP identity")
    values = (
        identity.get("git_commit"),
        identity.get("source_fingerprint_sha256"),
        hap.get("sha256"),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise ArchiveFailure(f"report {report.get('run_id')} has incomplete build identity")
    artifacts_digest = hashlib.sha256(
        json.dumps(artifacts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return (*values, artifacts_digest)  # type: ignore[return-value]


def observed_duration_seconds(run: Path) -> float:
    try:
        with (run / "memory.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        values = [float(row["elapsed_seconds"]) for row in rows]
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ArchiveFailure(f"invalid memory timeline: {run / 'memory.csv'}") from error
    if not values:
        raise ArchiveFailure(f"empty memory timeline: {run / 'memory.csv'}")
    return max(values)


def parse_assignments(values: Iterable[str], label: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ArchiveFailure(f"{label} must use NAME=VALUE: {value}")
        name, detail = value.split("=", 1)
        if not name or not detail:
            raise ArchiveFailure(f"{label} must use non-empty NAME=VALUE: {value}")
        parsed[name] = detail
    return parsed


def archive_evidence(
    *,
    raw_root: Path,
    output: Path,
    release_version: str,
    source_commit: str,
    artifact_sha256: str,
    har_sha256: str,
    diagnostic_notes: Mapping[str, str],
    artifact_name: str = "",
    artifact_size_bytes: int = 0,
    provenance_sha256: str = "",
    android_summary: Path,
    android_results_root: Path,
    verified_at: str = "",
    not_applicable: Mapping[str, str] | None = None,
    limitations: Sequence[str] = (),
) -> Dict[str, Any]:
    raw_root = raw_root.resolve()
    output = output.resolve()
    if output.exists():
        raise ArchiveFailure(f"evidence output already exists: {output}")
    if not raw_root.is_dir():
        raise ArchiveFailure(f"raw evidence root does not exist: {raw_root}")
    if not FULL_COMMIT.fullmatch(source_commit):
        raise ArchiveFailure("source_commit must be a full commit")
    for label, digest in (
        ("artifact_sha256", artifact_sha256),
        ("har_sha256", har_sha256),
    ):
        if not SHA256.fullmatch(digest):
            raise ArchiveFailure(f"{label} must be SHA-256")
    if provenance_sha256 and not SHA256.fullmatch(provenance_sha256):
        raise ArchiveFailure("provenance_sha256 must be SHA-256")
    required_modes = REQUIRED_RELEASE_MODES
    canonical, reports = canonical_passes(raw_root, required_modes)
    serials = {
        report.get("device")
        for _, report in reports
        if isinstance(report.get("device"), str) and report.get("device")
    }
    if len(serials) != 1:
        raise ArchiveFailure(f"expected one device identity, found {len(serials)}")
    serial = next(iter(serials))
    alias = device_alias(serial)
    identities = {identity_tuple(report) for _, report in canonical.values()}
    if len(identities) != 1:
        raise ArchiveFailure("canonical PASS reports do not share one source/HAP/HAR identity")
    build_commit, source_fingerprint, hap_sha256, _ = next(iter(identities))
    if build_commit != source_commit:
        raise ArchiveFailure(
            f"report commit {build_commit} does not match release source {source_commit}"
        )
    run_durations = {
        mode: observed_duration_seconds(source)
        for mode, (source, _) in canonical.items()
    }
    longest_mode, longest_duration = max(run_durations.items(), key=lambda item: item[1])
    if longest_duration <= MIN_LONG_RUN_SECONDS:
        raise ArchiveFailure(
            f"release matrix has no run longer than {MIN_LONG_RUN_SECONDS:.0f} seconds"
        )

    replacements = {
        serial: alias,
        str(raw_root): "<RAW_EVIDENCE_ROOT>",
    }
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent))
    )
    try:
        mode_summaries: List[Dict[str, Any]] = []
        canonical_directories = {path.resolve() for path, _ in canonical.values()}
        for mode in required_modes:
            source, report = canonical[mode]
            destination = temporary / "modes" / mode
            files = copy_redacted_artifacts(
                source, destination, replacements, require_complete=True
            )
            mode_summaries.append(
                {
                    "mode": mode,
                    "run_id": report.get("run_id", source.name),
                    "report": f"modes/{mode}/report.json",
                    "cycles": report.get("configuration", {}).get("cycles"),
                    "completed": report.get("application", {}).get("completed"),
                    "memory_status": report.get("memory", {}).get("status"),
                    "files": files,
                }
            )

        diagnostic_summaries: List[Dict[str, Any]] = []
        for run in sorted(path for path in raw_root.iterdir() if path.is_dir()):
            if run.resolve() in canonical_directories:
                continue
            destination = temporary / "diagnostics" / run.name
            files = copy_redacted_artifacts(
                run, destination, replacements, require_complete=False
            )
            report_path = run / "report.json"
            report = load_report(report_path) if report_path.is_file() else {}
            diagnostic_summaries.append(
                {
                    "run_id": report.get("run_id", run.name),
                    "mode": report.get("mode", "unknown"),
                    "status": report.get("overall_status", "INFRASTRUCTURE_FAILURE"),
                    "note": diagnostic_notes.get(run.name, "non-canonical run retained for audit"),
                    "path": f"diagnostics/{run.name}",
                    "files": files,
                }
            )

        android_tests = validate_android_summary(android_summary, source_commit)
        android_destination = temporary / "android-tests.json"
        android_destination.write_text(
            json.dumps(
                _redact_json(android_tests, replacements),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        android_artifact = {
            "path": "android-tests.json",
            "sha256": sha256_file(android_destination),
            "size_bytes": android_destination.stat().st_size,
        }
        android_result_files = archive_android_results(
            android_results_root.resolve(),
            temporary / "android-test-results",
            replacements,
            android_tests,
            commit_timestamp_utc(
                raw_root, source_commit, android_tests["sherpa_submodule_commit"]
            ),
        )

        summary: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "release_version": release_version,
            "verified_at": verified_at,
            "overall_status": "PASS",
            "source_commit": source_commit,
            "source_fingerprint_sha256": source_fingerprint,
            "device_alias": alias,
            "build_identity": {
                "hap_sha256": hap_sha256,
                "delivery_har_sha256": har_sha256,
            },
            "release_artifact": {
                "name": artifact_name,
                "sha256": artifact_sha256,
                "size_bytes": artifact_size_bytes,
                "provenance_sha256": provenance_sha256,
            },
            "required_modes": list(required_modes),
            "modes": mode_summaries,
            "long_run": {
                "mode": longest_mode,
                "duration_seconds": longest_duration,
            },
            "diagnostics": diagnostic_summaries,
            "not_applicable": dict(not_applicable or {}),
            "limitations": list(limitations),
            "android_tests": android_tests,
            "android_tests_artifact": android_artifact,
            "android_test_results": android_result_files,
            "retention": {
                "raw_pcm_committed": False,
                "input_mapping_retained": True,
                "failure_artifacts_retained": True,
                "device_and_local_paths_redacted": True,
            },
        }
        (temporary / "report.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        scan_archive_text(temporary, (serial, str(raw_root)))
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(output)
        return summary
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--artifact-size-bytes", type=int, default=0)
    parser.add_argument("--provenance-sha256", default="")
    parser.add_argument("--har-sha256", required=True)
    parser.add_argument("--diagnostic-note", action="append", default=[])
    parser.add_argument("--not-applicable", action="append", default=[])
    parser.add_argument("--limitation", action="append", default=[])
    parser.add_argument("--android-summary", type=Path, required=True)
    parser.add_argument("--android-results-root", type=Path, required=True)
    parser.add_argument("--verified-at", default="")
    args = parser.parse_args()
    try:
        archive_evidence(
            raw_root=args.raw_root,
            output=args.output,
            release_version=args.release_version,
            source_commit=args.source_commit,
            artifact_name=args.artifact_name,
            artifact_sha256=args.artifact_sha256,
            artifact_size_bytes=args.artifact_size_bytes,
            provenance_sha256=args.provenance_sha256,
            har_sha256=args.har_sha256,
            diagnostic_notes=parse_assignments(args.diagnostic_note, "diagnostic note"),
            not_applicable=parse_assignments(args.not_applicable, "not applicable"),
            limitations=args.limitation,
            android_summary=args.android_summary,
            android_results_root=args.android_results_root,
            verified_at=args.verified_at,
        )
        print(f"[OK] archived release-gate evidence: {args.output}")
        return 0
    except ArchiveFailure as error:
        print(f"[ERROR] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
