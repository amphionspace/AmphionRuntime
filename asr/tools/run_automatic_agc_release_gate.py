#!/usr/bin/env python3
"""Run automatic AGC checks at the earliest useful development stage."""

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, NamedTuple, Optional, Sequence
import zipfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.delivery.asr_release_evidence_contract import HARMONY_RELEASE_MODES  # noqa: E402
FINISH_COMPAT_MODES = ("callback-api-reentrant", "finish-shutdown")
DEVICE_MATRIX = tuple(mode for mode in HARMONY_RELEASE_MODES if mode not in FINISH_COMPAT_MODES)
STATIC_MAX_PARALLEL = 3
REGRESSION_MAX_PARALLEL = 3
RELEASE_MAX_PARALLEL = 3


class GateCommand(NamedTuple):
    name: str
    argv: Sequence[str]
    cwd: Path
    env: Mapping[str, str] = {}


class GateTask(NamedTuple):
    key: str
    command: GateCommand
    dependencies: tuple[str, ...] = ()


def packaged_delivery_har_sha256(release_artifact: Path) -> str:
    with zipfile.ZipFile(release_artifact) as archive:
        har_members = [
            name for name in archive.namelist()
            if name.endswith("/har/amphion_dingqiao.har")
        ]
        if len(har_members) != 1:
            raise ValueError("release artifact must contain exactly one amphion_dingqiao.har")
        return hashlib.sha256(archive.read(har_members[0])).hexdigest()


def static_commands(root: Path = ROOT):
    python = sys.executable
    return [
        GateCommand(
            "dependency-free AGC contracts",
            (
                python,
                "-S",
                "-m",
                "unittest",
                "asr.tools.tests.test_automatic_agc_release_gate",
                "asr.tools.tests.test_automatic_agc_evaluation_evidence",
                "delivery.harmony-dingqiao.delivery.test_build_install_smoke",
                "-v",
            ),
            root,
        ),
        GateCommand(
            "cross-platform AGC framing and signal domains",
            (
                python,
                "-S",
                "-m",
                "unittest",
                "asr.tools.tests.test_harmony_streaming_agc_processor",
                "asr.tools.tests.test_agc_signal_domains",
                "-v",
            ),
            root,
        ),
        GateCommand(
            "AGC evaluation provenance",
            (python, "asr/tools/sync_automatic_agc_evidence.py", "--check"),
            root,
        ),
    ]


def host_library(root: Path = ROOT) -> Path:
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    return root / f"asr/native/audio-processing/build-host/libamphion_audio_processing{suffix}"


def regression_commands(
    root: Path,
    model_dir: Path,
    agc_lib: Optional[Path] = None,
):
    library = agc_lib or host_library(root)
    return static_commands(root) + [
        GateCommand(
            "AGC evaluation model identity",
            (
                sys.executable,
                "asr/tools/sync_automatic_agc_evidence.py",
                "--check",
                "--model-dir",
                str(model_dir),
            ),
            root,
        ),
        GateCommand(
            "host AGC build and native tests",
            ("bash", "asr/tools/03_build_agc_native.sh", "host"),
            root,
        ),
        GateCommand(
            "low-volume ASR red/green reproduction",
            (
                sys.executable,
                "asr/tools/evaluate_automatic_agc_regression.py",
                "--model-dir",
                str(model_dir),
                "--agc-lib",
                str(library),
            ),
            root,
        ),
    ]


def release_commands(
    root: Path,
    model_dir: Path,
    device: str,
    signing_config: Path,
    data_dir: Path,
    release_version: str,
    delivered_at: str,
    release_artifact: Path,
    delivery_har: Path,
    evidence_output: Path,
    evaluation_artifact_root: Path,
    build_identity: Path,
    provenance: Optional[Path] = None,
    agc_lib: Optional[Path] = None,
):
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    gate_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}-{source_commit[:8]}"
    gate_root = root / "delivery/harmony-dingqiao/build/release-gates/automatic-agc" / gate_id
    raw_root = gate_root / "raw"
    android_root = gate_root / "android"
    commands = regression_commands(root, model_dir, agc_lib) + [
        GateCommand(
            "Complete AGC evaluation artifact identity",
            (
                sys.executable,
                "asr/tools/sync_automatic_agc_evidence.py",
                "--check",
                "--model-dir", str(model_dir),
                "--artifact-root", str(evaluation_artifact_root),
            ),
            root,
        ),
        GateCommand(
            "Isolated Android AAR build and Debug/Release tests",
            ("bash", "asr/tools/build_android_agc_release_gate.sh", str(android_root)),
            root,
        ),
        GateCommand(
            "Harmony finish compatibility build/install gate",
            (
                sys.executable,
                "delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py",
                "--data-dir", str(data_dir),
                "--device", device,
                "--raw-output-root", str(raw_root),
                "--output-root", str(gate_root / "finish-compat"),
                "--summary-output", str(gate_root / "finish-compat-report.json"),
                "--reuse-verified-build",
                "--build-identity", str(build_identity),
            ),
            root,
            {"HARMONY_SIGNING_CONFIG": str(signing_config)},
        ),
    ]
    for mode in DEVICE_MATRIX:
        argv = [
            sys.executable,
            "delivery/harmony-dingqiao/delivery/run_device_stress.py",
            "--data-dir",
            str(data_dir),
            "--device",
            device,
            "--mode",
            mode,
            "--cycles",
            "3",
            "--files",
            "3",
            "--skip-build-install",
            "--output-root",
            str(raw_root),
        ]
        if mode in ("paced", "voiceprint-fallback"):
            argv.extend(("--post-run-observe", "65"))
        commands.append(GateCommand(f"Harmony device matrix: {mode}", tuple(argv), root))
    finalize = [
        sys.executable,
        "asr/tools/finalize_automatic_agc_release_gate.py",
        "--raw-root", str(raw_root),
        "--output", str(evidence_output),
        "--release-version", release_version,
        "--delivered-at", delivered_at,
        "--release-artifact", str(release_artifact),
        "--delivery-har", str(delivery_har),
        "--android-results-root", str(android_root),
        "--finish-compat-summary", str(gate_root / "finish-compat-report.json"),
        "--build-identity", str(build_identity),
    ]
    if provenance is not None:
        finalize.extend(("--provenance", str(provenance)))
    commands.append(GateCommand("Archive and ledger-verify release evidence", tuple(finalize), root))
    return commands


def static_tasks(root: Path = ROOT) -> list[GateTask]:
    commands = {command.name: command for command in static_commands(root)}
    return [
        GateTask("cheap-contracts", commands["dependency-free AGC contracts"]),
        GateTask(
            "signal-domains",
            commands["cross-platform AGC framing and signal domains"],
        ),
        GateTask("evidence-source", commands["AGC evaluation provenance"]),
    ]


def regression_tasks(
    root: Path,
    model_dir: Path,
    agc_lib: Optional[Path] = None,
) -> list[GateTask]:
    commands = {command.name: command for command in regression_commands(root, model_dir, agc_lib)}
    return [
        GateTask("host-agc", commands["host AGC build and native tests"]),
        *static_tasks(root),
        GateTask("model-identity", commands["AGC evaluation model identity"]),
        GateTask(
            "low-volume-regression",
            commands["low-volume ASR red/green reproduction"],
            ("host-agc",),
        ),
    ]


def release_tasks(
    root: Path,
    model_dir: Path,
    device: str,
    signing_config: Path,
    data_dir: Path,
    release_version: str,
    delivered_at: str,
    release_artifact: Path,
    delivery_har: Path,
    evidence_output: Path,
    evaluation_artifact_root: Path,
    build_identity: Path,
    provenance: Optional[Path] = None,
    agc_lib: Optional[Path] = None,
) -> list[GateTask]:
    command_list = release_commands(
        root,
        model_dir,
        device,
        signing_config,
        data_dir,
        release_version,
        delivered_at,
        release_artifact,
        delivery_har,
        evidence_output,
        evaluation_artifact_root,
        build_identity,
        provenance,
        agc_lib,
    )
    commands = {command.name: command for command in command_list}
    prerequisites = (
        "cheap-contracts",
        "signal-domains",
        "evidence-source",
        "evaluation-artifacts",
    )
    tasks = [
        GateTask("host-agc", commands["host AGC build and native tests"]),
        GateTask("cheap-contracts", commands["dependency-free AGC contracts"]),
        GateTask(
            "signal-domains",
            commands["cross-platform AGC framing and signal domains"],
        ),
        GateTask("evidence-source", commands["AGC evaluation provenance"]),
        GateTask(
            "evaluation-artifacts",
            commands["Complete AGC evaluation artifact identity"],
        ),
        GateTask(
            "low-volume-regression",
            commands["low-volume ASR red/green reproduction"],
            ("host-agc",),
        ),
        GateTask(
            "android-release",
            commands["Isolated Android AAR build and Debug/Release tests"],
            prerequisites,
        ),
        GateTask(
            "harmony-finish-compat",
            commands["Harmony finish compatibility build/install gate"],
            prerequisites,
        ),
    ]
    previous = "harmony-finish-compat"
    for mode in DEVICE_MATRIX:
        key = f"device-{mode}"
        tasks.append(GateTask(key, commands[f"Harmony device matrix: {mode}"], (previous,)))
        previous = key
    tasks.append(
        GateTask(
            "finalize",
            commands["Archive and ledger-verify release evidence"],
            ("android-release", previous, "low-volume-regression"),
        )
    )
    validate_task_graph(tasks)
    return tasks


def require_release_inputs(
    root: Path,
    model_dir: Path,
    signing_config: Path,
    data_dir: Path,
    release_version: str,
    delivered_at: str,
    release_artifact: Path,
    delivery_har: Path,
    evidence_output: Path,
    evaluation_artifact_root: Path,
    build_identity: Path,
    provenance: Optional[Path],
) -> None:
    required_model_files = (
        "encoder.int8.onnx",
        "decoder.onnx",
        "joiner.onnx",
        "tokens.txt",
        "bbpe.vocab",
    )
    missing_model_files = [name for name in required_model_files if not (model_dir / name).is_file()]
    if missing_model_files:
        raise ValueError(f"model directory is incomplete: {', '.join(missing_model_files)}")
    if not signing_config.is_file():
        raise ValueError(f"signing config does not exist: {signing_config}")
    if not data_dir.is_dir():
        raise ValueError(f"device data directory does not exist: {data_dir}")
    for label, path in (
        ("release artifact", release_artifact),
        ("delivery HAR", delivery_har),
    ):
        if not path.is_file():
            raise ValueError(f"{label} does not exist: {path}")
    if provenance is None or not provenance.is_file():
        raise ValueError(f"provenance does not exist: {provenance}")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", delivered_at):
        raise ValueError("delivered-at must be YYYY-MM-DD")
    if evidence_output.exists():
        raise ValueError(f"evidence output must not already exist: {evidence_output}")
    try:
        evidence_output.resolve().relative_to((root / "delivery").resolve())
    except ValueError as error:
        raise ValueError("evidence output must be inside the repository delivery directory") from error
    if not evaluation_artifact_root.is_dir():
        raise ValueError(f"evaluation artifact root does not exist: {evaluation_artifact_root}")
    if not build_identity.is_file():
        raise ValueError(f"build identity does not exist: {build_identity}")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    if status:
        raise ValueError("release gate requires a completely clean worktree, including untracked files")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    history = json.loads((root / "delivery/asr-sdk-release-history.json").read_text(encoding="utf-8"))
    if any(
        entry.get("platform") == "harmony" and entry.get("version") == release_version
        for entry in history.get("deliveries", [])
    ):
        raise ValueError(f"Harmony delivery {release_version} is already recorded")
    sys.path.insert(0, str(root))
    from tools.delivery.asr_release_tracker import _read_artifact_provenance
    embedded, payload = _read_artifact_provenance(release_artifact, "harmony")
    if embedded.get("version") != release_version:
        raise ValueError("release artifact provenance version does not match release-version")
    embedded_commit = subprocess.check_output(
        ["git", "rev-parse", f"{embedded.get('commit')}^{{commit}}"], cwd=root, text=True
    ).strip()
    if embedded_commit != head:
        raise ValueError("release artifact provenance commit does not match current HEAD")
    if hashlib.sha256(payload).hexdigest() != hashlib.sha256(provenance.read_bytes()).hexdigest():
        raise ValueError("provenance file does not match the provenance embedded in the release artifact")
    if packaged_delivery_har_sha256(release_artifact) != hashlib.sha256(delivery_har.read_bytes()).hexdigest():
        raise ValueError("release artifact HAR does not match the HAR tested on the device")
    subprocess.run(
        [
            sys.executable,
            "delivery/harmony-dingqiao/delivery/validate_asr_sdk_delivery.py",
            str(release_artifact),
            "--version",
            release_version,
            "--build-identity",
            str(build_identity),
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [sys.executable, "tools/delivery/asr_release_tracker.py", "verify-evidence"],
        cwd=root,
        check=True,
    )


def validate_task_graph(tasks: Sequence[GateTask]) -> None:
    keys = [task.key for task in tasks]
    if len(keys) != len(set(keys)):
        raise ValueError("task graph contains duplicate task keys")
    known = set(keys)
    for task in tasks:
        unknown = set(task.dependencies) - known
        if unknown:
            raise ValueError(
                f"task {task.key} has unknown dependency: {', '.join(sorted(unknown))}"
            )

    remaining = {task.key: set(task.dependencies) for task in tasks}
    completed: set[str] = set()
    while remaining:
        ready = [key for key, dependencies in remaining.items() if dependencies <= completed]
        if not ready:
            raise ValueError("task graph contains a dependency cycle")
        completed.update(ready)
        for key in ready:
            del remaining[key]


def execute_command(command: GateCommand, label: str) -> int:
    started = time.monotonic()
    print(f"[START] {label}: {command.name}", flush=True)
    environment = os.environ.copy()
    environment.update(command.env)
    try:
        subprocess.run(command.argv, cwd=command.cwd, check=True, env=environment)
    except (OSError, subprocess.CalledProcessError) as error:
        elapsed = time.monotonic() - started
        returncode = error.returncode if isinstance(error, subprocess.CalledProcessError) else 1
        print(
            f"[FAIL] {label}: {command.name} ({elapsed:.1f}s, exit {returncode})",
            file=sys.stderr,
            flush=True,
        )
        return returncode or 1
    print(f"[PASS] {label}: {command.name} ({time.monotonic() - started:.1f}s)", flush=True)
    return 0


def run_task_graph(tasks: Sequence[GateTask], max_parallel: int) -> int:
    validate_task_graph(tasks)
    if max_parallel <= 0:
        raise ValueError("max_parallel must be positive")

    pending = {task.key: task for task in tasks}
    completed: set[str] = set()
    running: dict[Future[int], GateTask] = {}
    first_failure = 0
    with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="agc-gate") as executor:
        while pending or running:
            if not first_failure:
                ready = [
                    task
                    for task in tasks
                    if task.key in pending and set(task.dependencies) <= completed
                ]
                for task in ready[: max_parallel - len(running)]:
                    del pending[task.key]
                    future = executor.submit(execute_command, task.command, task.key)
                    running[future] = task
            if not running:
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                task = running.pop(future)
                result = future.result()
                if result == 0:
                    completed.add(task.key)
                elif not first_failure:
                    first_failure = result

    if first_failure:
        skipped = [task.key for task in tasks if task.key in pending]
        if skipped:
            print(f"[SKIP] dependency graph stopped before: {', '.join(skipped)}", flush=True)
        return first_failure
    if pending:
        raise RuntimeError("task graph stopped without completing all tasks")
    print("[PASS] automatic AGC release gate")
    return 0


def run(commands) -> int:
    tasks = [GateTask(f"gate-{index}", command) for index, command in enumerate(commands, start=1)]
    return run_task_graph(tasks, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("static", "regression", "release"))
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--agc-lib", type=Path)
    parser.add_argument("--device")
    parser.add_argument("--signing-config", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--release-version")
    parser.add_argument("--delivered-at")
    parser.add_argument("--release-artifact", type=Path)
    parser.add_argument("--delivery-har", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--evaluation-artifact-root", type=Path)
    parser.add_argument("--build-identity", type=Path)
    args = parser.parse_args()

    if args.stage == "static":
        return run_task_graph(static_tasks(ROOT), STATIC_MAX_PARALLEL)
    elif args.stage == "regression":
        if args.model_dir is None:
            parser.error("regression requires --model-dir")
        return run_task_graph(
            regression_tasks(ROOT, args.model_dir, args.agc_lib),
            REGRESSION_MAX_PARALLEL,
        )
    else:
        missing = [
            option
            for option, value in (
                ("--model-dir", args.model_dir),
                ("--device", args.device),
                ("--signing-config", args.signing_config),
                ("--data-dir", args.data_dir),
                ("--release-version", args.release_version),
                ("--delivered-at", args.delivered_at),
                ("--release-artifact", args.release_artifact),
                ("--delivery-har", args.delivery_har),
                ("--evidence-output", args.evidence_output),
                ("--provenance", args.provenance),
                ("--evaluation-artifact-root", args.evaluation_artifact_root),
                ("--build-identity", args.build_identity),
            )
            if value is None
        ]
        if missing:
            parser.error(f"release requires {', '.join(missing)}")
        try:
            require_release_inputs(
                ROOT,
                args.model_dir,
                args.signing_config,
                args.data_dir,
                args.release_version,
                args.delivered_at,
                args.release_artifact,
                args.delivery_har,
                args.evidence_output,
                args.evaluation_artifact_root,
                args.build_identity,
                args.provenance,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            parser.error(str(error))
        tasks = release_tasks(
            ROOT,
            args.model_dir,
            args.device,
            args.signing_config,
            args.data_dir,
            args.release_version,
            args.delivered_at,
            args.release_artifact,
            args.delivery_har,
            args.evidence_output,
            args.evaluation_artifact_root,
            args.build_identity,
            args.provenance,
            args.agc_lib,
        )
        return run_task_graph(tasks, RELEASE_MAX_PARALLEL)


if __name__ == "__main__":
    sys.exit(main())
