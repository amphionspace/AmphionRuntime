from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).with_name("run_model_load_bench.py")
SPEC = importlib.util.spec_from_file_location("run_model_load_bench", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DeviceResultTest(unittest.TestCase):
    def test_parses_one_cold_and_three_pool_hit_creates(self) -> None:
        result = MODULE.parse_device_result(
            "LOADBENCH|version=1|api=createEngineAsync|runId=measure-001-abcd|status=PASS|"
            "punctuationRequested=true|punctuationLoaded=true|"
            "coldMs=4321|poolHitMs=8,7,9|fatal=\n",
            "measure-001-abcd",
        )

        self.assertEqual(4321, result.cold_ms)
        self.assertEqual([8, 7, 9], result.pool_hit_ms)

    def test_ignores_partial_or_stale_results(self) -> None:
        partial = (
            "LOADBENCH|version=1|api=createEngineAsync|runId=current|status=PASS|"
            "punctuationRequested=true|punctuationLoaded=true|coldMs=4"
        )
        stale = (
            "LOADBENCH|version=1|api=createEngineAsync|runId=old|status=PASS|"
            "punctuationRequested=true|punctuationLoaded=true|"
            "coldMs=4321|poolHitMs=8,7,9|fatal=\n"
        )

        self.assertIsNone(MODULE.parse_device_result(partial, "current"))
        self.assertIsNone(MODULE.parse_device_result(stale, "current"))

    def test_rejects_missing_pool_hit_sample(self) -> None:
        text = (
            "LOADBENCH|version=1|api=createEngineAsync|runId=current|status=PASS|"
            "punctuationRequested=true|punctuationLoaded=true|"
            "coldMs=4321|poolHitMs=8,7|fatal=\n"
        )

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "invalid sample counts"):
            MODULE.parse_device_result(text, "current")

    def test_rejects_a_result_from_the_synchronous_api(self) -> None:
        text = (
            "LOADBENCH|version=1|api=createEngine|runId=current|status=PASS|punctuationRequested=true|"
            "coldMs=4321|poolHitMs=8,7,9|fatal=\n"
        )

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "createEngineAsync"):
            MODULE.parse_device_result(text, "current")

    def test_rejects_silently_degraded_punctuation(self) -> None:
        text = (
            "LOADBENCH|version=1|api=createEngineAsync|runId=current|status=PASS|"
            "punctuationRequested=true|punctuationLoaded=false|"
            "coldMs=4321|poolHitMs=8,7,9|fatal=\n"
        )

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "did not load punctuation"):
            MODULE.parse_device_result(text, "current")

    def test_surfaces_device_failure_detail(self) -> None:
        text = (
            "LOADBENCH|version=1|api=createEngineAsync|runId=current|status=FAIL|"
            "punctuationRequested=true|"
            "coldMs=-1|poolHitMs=|fatal=license-1002200031\n"
        )

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "license-1002200031"):
            MODULE.parse_device_result(text, "current")


class StatisticsTest(unittest.TestCase):
    def test_reports_required_percentiles_with_linear_interpolation(self) -> None:
        stats = MODULE.timing_statistics([10, 20, 30, 40, 50])

        self.assertEqual(
            {"count": 5, "min": 10, "p50": 30.0, "p90": 46.0, "p95": 48.0, "max": 50},
            stats,
        )

    def test_single_sample_is_valid_for_every_percentile(self) -> None:
        stats = MODULE.timing_statistics([17])

        self.assertEqual(17.0, stats["p50"])
        self.assertEqual(17.0, stats["p95"])


class ModelIdentityTest(unittest.TestCase):
    def manifest(self, version: int) -> dict:
        digest_key = "source_sha256" if version == 2 else "sha256"
        suffix = "ort" if version == 2 else "onnx"
        return {
            "manifest_version": version,
            "bundles": {
                "zh-en/v1": [
                    {"name": f"encoder.int8.{suffix}", digest_key: "1" * 64},
                    {
                        "name": "decoder.int8.ort" if version == 2 else "decoder.onnx",
                        digest_key: "2" * 64,
                    },
                    {"name": f"joiner.int8.{suffix}", digest_key: "3" * 64},
                    {"name": "tokens.txt", digest_key: "4" * 64},
                    {"name": "bbpe.vocab", digest_key: "5" * 64},
                ],
                "punct-zhen/v1": [
                    {"name": f"model.int8.{suffix}", digest_key: "6" * 64}
                ],
            },
        }

    def test_normalizes_v1_and_v2_to_the_same_source_identity(self) -> None:
        self.assertEqual(
            MODULE.model_source_hashes_from_manifest(self.manifest(1)),
            MODULE.model_source_hashes_from_manifest(self.manifest(2)),
        )

    def test_rejects_a_manifest_without_punctuation(self) -> None:
        manifest = self.manifest(2)
        del manifest["bundles"]["punct-zhen/v1"]

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "punct-zhen"):
            MODULE.model_source_hashes_from_manifest(manifest)


class BaselineGateTest(unittest.TestCase):
    def test_default_gates_pass_at_exact_boundaries(self) -> None:
        gates = MODULE.evaluate_gates(
            {"p50": 80.0, "p95": 103.0},
            {"p50": 100.0, "p95": 100.0},
        )

        self.assertEqual("PASS", gates["status"])
        self.assertEqual("PASS", gates["p50"]["status"])
        self.assertEqual("PASS", gates["p95"]["status"])

    def test_fails_when_p50_improvement_is_under_twenty_percent(self) -> None:
        gates = MODULE.evaluate_gates(
            {"p50": 81.0, "p95": 90.0},
            {"p50": 100.0, "p95": 100.0},
        )

        self.assertEqual("FAIL", gates["status"])
        self.assertEqual("FAIL", gates["p50"]["status"])
        self.assertEqual("PASS", gates["p95"]["status"])

    def test_fails_when_p95_regresses_more_than_three_percent(self) -> None:
        gates = MODULE.evaluate_gates(
            {"p50": 70.0, "p95": 104.0},
            {"p50": 100.0, "p95": 100.0},
        )

        self.assertEqual("FAIL", gates["status"])
        self.assertEqual("PASS", gates["p50"]["status"])
        self.assertEqual("FAIL", gates["p95"]["status"])

    def test_extracts_baseline_from_report_schema(self) -> None:
        baseline = MODULE.extract_baseline_cold_statistics(
            {"statistics": {"cold_create_engine_async_ms": {"p50": 1250, "p95": 1600}}}
        )

        self.assertEqual({"p50": 1250.0, "p95": 1600.0}, baseline)

    def test_rejects_the_obsolete_synchronous_baseline_key(self) -> None:
        report = {"statistics": {"cold_create_ms": {"p50": 1250, "p95": 1600}}}

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "cold_create_engine_async_ms"):
            MODULE.extract_baseline_cold_statistics(report)

    def test_accepts_an_exact_comparison_identity(self) -> None:
        identity = {
            "device": "serial",
            "profile": {"api": "SpeechRecognizeSdk.createEngineAsync"},
            "model_source_sha256": {"encoder": "a" * 64},
        }

        MODULE.validate_baseline_comparability(
            {"comparison_identity": identity}, identity
        )

    def test_rejects_a_baseline_from_another_model(self) -> None:
        expected = {
            "device": "serial",
            "profile": {"api": "SpeechRecognizeSdk.createEngineAsync"},
            "model_source_sha256": {"encoder": "a" * 64},
        }
        report = {
            "comparison_identity": {
                "device": "serial",
                "profile": {"api": "SpeechRecognizeSdk.createEngineAsync"},
                "model_source_sha256": {"encoder": "b" * 64},
            }
        }

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "model_source_sha256"):
            MODULE.validate_baseline_comparability(report, expected)

    def test_rejects_a_baseline_without_identity(self) -> None:
        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "comparison_identity"):
            MODULE.validate_baseline_comparability({}, {"device": "serial"})


class FakeHdc:
    def __init__(self, pid_outputs: list[str]):
        self.pid_outputs = iter(pid_outputs)
        self.calls: list[tuple[str, ...]] = []

    def shell(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        stdout = next(self.pid_outputs, "") if args[0] == "pidof" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout=stdout, stderr="")


class ProcessIsolationTest(unittest.TestCase):
    def test_force_stop_waits_until_the_old_process_is_gone(self) -> None:
        hdc = FakeHdc(["4321\r\n", ""])

        MODULE.force_stop_and_wait(hdc, timeout=1.0, poll_interval=0.0)

        self.assertEqual(("aa", "force-stop", MODULE.BUNDLE), hdc.calls[0])
        self.assertEqual(2, sum(call[0] == "pidof" for call in hdc.calls))

    def test_force_stop_fails_instead_of_recording_a_pool_hit_as_cold(self) -> None:
        hdc = FakeHdc(["4321"])

        with self.assertRaisesRegex(MODULE.LoadBenchFailure, "did not exit"):
            MODULE.force_stop_and_wait(hdc, timeout=0.000001, poll_interval=0.0)


if __name__ == "__main__":
    unittest.main()
