import importlib.util
import sys
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_finish_compat_release_gate.py")
SPEC = importlib.util.spec_from_file_location("run_finish_compat_release_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def build_identity() -> dict[str, object]:
    return {
        "git_commit": "0123456789abcdef",
        "source_fingerprint_sha256": "source-fingerprint",
        "artifacts": {
            "amphion_asr_demo.hap": {"sha256": "hap-sha256"},
            "amphion_dingqiao.har": {"sha256": "har-sha256"},
        },
    }


def cycle(detail: str, trace: str, *, chars: int = 12) -> dict[str, str]:
    return {
        "status": "PASS",
        "detail": detail,
        "trace": trace,
        "finals": "1",
        "lastFinalsBeforeFinish": "0",
        "completes": "1",
        "errors": "0",
        "finalChars": str(chars),
        "liveStreams": "0",
    }


def callback_report(*, speech_end_chars: int = 12) -> dict[str, object]:
    return {
        "run_id": "callback-run",
        "mode": "callback-api-reentrant",
        "overall_status": "PASS",
        "device": "device-1",
        "build_identity": build_identity(),
        "cycles": [
            cycle(
                "callback-api-reentrant-speech-begin",
                "callback-api-speech-begin-0:start>callback-api-speech-begin-0:final-last>"
                "callback-api-speech-begin-0:complete",
                chars=0,
            ),
            cycle(
                "callback-api-reentrant-speech-end",
                "callback-api-speech-end-1:start>callback-api-speech-end-1:event-3>"
                "callback-api-speech-end-1:final-last>callback-api-speech-end-1:complete",
                chars=speech_end_chars,
            ),
            cycle(
                "callback-api-reentrant-result",
                "callback-api-result-2:start>callback-api-result-2:final-last>"
                "callback-api-result-2:complete",
            ),
        ],
    }


def finish_shutdown_report(*, completes: int = 1, terminal_order: bool = True) -> dict[str, object]:
    terminal = (
        "finish-shutdown-0:start>finish-shutdown-0:final-last>finish-shutdown-0:complete"
        if terminal_order
        else "finish-shutdown-0:start>finish-shutdown-0:complete>finish-shutdown-0:final-last"
    )
    item = cycle("finish-shutdown-drained", terminal)
    item["completes"] = str(completes)
    return {
        "run_id": "finish-shutdown-run",
        "mode": "finish-shutdown",
        "overall_status": "PASS",
        "device": "device-1",
        "build_identity": build_identity(),
        "cycles": [item],
    }


class FinishCompatReleaseGateTest(unittest.TestCase):
    def test_default_corpus_uses_versioned_test_data_cache(self) -> None:
        with mock.patch.object(sys, "argv", [str(SCRIPT)]):
            args = MODULE.parse_args()

        self.assertEqual(MODULE.DEFAULT_DEVICE_CORPUS, args.data_dir)
        self.assertIn(".cache/amphion-runtime/test-data/v1", str(args.data_dir))

    def test_verified_build_reuse_still_installs_before_both_modes(self) -> None:
        command = MODULE.build_verified_install_command("device-1")

        self.assertIn("build_install_smoke.sh", command[0])
        self.assertIn("--skip-build", command)
        self.assertIn("--device", command)
        self.assertIn("device-1", command)

    def test_verified_build_reuse_verifies_identity_before_install(self) -> None:
        identity = Path("/delivery/build-identity.json")
        with mock.patch.object(MODULE.subprocess, "run") as run:
            MODULE.prepare_verified_build(identity, "device-1")

        self.assertEqual(2, run.call_count)
        verify, install = [call.args[0] for call in run.call_args_list]
        self.assertIn("harmony_build_identity.py", verify[1])
        self.assertEqual(["--verify", str(identity)], verify[-2:])
        self.assertIn("build_install_smoke.sh", install[0])
        self.assertIn("--skip-build", install)

    def test_shared_raw_matrix_report_can_live_outside_summary_directory(self) -> None:
        gate_root = Path("/repo/build/finish-compat/run-1")
        raw_report = Path("/repo/build/automatic-agc/raw/device-run/report.json")

        self.assertEqual(
            "../../automatic-agc/raw/device-run/report.json",
            MODULE.report_reference(raw_report, gate_root),
        )

    def test_accepts_exact_vad_and_ptt_customer_sequences(self) -> None:
        result = MODULE.validate_gate_reports(callback_report(), finish_shutdown_report())

        self.assertEqual("PASS", result["status"])
        self.assertEqual(
            ["callback-api-reentrant", "finish-shutdown"],
            [item["mode"] for item in result["modes"]],
        )

    def test_rejects_empty_last_from_vad_speech_end_finish(self) -> None:
        with self.assertRaisesRegex(MODULE.GateFailure, "speech-end.*non-empty"):
            MODULE.validate_gate_reports(
                callback_report(speech_end_chars=0),
                finish_shutdown_report(),
            )

    def test_rejects_ptt_shutdown_that_loses_or_reorders_complete(self) -> None:
        with self.assertRaisesRegex(MODULE.GateFailure, "complete"):
            MODULE.validate_gate_reports(
                callback_report(),
                finish_shutdown_report(completes=0),
            )
        with self.assertRaisesRegex(MODULE.GateFailure, "last.*complete"):
            MODULE.validate_gate_reports(
                callback_report(),
                finish_shutdown_report(terminal_order=False),
            )

    def test_rejects_reports_from_different_builds_or_devices(self) -> None:
        report = finish_shutdown_report()
        report["device"] = "device-2"
        with self.assertRaisesRegex(MODULE.GateFailure, "same device"):
            MODULE.validate_gate_reports(callback_report(), report)

        report = finish_shutdown_report()
        report["build_identity"]["source_fingerprint_sha256"] = "other-source"
        with self.assertRaisesRegex(MODULE.GateFailure, "same build"):
            MODULE.validate_gate_reports(callback_report(), report)

    def test_requires_device_identity_and_accepts_repeated_speech_end_cycles(self) -> None:
        callback = callback_report()
        callback["cycles"].append(callback["cycles"][1].copy())
        result = MODULE.validate_gate_reports(callback, finish_shutdown_report())
        self.assertEqual(2, result["modes"][0]["speech_end_cycles"])

        callback["device"] = ""
        with self.assertRaisesRegex(MODULE.GateFailure, "device identity"):
            MODULE.validate_gate_reports(callback, finish_shutdown_report())

    def test_second_mode_always_reuses_the_first_modes_build(self) -> None:
        callback = MODULE.build_runner_command(
            mode="callback-api-reentrant",
            cycles=3,
            data_dir=Path("/tmp/corpus"),
            files=3,
            output_root=Path("/tmp/evidence"),
            skip_build_install=False,
        )
        finish = MODULE.build_runner_command(
            mode="finish-shutdown",
            cycles=10,
            data_dir=Path("/tmp/corpus"),
            files=3,
            output_root=Path("/tmp/evidence"),
            skip_build_install=True,
        )

        self.assertNotIn("--skip-build-install", callback)
        self.assertIn("--skip-build-install", finish)
        self.assertEqual("3", callback[callback.index("--cycles") + 1])
        self.assertEqual("10", finish[finish.index("--cycles") + 1])

    def test_release_gate_cannot_skip_installing_the_current_build(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--skip-build-install"],
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()

    def test_reuse_requires_an_explicit_build_identity(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [str(SCRIPT), "--reuse-verified-build"],
        ), self.assertRaises(SystemExit):
            MODULE.parse_args()

    def test_failure_summary_keeps_every_available_evidence_reference(self) -> None:
        root = Path("/tmp/gate")
        report_path = root / "runs/callback/report.json"
        observed = [("callback-api-reentrant", report_path, callback_report())]

        result = MODULE.failure_summary(
            {
                "schema_version": 1,
                "gate": "harmony-finish-compat",
                "source_commit": "0123456789abcdef",
            },
            MODULE.GateFailure("runner failed"),
            observed,
            root,
        )

        self.assertEqual("FAIL", result["status"])
        self.assertEqual("device-1", result["device"])
        self.assertEqual(build_identity(), result["build_identity"])
        self.assertEqual(
            "runs/callback/report.json",
            result["reports"]["callback-api-reentrant"],
        )


if __name__ == "__main__":
    unittest.main()
