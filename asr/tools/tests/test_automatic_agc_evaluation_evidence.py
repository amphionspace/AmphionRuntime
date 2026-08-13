import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "asr/test-fixtures/voiceprint-fallback/001_recognize.wav"
REPORT = ROOT / "asr/android/reports/automatic-agc-evaluation/report.json"
RUNNER = ROOT / "asr/tools/evaluate_automatic_agc_regression.py"


class AutomaticAgcEvaluationEvidenceTest(unittest.TestCase):
    def test_report_separates_level_snr_and_long_audio_claims(self) -> None:
        report = json.loads(REPORT.read_text(encoding="utf-8"))

        self.assertEqual(
            ["overall_level_dbfs", "snr_db", "long_audio_time_region"],
            report["evaluation_axes"],
        )
        self.assertEqual("AGC does not improve SNR", report["customer_snr"]["conclusion"])
        self.assertTrue(all(value < 20 for value in report["customer_snr"]["incorrect_both_modes_db"]))
        self.assertEqual(
            "local_benefit_not_complete_transcript",
            report["long_audio"]["claim_scope"],
        )

        normal = report["aishell3"]["original"]
        confidence_interval = normal["paired_bootstrap_cer_delta_95_percent_points"]
        self.assertLessEqual(confidence_interval[0], 0.0)
        self.assertGreaterEqual(confidence_interval[1], 0.0)
        self.assertEqual("1.13.1", report["evaluation_runtime"]["sherpa_onnx_version"])
        self.assertEqual(
            {"encoder.int8.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "bbpe.vocab"},
            set(report["evaluation_runtime"]["model_sha256"]),
        )
        for name, digest in report["preserved_artifact_sha256"].items():
            self.assertRegex(name, r"\.(json|jsonl)$")
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        applicability = report["evaluation_applicability_review"]
        self.assertEqual(
            "existing_accuracy_evaluation_remains_applicable",
            applicability["decision"],
        )
        self.assertIn("were not rerun", applicability["not_claimed"])
        self.assertEqual(
            {
                "test_agc_signal_domains",
                "test_harmony_streaming_agc_processor",
                "repository_low_volume_regression_off_on",
            },
            set(applicability["rerun_verification"]),
        )

    def test_fixture_report_and_reproduction_runner_stay_in_sync(self) -> None:
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        regression = report["repository_low_volume_regression"]

        for relative_path, expected_sha256 in report["implementation_source_sha256"].items():
            source = ROOT / relative_path
            self.assertTrue(source.is_file(), relative_path)
            self.assertEqual(
                expected_sha256,
                hashlib.sha256(source.read_bytes()).hexdigest(),
                relative_path,
            )

        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), regression["source_sha256"])
        self.assertEqual(-80, regression["target_dbfs"])
        self.assertNotEqual(regression["reference"], regression["off_hypothesis"])
        self.assertEqual(regression["reference"], regression["agc_hypothesis"])

        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn(regression["source_sha256"], runner)
        self.assertIn(regression["reference"], runner)
        self.assertIn(regression["off_hypothesis"], runner)
        self.assertIn('"--model-dir"', runner)
        self.assertIn('"--agc-lib"', runner)

    def test_scaling_rejects_silence(self) -> None:
        spec = importlib.util.spec_from_file_location("automatic_agc_regression", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with self.assertRaisesRegex(ValueError, "silent"):
            module.scale_to_dbfs([0.0] * 160, -80.0)


if __name__ == "__main__":
    unittest.main()
