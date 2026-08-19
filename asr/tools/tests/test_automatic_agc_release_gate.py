import importlib.util
import contextlib
import hashlib
import io
import json
import unittest
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / "asr/tools/run_automatic_agc_release_gate.py"
SYNC = ROOT / "asr/tools/sync_automatic_agc_evidence.py"
BUILD_AGC = ROOT / "asr/tools/03_build_agc_native.sh"
ENSURE_TOOLS = ROOT / "asr/tools/ensure_agc_build_tools.sh"
ANDROID_RELEASE = ROOT / "asr/tools/build_android_agc_release_gate.sh"
FINALIZE = ROOT / "asr/tools/finalize_automatic_agc_release_gate.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AutomaticAgcReleaseGateTest(unittest.TestCase):
    def test_static_gate_covers_every_previously_late_failure(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate")
        rendered = [" ".join(command.argv) for command in gate.static_commands(ROOT)]

        self.assertTrue(any("-S -m unittest" in command for command in rendered))
        self.assertTrue(any("test_automatic_agc_evaluation_evidence" in command for command in rendered))
        self.assertTrue(any("test_build_install_smoke" in command for command in rendered))
        self.assertTrue(any("test_harmony_streaming_agc_processor" in command for command in rendered))
        self.assertTrue(any("test_agc_signal_domains" in command for command in rendered))
        self.assertTrue(any("sync_automatic_agc_evidence.py --check" in command for command in rendered))

    def test_release_gate_builds_each_platform_once_and_archives_complete_evidence(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate_release")
        commands = gate.release_commands(
            ROOT,
            model_dir=Path("/models/zhen"),
            device="device-1",
            signing_config=Path("/secure/signing.json"),
            data_dir=Path("/audio/release"),
            release_version="0.3.2",
            delivered_at="2026-08-13",
            release_artifact=Path("/delivery/customer.zip"),
            delivery_har=Path("/delivery/amphion_dingqiao.har"),
            evidence_output=Path("/evidence/0.3.2"),
            evaluation_artifact_root=Path("/evaluation/artifacts"),
            build_identity=Path("/delivery/build-identity.json"),
        )
        rendered = [" ".join(command.argv) for command in commands]

        self.assertLess(
            next(i for i, command in enumerate(rendered) if "03_build_agc_native.sh host" in command),
            next(i for i, command in enumerate(rendered) if "evaluate_automatic_agc_regression.py" in command),
        )
        self.assertEqual(1, sum("build_android_agc_release_gate.sh" in command for command in rendered))
        self.assertEqual(1, sum("run_finish_compat_release_gate.py" in command for command in rendered))
        self.assertEqual(1, sum("finalize_automatic_agc_release_gate.py" in command for command in rendered))
        self.assertTrue(any("--device device-1" in command for command in rendered))
        finish = next(
            command for command in commands
            if any("run_finish_compat_release_gate.py" in argument for argument in command.argv)
        )
        self.assertEqual("/secure/signing.json", finish.env["HARMONY_SIGNING_CONFIG"])
        self.assertIn("--reuse-verified-build", finish.argv)
        matrix = {
            command.name.removeprefix("Harmony device matrix: ")
            for command in commands
            if command.name.startswith("Harmony device matrix: ")
        }
        self.assertEqual(set(gate.DEVICE_MATRIX), matrix)
        self.assertEqual(
            set(gate.HARMONY_RELEASE_MODES),
            matrix | set(gate.FINISH_COMPAT_MODES),
        )
        smoke_index = next(
            i for i, command in enumerate(commands)
            if any("run_finish_compat_release_gate.py" in argument for argument in command.argv)
        )
        first_matrix = next(i for i, command in enumerate(commands) if command.name.startswith("Harmony device matrix:"))
        self.assertLess(smoke_index, first_matrix)
        self.assertTrue(
            all(
                "--skip-build-install" in command.argv
                for command in commands[first_matrix:-1]
            )
        )
        self.assertTrue(
            all(
                command.argv[command.argv.index("--device") + 1] == "device-1"
                for command in commands[first_matrix:-1]
            )
        )
        self.assertIn("--release-version 0.3.2", rendered[-1])
        self.assertIn("--delivered-at 2026-08-13", rendered[-1])
        self.assertIn("--output /evidence/0.3.2", rendered[-1])

    def test_release_graph_parallelizes_independent_work_but_serializes_device_modes(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate_graph")
        tasks = gate.release_tasks(
            ROOT,
            model_dir=Path("/models/zhen"),
            device="device-1",
            signing_config=Path("/secure/signing.json"),
            data_dir=Path("/audio/release"),
            release_version="0.3.2",
            delivered_at="2026-08-13",
            release_artifact=Path("/delivery/customer.zip"),
            delivery_har=Path("/delivery/amphion_dingqiao.har"),
            evidence_output=Path("/evidence/0.3.2"),
            evaluation_artifact_root=Path("/evaluation/artifacts"),
            build_identity=Path("/delivery/build-identity.json"),
        )
        by_key = {task.key: task for task in tasks}

        self.assertEqual(3, gate.RELEASE_MAX_PARALLEL)
        self.assertNotIn("model-identity", by_key)
        self.assertIn("evaluation-artifacts", by_key)
        self.assertIn("cheap-contracts", by_key["android-release"].dependencies)
        self.assertIn("cheap-contracts", by_key["harmony-finish-compat"].dependencies)
        self.assertNotIn("android-release", by_key["harmony-finish-compat"].dependencies)
        self.assertEqual(("host-agc",), by_key["low-volume-regression"].dependencies)
        previous = "harmony-finish-compat"
        for mode in gate.DEVICE_MATRIX:
            current = f"device-{mode}"
            self.assertEqual((previous,), by_key[current].dependencies)
            previous = current
        self.assertIn("android-release", by_key["finalize"].dependencies)
        self.assertIn(previous, by_key["finalize"].dependencies)
        self.assertIn("low-volume-regression", by_key["finalize"].dependencies)

    def test_task_graph_rejects_missing_and_cyclic_dependencies(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate_invalid_graph")
        command = gate.GateCommand("noop", (sys.executable, "-c", "pass"), ROOT)

        with self.assertRaisesRegex(ValueError, "unknown dependency"):
            gate.validate_task_graph([gate.GateTask("a", command, ("missing",))])
        with self.assertRaisesRegex(ValueError, "cycle"):
            gate.validate_task_graph(
                [
                    gate.GateTask("a", command, ("b",)),
                    gate.GateTask("b", command, ("a",)),
                ]
            )

    def test_task_graph_really_runs_independent_tasks_concurrently(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate_parallel")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = textwrap.dedent(
                """
                import sys
                import time
                from pathlib import Path

                own = Path(sys.argv[1])
                peer = Path(sys.argv[2])
                own.write_text("started", encoding="utf-8")
                deadline = time.monotonic() + 2
                while not peer.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise SystemExit(0 if peer.exists() else 9)
                """
            )
            first = root / "first"
            second = root / "second"
            tasks = [
                gate.GateTask(
                    "first",
                    gate.GateCommand(
                        "first rendezvous",
                        (sys.executable, "-c", script, str(first), str(second)),
                        ROOT,
                    ),
                ),
                gate.GateTask(
                    "second",
                    gate.GateCommand(
                        "second rendezvous",
                        (sys.executable, "-c", script, str(second), str(first)),
                        ROOT,
                    ),
                ),
            ]

            self.assertEqual(0, gate.run_task_graph(tasks, max_parallel=2))

    def test_task_graph_failure_never_starts_dependents(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate_fail_fast")
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-run"
            failing = gate.GateCommand("fail", (sys.executable, "-c", "raise SystemExit(7)"), ROOT)
            dependent = gate.GateCommand(
                "dependent",
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                    str(marker),
                ),
                ROOT,
            )

            result = gate.run_task_graph(
                [
                    gate.GateTask("failing", failing),
                    gate.GateTask("dependent", dependent, ("failing",)),
                ],
                max_parallel=2,
            )

            self.assertEqual(7, result)
            self.assertFalse(marker.exists())

    def test_release_cleanliness_includes_untracked_inputs(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate_clean")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model"
            model.mkdir()
            for name in ("encoder.int8.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "bbpe.vocab"):
                (model / name).touch()
            signing = root / "signing.json"
            signing.touch()
            data = root / "data"
            data.mkdir()
            artifact = root / "delivery.zip"
            artifact.write_bytes(b"delivery")
            delivery_har = root / "amphion_dingqiao.har"
            delivery_har.write_bytes(b"har")
            provenance = root / "BUILD_PROVENANCE.json"
            provenance.write_bytes(b"provenance")
            evaluation_artifacts = root / "evaluation"
            evaluation_artifacts.mkdir()
            build_identity = root / "build-identity.json"
            build_identity.write_text("{}", encoding="utf-8")
            evidence_output = root / "delivery/evidence/new"
            (root / "delivery").mkdir()
            (root / "delivery/asr-sdk-release-history.json").write_text(
                json.dumps(
                    {
                        "deliveries": [
                            {
                                "platform": "harmony",
                                "version": "1.0.0",
                                "source_commit": "a" * 40,
                                "artifact": artifact.name,
                                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                                "artifact_size_bytes": artifact.stat().st_size,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess([], 0, stdout="?? untracked.cpp\n")
            with mock.patch.object(gate.subprocess, "run", return_value=completed) as run:
                with self.assertRaisesRegex(ValueError, "including untracked"):
                    gate.require_release_inputs(
                        root,
                        model,
                        signing,
                        data,
                        "1.0.0",
                        "2026-08-13",
                        artifact,
                        delivery_har,
                        evidence_output,
                        evaluation_artifacts,
                        build_identity,
                        provenance,
                    )
            self.assertIn("--untracked-files=all", run.call_args.args[0])

    def test_evidence_sync_owns_the_complete_implementation_source_set(self) -> None:
        sync = load_module(SYNC, "automatic_agc_evidence_sync")

        self.assertEqual(
            {
                "asr/native/audio-processing/src/amphion_audio_processing.cpp",
                "asr/android/sdk/src/main/java/com/amphion/asr/internal/StreamingAgcProcessor.kt",
                "asr/android/sdk/src/main/java/com/amphion/asr/internal/NativeAgcBackend.kt",
                "asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt",
                "asr/harmony/sdk/src/main/ets/com/amphion/asr/StreamingAgcProcessor.ts",
                "asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeAgcBackend.ets",
                "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets",
                "asr/tools/evaluate_automatic_agc_regression.py",
            },
            set(sync.IMPLEMENTATION_SOURCES),
        )

    def test_release_preflight_rejects_a_zip_with_a_different_har(self) -> None:
        gate = load_module(GATE, "automatic_agc_release_gate_zip_har")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "delivery.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("delivery/har/amphion_dingqiao.har", b"packaged-old-har")

            self.assertNotEqual(
                hashlib.sha256(b"tested-current-har").hexdigest(),
                gate.packaged_delivery_har_sha256(archive),
            )
        source = GATE.read_text(encoding="utf-8")
        self.assertIn("validate_asr_sdk_delivery.py", source)
        self.assertIn('"--build-identity"', source)

    def test_evidence_sync_check_never_writes_report(self) -> None:
        sync = load_module(SYNC, "automatic_agc_evidence_sync_no_write")
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text('{"implementation_source_sha256": {}}\n', encoding="utf-8")
            before = report.read_bytes()

            with contextlib.redirect_stderr(io.StringIO()):
                self.assertFalse(sync.check(report, ROOT))
            self.assertEqual(before, report.read_bytes())

    def test_evidence_runtime_check_binds_model_and_preserved_artifacts(self) -> None:
        sync = load_module(SYNC, "automatic_agc_evidence_runtime")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model"
            artifacts = root / "artifacts"
            model.mkdir()
            artifacts.mkdir()
            (model / "encoder.onnx").write_bytes(b"model")
            (artifacts / "cases.jsonl").write_bytes(b"cases")
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "evaluation_runtime": {
                            "model_sha256": {
                                "encoder.onnx": hashlib.sha256(b"model").hexdigest()
                            }
                        },
                        "preserved_artifact_sha256": {
                            "cases.jsonl": hashlib.sha256(b"cases").hexdigest()
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(sync.check_runtime_inputs(report, model, artifacts))
            (artifacts / "cases.jsonl").write_bytes(b"stale")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertFalse(sync.check_runtime_inputs(report, model, artifacts))

    def test_evidence_sync_has_no_fingerprint_only_update_escape_hatch(self) -> None:
        source = SYNC.read_text(encoding="utf-8")

        self.assertNotIn('add_argument("--update"', source)
        self.assertNotIn("def update(", source)
        self.assertNotIn("write_text(", source)

    def test_ci_runs_static_gate_before_native_builds(self) -> None:
        workflow = (ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")

        gate = workflow.index("run_automatic_agc_release_gate.py static")
        host_build = workflow.index("03_build_agc_native.sh host")
        android_build = workflow.index("03_build_agc_native.sh android-arm64-v8a")
        self.assertLess(gate, host_build)
        self.assertLess(gate, android_build)

    def test_every_agc_build_uses_the_pinned_tool_bootstrap(self) -> None:
        build = BUILD_AGC.read_text(encoding="utf-8")
        ensure = ENSURE_TOOLS.read_text(encoding="utf-8")

        self.assertIn('source "$SCRIPT_DIR/ensure_agc_build_tools.sh"', build)
        self.assertIn('"meson==1.7.0"', ensure)
        self.assertIn('"ninja==1.11.1.4"', ensure)
        self.assertIn('export MESON NINJA', ensure)
        self.assertIn('--force-reinstall', ensure)

    def test_android_release_build_is_isolated_strict_and_verifies_the_aar(self) -> None:
        source = ANDROID_RELEASE.read_text(encoding="utf-8")

        self.assertIn("mktemp -d", source)
        self.assertIn("git clone", source)
        self.assertIn(
            "submodule update --init --recursive third_party/sherpa-onnx",
            source,
        )
        self.assertNotIn("submodule update --init --recursive\n", source)
        self.assertIn('ls-tree "$SOURCE_COMMIT" -- third_party/sherpa-onnx', source)
        self.assertNotIn('third_party/sherpa-onnx" rev-parse HEAD', source)
        self.assertIn("04_build_android_so.sh", source)
        self.assertIn("AMPHION_REQUIRE_ANDROID_NATIVE_LIBS=1", source)
        self.assertIn(":sdk:assembleRelease", source)
        for task in (
            ":sdk:testDebugUnitTest",
            ":sdk:testReleaseUnitTest",
            ":sdk-dingqiao:testDebugUnitTest",
            ":sdk-dingqiao:testReleaseUnitTest",
        ):
            self.assertEqual(1, source.count(task))
        for library in (
            "libsherpa-onnx-jni.so",
            "libonnxruntime.so",
            "libamphion_audio_processing.so",
        ):
            self.assertIn(library, source)
        self.assertIn("actual != expected", source)

    def test_finalizer_cannot_skip_archive_attach_or_verify(self) -> None:
        source = FINALIZE.read_text(encoding="utf-8")

        self.assertIn("archive_release_gate_evidence.py", source)
        self.assertIn('"record-evidence"', source)
        self.assertIn('"verify-evidence"', source)

    def test_harmony_workspace_probe_preserves_the_real_submodule(self) -> None:
        submodule = ROOT / "third_party/sherpa-onnx"
        if not (submodule / ".git").exists():
            self.skipTest("sherpa-onnx submodule is not initialized")
        before_head = subprocess.check_output(
            ["git", "-C", str(submodule), "rev-parse", "HEAD"], text=True
        )
        before_status = subprocess.check_output(
            ["git", "-C", str(submodule), "status", "--porcelain=v1", "--untracked-files=all"],
            text=True,
        )

        subprocess.run(
            ["bash", "delivery/harmony-dingqiao/delivery/build_install_smoke.sh", "--prepare-only"],
            cwd=ROOT,
            check=True,
        )

        after_head = subprocess.check_output(
            ["git", "-C", str(submodule), "rev-parse", "HEAD"], text=True
        )
        after_status = subprocess.check_output(
            ["git", "-C", str(submodule), "status", "--porcelain=v1", "--untracked-files=all"],
            text=True,
        )
        self.assertEqual(before_head, after_head)
        self.assertEqual(before_status, after_status)


if __name__ == "__main__":
    unittest.main()
