#!/usr/bin/env python3
"""Run and verify the Harmony finish-compatibility USB release gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
PROJECT_ROOT = REPO_ROOT / "delivery" / "harmony-dingqiao"
RUNNER = SCRIPT_DIR / "run_device_stress.py"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "build" / "release-gates" / "finish-compat"


class GateFailure(RuntimeError):
    pass


def integer(item: dict[str, Any], key: str, context: str) -> int:
    try:
        return int(item[key])
    except (KeyError, TypeError, ValueError) as error:
        raise GateFailure(f"{context} missing integer field {key}") from error


def require_last_then_complete(cycle: dict[str, Any], context: str) -> None:
    trace = str(cycle.get("trace", ""))
    callbacks = trace.split(">") if trace else []
    last = [index for index, value in enumerate(callbacks) if value.endswith(":final-last")]
    complete = [index for index, value in enumerate(callbacks) if value.endswith(":complete")]
    if len(last) != 1 or len(complete) != 1 or complete[0] != last[0] + 1:
        raise GateFailure(f"{context} must emit exactly one last followed by one complete")


def validate_report_header(report: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if report.get("mode") != mode:
        raise GateFailure(f"expected {mode} report, got {report.get('mode')!r}")
    if report.get("overall_status") != "PASS":
        raise GateFailure(f"{mode} report is not PASS")
    cycles = report.get("cycles")
    if not isinstance(cycles, list) or not cycles:
        raise GateFailure(f"{mode} report has no cycle evidence")
    return cycles


def validate_terminal_cycle(
    cycle: dict[str, Any],
    context: str,
    *,
    require_pre_finish_snapshot: bool = False,
) -> None:
    if cycle.get("status") != "PASS":
        raise GateFailure(f"{context} is not PASS")
    if require_pre_finish_snapshot and integer(cycle, "lastFinalsBeforeFinish", context) != 0:
        raise GateFailure(f"{context} emitted last before explicit finish")
    if integer(cycle, "finals", context) != 1:
        raise GateFailure(f"{context} must emit exactly one final")
    if integer(cycle, "completes", context) != 1:
        raise GateFailure(f"{context} must emit exactly one complete")
    if integer(cycle, "errors", context) != 0:
        raise GateFailure(f"{context} must not emit errors")
    if integer(cycle, "finalChars", context) <= 0:
        raise GateFailure(f"{context} must preserve non-empty text on the last result")
    if integer(cycle, "liveStreams", context) != 0:
        raise GateFailure(f"{context} must release the native stream")
    require_last_then_complete(cycle, context)


def validate_callback_report(report: dict[str, Any]) -> dict[str, Any]:
    cycles = validate_report_header(report, "callback-api-reentrant")
    speech_end = [
        cycle
        for cycle in cycles
        if cycle.get("detail") == "callback-api-reentrant-speech-end"
    ]
    if not speech_end:
        raise GateFailure("callback-api-reentrant must contain a speech-end cycle")
    for index, cycle in enumerate(speech_end):
        validate_terminal_cycle(cycle, f"speech-end finish cycle {index}")
    return {
        "mode": "callback-api-reentrant",
        "run_id": report.get("run_id"),
        "status": "PASS",
        "cycles": len(cycles),
        "speech_end_cycles": len(speech_end),
        "minimum_speech_end_final_chars": min(
            integer(cycle, "finalChars", "speech-end finish") for cycle in speech_end
        ),
    }


def validate_finish_shutdown_report(report: dict[str, Any]) -> dict[str, Any]:
    cycles = validate_report_header(report, "finish-shutdown")
    for index, cycle in enumerate(cycles):
        context = f"finish-shutdown cycle {index}"
        validate_terminal_cycle(cycle, context, require_pre_finish_snapshot=True)
    return {
        "mode": "finish-shutdown",
        "run_id": report.get("run_id"),
        "status": "PASS",
        "cycles": len(cycles),
    }


def build_key(report: dict[str, Any]) -> tuple[Any, ...]:
    identity = report.get("build_identity")
    if not isinstance(identity, dict):
        raise GateFailure(f"{report.get('mode')} report has no build identity")
    artifacts = identity.get("artifacts")
    if not isinstance(artifacts, dict):
        raise GateFailure(f"{report.get('mode')} report has no artifact identity")

    def artifact_sha(name: str) -> Any:
        value = artifacts.get(name)
        return value.get("sha256") if isinstance(value, dict) else None

    key = (
        identity.get("git_commit"),
        identity.get("source_fingerprint_sha256"),
        artifact_sha("amphion_asr_demo.hap"),
        artifact_sha("amphion_dingqiao.har"),
    )
    if any(value in (None, "") for value in key):
        raise GateFailure(f"{report.get('mode')} build identity is incomplete")
    return key


def validate_gate_reports(
    callback_report: dict[str, Any],
    finish_shutdown_report: dict[str, Any],
) -> dict[str, Any]:
    callback = validate_callback_report(callback_report)
    finish_shutdown = validate_finish_shutdown_report(finish_shutdown_report)
    callback_device = callback_report.get("device")
    finish_device = finish_shutdown_report.get("device")
    if not isinstance(callback_device, str) or not callback_device.strip():
        raise GateFailure("callback-api-reentrant report has no device identity")
    if not isinstance(finish_device, str) or not finish_device.strip():
        raise GateFailure("finish-shutdown report has no device identity")
    if callback_device != finish_device:
        raise GateFailure("both modes must run on the same device")
    if build_key(callback_report) != build_key(finish_shutdown_report):
        raise GateFailure("both modes must run against the same build")
    return {
        "status": "PASS",
        "device": callback_device,
        "build_identity": callback_report.get("build_identity"),
        "modes": [callback, finish_shutdown],
    }


def build_runner_command(
    *,
    mode: str,
    cycles: int,
    data_dir: Path,
    files: int,
    output_root: Path,
    skip_build_install: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(RUNNER),
        "--data-dir",
        str(data_dir),
        "--mode",
        mode,
        "--cycles",
        str(cycles),
        "--files",
        str(files),
        "--post-run-observe",
        "0",
        "--output-root",
        str(output_root),
    ]
    if skip_build_install:
        command.append("--skip-build-install")
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build once, then run the VAD callback-finish and PTT finish-shutdown USB gates "
            "against the same Harmony HAP."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "Downloads" / "testdata")
    parser.add_argument("--callback-cycles", type=int, default=3)
    parser.add_argument("--finish-shutdown-cycles", type=int, default=10)
    parser.add_argument("--files", type=int, default=3)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    if args.callback_cycles < 3:
        parser.error("--callback-cycles must be at least 3 to cover every callback entry")
    if args.finish_shutdown_cycles <= 0:
        parser.error("--finish-shutdown-cycles must be positive")
    if args.files < 3:
        parser.error("--files must be at least 3")
    return args


def git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def run_mode(command: list[str], output_root: Path) -> tuple[Path, dict[str, Any], int]:
    before = set(output_root.glob("*/report.json")) if output_root.exists() else set()
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    after = set(output_root.glob("*/report.json")) if output_root.exists() else set()
    created = sorted(after - before)
    if len(created) != 1:
        raise GateFailure(f"expected one new device report, found {len(created)}")
    report_path = created[0]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return report_path, report, result.returncode


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def failure_summary(
    base_summary: dict[str, Any],
    error: BaseException,
    observed: list[tuple[str, Path, dict[str, Any]]],
    gate_root: Path,
) -> dict[str, Any]:
    failure = dict(base_summary)
    failure.update({"status": "FAIL", "failures": [str(error)]})
    if observed:
        first_report = observed[0][2]
        failure["device"] = first_report.get("device")
        failure["build_identity"] = first_report.get("build_identity")
        failure["reports"] = {
            mode: str(path.relative_to(gate_root))
            for mode, path, _ in observed
        }
    return failure


def main() -> int:
    args = parse_args()
    created_at = datetime.now(timezone.utc)
    try:
        source_commit = git_output("rev-parse", "HEAD")
    except subprocess.SubprocessError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    gate_id = f"{created_at:%Y%m%d-%H%M%S-%f}-{source_commit[:8]}"
    gate_root = args.output_root / gate_id
    runs_root = gate_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=False)
    summary_path = gate_root / "report.json"
    base_summary: dict[str, Any] = {
        "schema_version": 1,
        "gate": "harmony-finish-compat",
        "created_at": created_at.isoformat(),
        "source_commit": source_commit,
    }
    observed: list[tuple[str, Path, dict[str, Any]]] = []
    try:
        if git_output("status", "--porcelain"):
            raise GateFailure("release gate requires a clean worktree")
        callback_path, callback_report, callback_exit = run_mode(
            build_runner_command(
                mode="callback-api-reentrant",
                cycles=args.callback_cycles,
                data_dir=args.data_dir,
                files=args.files,
                output_root=runs_root,
                skip_build_install=False,
            ),
            runs_root,
        )
        observed.append(("callback-api-reentrant", callback_path, callback_report))
        if callback_exit != 0:
            raise GateFailure(f"callback-api-reentrant runner failed; see {callback_path}")
        validate_callback_report(callback_report)
        finish_path, finish_report, finish_exit = run_mode(
            build_runner_command(
                mode="finish-shutdown",
                cycles=args.finish_shutdown_cycles,
                data_dir=args.data_dir,
                files=args.files,
                output_root=runs_root,
                skip_build_install=True,
            ),
            runs_root,
        )
        observed.append(("finish-shutdown", finish_path, finish_report))
        if finish_exit != 0:
            raise GateFailure(f"finish-shutdown runner failed; see {finish_path}")
        result = validate_gate_reports(callback_report, finish_report)
        if build_key(callback_report)[0] != source_commit:
            raise GateFailure("device build identity does not match the current source commit")
        result.update(base_summary)
        result["reports"] = {
            "callback-api-reentrant": str(callback_path.relative_to(gate_root)),
            "finish-shutdown": str(finish_path.relative_to(gate_root)),
        }
        write_report(summary_path, result)
        print(f"[PASS] Harmony finish compatibility release gate: {gate_root}")
        return 0
    except (GateFailure, json.JSONDecodeError, OSError, subprocess.SubprocessError) as error:
        failure = failure_summary(base_summary, error, observed, gate_root)
        write_report(summary_path, failure)
        print(f"[FAIL] {error}; evidence={gate_root}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
