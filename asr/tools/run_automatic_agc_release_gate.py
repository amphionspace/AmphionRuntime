#!/usr/bin/env python3
"""Run automatic AGC checks at the earliest useful development stage."""

import argparse
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


class GateCommand(NamedTuple):
    name: str
    argv: Sequence[str]
    cwd: Path
    env: Mapping[str, str] = {}


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


def run(commands) -> int:
    for index, command in enumerate(commands, start=1):
        started = time.monotonic()
        print(f"[GATE {index}/{len(commands)}] {command.name}", flush=True)
        try:
            environment = os.environ.copy()
            environment.update(command.env)
            subprocess.run(command.argv, cwd=command.cwd, check=True, env=environment)
        except subprocess.CalledProcessError as error:
            elapsed = time.monotonic() - started
            print(
                f"[FAIL] {command.name} ({elapsed:.1f}s, exit {error.returncode})",
                file=sys.stderr,
            )
            return error.returncode or 1
        print(f"[PASS] {command.name} ({time.monotonic() - started:.1f}s)", flush=True)
    print("[PASS] automatic AGC release gate")
    return 0


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
        commands = static_commands(ROOT)
    elif args.stage == "regression":
        if args.model_dir is None:
            parser.error("regression requires --model-dir")
        commands = regression_commands(ROOT, args.model_dir, args.agc_lib)
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
        commands = release_commands(
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
    return run(commands)


if __name__ == "__main__":
    sys.exit(main())
