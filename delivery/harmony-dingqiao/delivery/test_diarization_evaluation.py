from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).parent))
import diarization_evaluation as gate


class EvaluationGateTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        with wave.open(str(self.root / "audio.wav"), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 64000)
        (self.root / "ref.rttm").write_text(
            "SPEAKER sample 1 0 2 <NA> <NA> A <NA>\n"
            "SPEAKER sample 1 2 2 <NA> <NA> B <NA>\n")
        self.spec = {"scope": "fixed-diagnostic-subset", "cases": [{
            "id": "two", "tier": "public", "audio": "audio.wav",
            "referenceRttm": "ref.rttm", "normalization": "native 16 kHz channel 0; no trimming",
            "annotationStatus": "official RTTM"}]}
        self.manifest = gate.freeze(self.spec, self.root)

    def captures(self, turns):
        report = {"overall_status": "PASS", "cycles": [{
            "speakerTurnsHex": json.dumps(turns).encode("utf-16-be").hex()}]}
        path = self.root / (gate.digest(report) + ".json")
        path.write_text(json.dumps(report))
        binding = {"commit": "1" * 40, "device": "test", "systemVersion": "test"}
        return {"binding": binding, "cases": {"two": {
            "inputSha256": self.manifest["cases"][0]["audio"]["sha256"],
            "bindingSha256": gate.digest(binding), "report": gate.file_record(path)}}}

    def test_freeze_verifies_bytes_and_refuses_overwrite(self):
        gate.verify_manifest(self.manifest)
        target = self.root / "evaluation-manifest.json"
        gate.write_new(target, self.manifest)
        with self.assertRaises(FileExistsError):
            gate.write_new(target, self.manifest)
        self.manifest["cases"][0]["sourceOffsetSeconds"] = 10
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            gate.verify_manifest(self.manifest)
        self.manifest = gate.freeze(self.spec, self.root)
        (self.root / "audio.wav").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            gate.verify_manifest(self.manifest)

    def test_multirecording_rttm_cannot_silently_merge_people(self):
        with (self.root / "ref.rttm").open("a") as stream:
            stream.write("SPEAKER other 1 0 1 <NA> <NA> C <NA>\n")
        with self.assertRaisesRegex(ValueError, "one recording"):
            gate.freeze(self.spec, self.root)

    def test_empty_or_wrong_geometry_and_duplicate_ids_are_rejected(self):
        with wave.open(str(self.root / "audio.wav"), "wb") as wav:
            wav.setparams((2, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0" * 64000)
        with self.assertRaisesRegex(ValueError, "mono PCM16"):
            gate.freeze(self.spec, self.root)
        with wave.open(str(self.root / "audio.wav"), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 64000)
        self.spec["cases"].append(copy.deepcopy(self.spec["cases"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            gate.freeze(self.spec, self.root)
        with self.assertRaisesRegex(ValueError, "empty"):
            gate.freeze({"scope": "test", "cases": []}, self.root)

    def test_lifecycle_only_report_cannot_release_an_identity_failure(self):
        captures = self.captures([{"beginTime": 0, "endTime": 4000, "speakerIndex": 0}])
        result = gate.assess(self.manifest, captures)
        self.assertEqual("INCONCLUSIVE", result["releaseStatus"])
        self.assertEqual(0, result["results"]["two"]["metrics"]["minoritySpeakerRecall"])
        self.assertEqual("INCONCLUSIVE", result["results"]["two"]["gates"]["identityAccuracy"])
        captures["cases"]["two"]["inputSha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "input mismatch"):
            gate.assess(self.manifest, captures)

    def test_review_from_another_artifact_cannot_turn_gate_green(self):
        captures = self.captures([{"beginTime": 0, "endTime": 4000, "speakerIndex": 0}])
        review = self.root / "review.json"
        review.write_text(json.dumps({"bindingSha256": "wrong", "assertions": {
            "identityAccuracy": [{"status": "PASS", "evidence": "reviewed"}]}}))
        captures["cases"]["two"]["review"] = gate.file_record(review)
        with self.assertRaisesRegex(ValueError, "review does not bind"):
            gate.assess(self.manifest, captures)

    def test_public_collapse_veto_and_protocol_pairing(self):
        before = gate.assess(self.manifest, self.captures([
            {"beginTime": 0, "endTime": 2000, "speakerIndex": 0},
            {"beginTime": 2000, "endTime": 4000, "speakerIndex": 1}]))
        after = gate.assess(self.manifest, self.captures([
            {"beginTime": 0, "endTime": 4000, "speakerIndex": 0}]))
        comparison = gate.compare(before, after)
        self.assertEqual("FAIL", comparison["status"])
        self.assertTrue(any("collapse" in r for r in comparison["regressions"]))
        after["manifestSha256"] = "different"
        with self.assertRaisesRegex(ValueError, "unpaired manifest"):
            gate.compare(before, after)

    def test_better_der_alone_does_not_release_and_raw_id_permutation_is_not_regression(self):
        before = gate.assess(self.manifest, self.captures([
            {"beginTime": 0, "endTime": 2000, "speakerIndex": 0},
            {"beginTime": 2000, "endTime": 4000, "speakerIndex": 1}]))
        after = gate.assess(self.manifest, self.captures([
            {"beginTime": 0, "endTime": 2000, "speakerIndex": 1},
            {"beginTime": 2000, "endTime": 4000, "speakerIndex": 0}]))
        comparison = gate.compare(before, after)
        self.assertEqual([], comparison["regressions"])
        self.assertEqual("INCONCLUSIVE", comparison["releaseStatus"])
        self.assertEqual(0, comparison["metricDeltas"]["two"]["der"])

    def test_cli_missing_evidence_is_nonzero_and_cannot_overwrite(self):
        manifest = self.root / "manifest.json"
        captures = self.root / "captures.json"
        output = self.root / "assessment.json"
        gate.write_new(manifest, self.manifest)
        gate.write_new(captures, {"binding": {}, "cases": {}})
        command = [sys.executable, gate.__file__, "evaluate", "--manifest", str(manifest),
                   "--captures", str(captures), "--output", str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(2, result.returncode, result.stderr)
        original = output.read_bytes()
        self.assertNotEqual(0, subprocess.run(command, capture_output=True).returncode)
        self.assertEqual(original, output.read_bytes())

    def test_existing_failure_blocks_release_without_being_called_a_regression(self):
        assessment = gate.assess(self.manifest, self.captures([
            {"beginTime": 0, "endTime": 4000, "speakerIndex": 0}]))
        assessment["results"]["two"]["gates"]["memory"] = "FAIL"
        result = gate.compare(assessment, copy.deepcopy(assessment))
        self.assertEqual("FAIL", result["releaseStatus"])
        self.assertEqual([], result["regressions"])
        self.assertEqual(["two:memory:FAIL"], result["existingFailures"])

    def test_failed_preflight_never_collects_previous_session(self):
        with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=2)) as run:
            result = gate.run_tier(self.manifest, "public", self.root / "run")
        self.assertEqual(1, run.call_count)
        self.assertIsNone(result["runs"][0]["captureExitCode"])
        self.assertEqual("FAIL", result["status"])
        self.assertIn("paced", run.call_args.args[0])
        self.assertEqual("cpu", run.call_args.args[0][run.call_args.args[0].index("--diarization-encoder") + 1])

    def test_encoder_backend_is_forwarded_and_bound_in_run_summary(self):
        for backend in ("cpu", "npu", "auto"):
            with self.subTest(backend=backend):
                with mock.patch.object(gate.subprocess, "run", return_value=mock.Mock(returncode=2)) as run:
                    result = gate.run_tier(self.manifest, "public", self.root / backend,
                                           encoder_backend=backend)
                command = run.call_args.args[0]
                self.assertEqual(backend, command[command.index("--diarization-encoder") + 1])
                self.assertEqual(backend, result["encoderBackend"])
                self.assertEqual(backend, result["runs"][0]["encoderBackend"])
                self.assertIn("--capture-diagnostics", command)

    def test_encoder_cli_does_not_override_explicit_npu_or_auto(self):
        for backend in ("npu", "auto"):
            with self.subTest(backend=backend):
                arguments = [gate.__file__, "run", "--manifest", "manifest.json",
                             "--tier", "public", "--output", "unused",
                             "--diarization-encoder", backend]
                with mock.patch.object(sys, "argv", arguments), mock.patch.object(gate, "read", return_value=self.manifest), \
                        mock.patch.object(gate, "run_tier", return_value={"status": "CAPTURED"}) as run, \
                        mock.patch("builtins.print"):
                    self.assertEqual(2, gate.main())
                self.assertEqual(backend, run.call_args.kwargs["encoder_backend"])

    def test_invalid_encoder_backend_fails_before_device_access_or_output(self):
        with mock.patch.object(gate.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "encoder"):
                gate.run_tier(self.manifest, "public", self.root / "run", encoder_backend="gpu")
        run.assert_not_called()
        self.assertFalse((self.root / "run").exists())

    def test_longer_anchor_uses_window_carrier_and_captures_failed_exact_run(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["cases"][0]["durationSeconds"] = 124
        manifest["cases"][0]["tier"] = "anchor"
        manifest["manifestSha256"] = gate.digest({k: v for k, v in manifest.items() if k != "manifestSha256"})
        def execute(command, **kwargs):
            if "--output-root" in command and "--mode" in command:
                target = Path(command[command.index("--output-root") + 1]) / "run" / "report.json"
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps({"diagnostics": {"status": "CAPTURED"}}))
                return mock.Mock(returncode=1)
            return mock.Mock(returncode=0)
        with mock.patch.object(gate.subprocess, "run", side_effect=execute) as run:
            result = gate.run_tier(manifest, "anchor", self.root / "run")
        self.assertEqual(1, run.call_count)
        self.assertIn("diarization-windows", run.call_args_list[0].args[0])
        self.assertEqual("FAIL", result["status"])
        self.assertEqual(0, result["runs"][0]["captureExitCode"])

    def test_inconclusive_anchors_block_expansion_before_device_access(self):
        with mock.patch.object(gate.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "paired"):
                gate.run_tier(self.manifest, "recordings", self.root / "run")
        run.assert_not_called()
        self.assertFalse((self.root / "run").exists())

    def test_bounded_jobs_cannot_hide_growing_pcm_backlog_or_rss(self):
        points = [{"sessionId": "s", "event": "DIARIZATION_QUEUE", "fields": {
            "pendingJobs": 0, "audioEndSample": i*20*16000, "audioDelayMs": i*2000}}
                  for i in range(7)]
        points.append({"sessionId": "s", "event": "DIARIZATION_DRAINED", "fields": {}})
        report = {"memory": {"status": "PASS", "observation_seconds": 120,
                             "rss_third_medians_mb": [100, 110, 120], "rss_slope_mb_per_minute": -1}}
        result = gate.runtime_evidence(report, points)
        self.assertEqual("INCONCLUSIVE", result["realtime"])
        self.assertEqual("INCONCLUSIVE", result["memory"])
        report["memory"]["status"] = "FAIL"
        points[0]["fields"]["pendingJobs"] = 3
        result = gate.runtime_evidence(report, points)
        self.assertEqual("FAIL", result["realtime"])
        self.assertEqual("FAIL", result["memory"])

    def test_generic_rss_alarm_is_not_a_diarization_failure(self):
        memory = {"status": "FAIL", "rss_growth_mb": 85.650,
                  "max_rss_growth_mb": 64.0, "thread_growth": -0.5,
                  "max_thread_growth": 2, "observation_seconds": 87.733,
                  "rss_third_medians_mb": [562.32, 506.396, 488.082],
                  "rss_slope_mb_per_minute": -17.813}
        original = copy.deepcopy(memory)
        self.assertEqual("INCONCLUSIVE", gate.runtime_evidence({"memory": memory}, [])["memory"])
        captures = self.captures([])
        record = captures["cases"]["two"]["report"]
        path = Path(record["path"])
        report = json.loads(path.read_text())
        report["memory"] = memory
        path.write_text(json.dumps(report))
        captures["cases"]["two"]["report"] = gate.file_record(path)
        result = gate.assess(self.manifest, captures)
        self.assertEqual("INCONCLUSIVE", result["results"]["two"]["gates"]["memory"])
        self.assertEqual(original, memory)

    def test_falling_process_rss_does_not_prove_phase_aligned_memory_stability(self):
        report = {"memory": {"status": "PASS", "observation_seconds": 120,
                             "rss_third_medians_mb": [600, 500, 400],
                             "rss_slope_mb_per_minute": -100}}
        self.assertEqual("INCONCLUSIVE", gate.runtime_evidence(report, [])["memory"])

    def test_bound_review_can_resolve_advisory_but_cannot_override_hard_failures(self):
        for threads, enforced, expected in ((0, False, "PASS"), (3, False, "FAIL"), (0, True, "FAIL")):
            with self.subTest(threads=threads, enforced=enforced):
                captures = self.captures([])
                capture = captures["cases"]["two"]
                path = Path(capture["report"]["path"])
                report = json.loads(path.read_text())
                report["memory"] = {"status": "FAIL", "rss_growth_mb": 85.650,
                                    "max_rss_growth_mb": 64, "thread_growth": threads,
                                    "max_thread_growth": 2, "rss_growth_limit_enforced": enforced}
                path.write_text(json.dumps(report))
                capture["report"] = gate.file_record(path)
                review = self.root / "review.json"
                review.write_text(json.dumps({
                    "inputSha256": capture["inputSha256"], "bindingSha256": capture["bindingSha256"],
                    "captureHashes": {"report": capture["report"]["sha256"]},
                    "assertions": {"memory": [{"status": "PASS", "evidence": "same-phase review fixture"}]}}))
                capture["review"] = gate.file_record(review)
                result = gate.assess(self.manifest, captures)
                self.assertEqual(expected, result["results"]["two"]["gates"]["memory"])
                self.assertNotEqual("PASS", result["releaseStatus"])


if __name__ == "__main__":
    unittest.main()
