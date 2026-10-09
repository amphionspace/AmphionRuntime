from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
import verify_community_encoder_execution as verifier


class EncoderExecutionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.run = self.root / "run-100"
        self.run.mkdir()
        self.runner_id = "runner-test"
        self.identity = {"source_fingerprint_sha256": "a"*64,
                         "artifacts": {name: {"sha256": "b"*64} for name in verifier.ARTIFACTS}}
        self.identity_path = self.root / "identity.json"
        self.identity_path.write_text(json.dumps(self.identity))
        self.events = [self.event(1, "START_LISTENING"), self.event(2, verifier.WINDOW, {
            "encoderBackend": "npu", "encoderDevice": "KIRIN990", "encoderMs": 0,
            "jobId": "w0001", "windowStartSample": 0}),
            self.event(3, "CALLBACK_RESULT", {"isLast": True, "isFinal": True, "text": "private-customer-text"}),
            self.event(4, "CALLBACK_COMPLETE")]
        self.binding = {"schemaVersion": 1, "runnerRunId": self.runner_id,
                        "diagnosticRunId": "run-100", "diarizationEncoder": "npu", "mode": "paced",
                        "requestedCycles": 1, "completedCycles": 1,
                        "startedAtMs": 100, "finishedAtMs": 200, "diagnosticSessions": ["session-1"]}
        self.report_path = self.root / "report.json"
        self.report = {"run_id": self.runner_id, "mode": "paced", "overall_status": "PASS",
                       "build_identity": copy.deepcopy(self.identity), "input_corpus_sha256": "c"*64,
                       "configuration": {"cycles": 1, "diarization_encoder": "npu"},
                       "application": {"completed": "1", "starts": "1", "diagnosticsStatus": "EXPORTED", "diagnosticsRunId": "run-100"},
                       "diagnostics": {"status": "CAPTURED", "run_id": "run-100"}}
        metadata = {"manifest.json": {"schemaVersion": 2, "runId": "run-100",
                                      "fullEventJournal": "events.full.ndjson", "fullEventJournalRunId": "run-100"},
                    "summary.json": {"runId": "run-100", "sessions": [{"sessionId": "session-1"}]},
                    "build-identity.json": {"binaryHashStatus": "not-available-at-runtime"},
                    "effective-config.json": {"enabled": True}}
        for name, value in metadata.items():
            (self.run / name).write_text(json.dumps(value))
        (self.run / "events.ndjson").write_text("")
        self.save()

    def event(self, sequence, name, fields=None):
        return {"sequence": sequence, "runId": "run-100", "sessionId": "session-1",
                "engineId": "engine-1", "sessionGeneration": 1, "wallTimeMs": 100+sequence,
                "event": name, "fields": fields or {}}

    def save(self):
        (self.run / "events.full.ndjson").write_text("".join(json.dumps(event)+"\n" for event in self.events))
        (self.run / f"stress-binding-{self.runner_id}.json").write_text(json.dumps(self.binding))
        self.report["diagnostics"]["files"] = {path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                                for path in self.run.iterdir()}
        self.report_path.write_text(json.dumps(self.report))

    def verify(self, source=None, **kwargs):
        return verifier.verify_capture(source or self.run, self.report_path, self.identity_path,
                                       requested_backend=kwargs.pop("requested_backend", "npu"), **kwargs)

    def test_empty_windows_cannot_pass(self):
        result = verifier.check_windows([], require_backend="npu", require_device="kirin")
        self.assertEqual("FAIL", result["status"])
        self.assertEqual(0, result["windowCount"])

    def test_complete_capture_binds_hashes_without_leaking_text_or_vectors(self):
        result = self.verify()
        self.assertEqual("PASS", result["status"])
        self.assertEqual("PASS", result["kirinAcceptance"])
        self.assertEqual({"npu": 1}, result["observedBackendCounts"])
        self.assertEqual(0, result["encoderMs"]["median"])
        self.assertEqual(0, result["windowsWithVectorEvidence"])
        self.assertNotIn("private-customer-text", json.dumps(result))
        self.assertIn("not proof", result["scopeStatement"])
        self.assertEqual(hashlib.sha256(self.report_path.read_bytes()).hexdigest(), result["inputs"]["report"]["sha256"])
        self.assertEqual("not-available-at-runtime", json.loads((self.run / "build-identity.json").read_text())["binaryHashStatus"])

    def test_every_window_backend_device_time_and_identity_is_checked(self):
        mutations = (("encoderBackend", "cpu"), ("encoderDevice", "otherNpu"), ("encoderMs", -1),
                     ("encoderMs", float("nan")), ("encoderMs", float("inf")), ("encoderMs", True),
                     ("windowStartSample", -1), ("jobId", ""), ("encoderMs", None))
        original = copy.deepcopy(self.events[1]["fields"])
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                self.events[1]["fields"] = dict(original, **{field: value})
                self.save()
                result = self.verify()
                self.assertEqual("FAIL", result["status"])
                self.assertEqual(1, result["firstErrorIndex"])
        for field in ("encoderBackend", "encoderDevice", "encoderMs"):
            self.events[1]["fields"] = copy.deepcopy(original)
            del self.events[1]["fields"][field]
            self.save()
            self.assertEqual("FAIL", self.verify()["status"])

    def test_duplicate_windows_or_sequence_fail_without_reordering(self):
        duplicate = copy.deepcopy(self.events[1])
        duplicate["sequence"] = 3
        self.events.insert(2, duplicate)
        self.events[3]["sequence"], self.events[4]["sequence"] = 4, 5
        self.save()
        self.assertEqual("FAIL", self.verify()["status"])
        self.events.pop(2)
        self.events[2]["sequence"] = 1
        self.save()
        self.assertIn("invalid-or-repeated-sequence", [error["code"] for error in self.verify()["errors"]])

    def test_full_journal_cannot_omit_a_sequence_or_a_whole_runner_session(self):
        self.events[1]["sequence"] = 3
        self.events[2]["sequence"], self.events[3]["sequence"] = 4, 5
        self.save()
        self.assertIn("missing-journal-sequence", [error["code"] for error in self.verify()["errors"]])
        for sequence, event in enumerate(self.events, 1):
            event["sequence"] = sequence
        self.report["application"]["starts"] = "2"
        self.save()
        self.assertIn("runner-diagnostic-session-count-mismatch", [error["code"] for error in self.verify()["errors"]])

    def test_relicense_counts_main_and_recovery_session_starts(self):
        recovery = copy.deepcopy(self.events)
        for event in recovery:
            event["sequence"] += len(self.events)
            event["sessionId"], event["engineId"] = "session-recovery", "engine-recovery"
        self.events.extend(recovery)
        summary_path = self.run / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["sessions"].append({"sessionId": "session-recovery"})
        summary_path.write_text(json.dumps(summary))
        self.binding["diagnosticSessions"].append("session-recovery")
        self.binding["mode"] = self.report["mode"] = "finish-shutdown-relicense"
        self.report["cycles"] = [{"recoveryStarts": "1"}]
        self.save()
        self.assertEqual("PASS", self.verify()["status"])
        self.report["cycles"][0]["recoveryStarts"] = "2"
        self.save()
        self.assertIn("runner-diagnostic-session-count-mismatch", [error["code"] for error in self.verify()["errors"]])

    def test_cpu_control_and_auto_fallback_do_not_establish_strict_kirin_acceptance(self):
        self.events[1]["fields"].update(encoderBackend="cpu", encoderDevice="cpu")
        for requested in ("cpu", "auto"):
            self.binding["diarizationEncoder"] = requested
            self.report["configuration"]["diarization_encoder"] = requested
            self.save()
            result = self.verify(requested_backend=requested, require_backend="cpu", require_device="cpu")
            self.assertEqual("PASS", result["status"])
            self.assertEqual("NOT_ESTABLISHED", result["kirinAcceptance"])
            self.assertEqual("FAIL", self.verify(requested_backend=requested)["status"])

    def test_requested_encoder_and_foreign_build_cannot_match(self):
        self.assertEqual("FAIL", self.verify(requested_backend="auto")["status"])
        for key in ("source_fingerprint_sha256", "artifacts"):
            original = copy.deepcopy(self.report["build_identity"])
            if key == "artifacts":
                self.report["build_identity"][key]["amphion_asr.har"]["sha256"] = "d"*64
            else:
                self.report["build_identity"][key] = "d"*64
            self.save()
            self.assertEqual("FAIL", self.verify()["status"])
            self.report["build_identity"] = original

    def test_runtime_error_empty_and_invalid_terminal_callback_fail(self):
        self.events[1]["event"] = "CALLBACK_ERROR"
        self.save()
        self.assertEqual("FAIL", self.verify()["status"])
        self.events[1]["event"] = verifier.WINDOW
        self.events[2]["fields"]["isLast"] = False
        self.save()
        self.assertEqual("FAIL", self.verify()["status"])
        self.events[2]["fields"]["isLast"] = True
        self.events[3]["sequence"] = 3
        self.events[2]["sequence"] = 4
        self.events[2], self.events[3] = self.events[3], self.events[2]
        self.save()
        self.assertEqual("FAIL", self.verify()["status"])

    def test_explicit_export_marker_hashes_run_and_sessions_are_required(self):
        for key, value in (("runnerRunId", "other"), ("diagnosticRunId", "other"),
                           ("mode", "burst"), ("completedCycles", 0),
                           ("diagnosticSessions", ["other-session"]), ("finishedAtMs", 100)):
            original = copy.deepcopy(self.binding)
            self.binding[key] = value
            self.save()
            self.assertEqual("FAIL", self.verify()["status"])
            self.binding = original
        self.save()
        (self.run / "events.full.ndjson").write_text((self.run / "events.full.ndjson").read_text()+"\n")
        self.assertEqual("FAIL", self.verify()["status"])
        self.save()
        (self.run / f"stress-binding-{self.runner_id}.json").unlink()
        self.assertEqual("INCONCLUSIVE", self.verify()["status"])

    def test_foreign_diagnostic_event_owner_or_unbound_journal_fail(self):
        for field, value in (("runId", "other-run"), ("sessionId", "other-session"), ("engineId", "other-engine")):
            original = copy.deepcopy(self.events[1])
            self.events[1][field] = value
            self.save()
            self.assertEqual("FAIL", self.verify()["status"])
            self.events[1] = original
        manifest = json.loads((self.run / "manifest.json").read_text())
        manifest["fullEventJournalRunId"] = "other-run"
        (self.run / "manifest.json").write_text(json.dumps(manifest))
        self.save()
        self.assertEqual("FAIL", self.verify()["status"])

    def test_optional_vectors_validate_real_values_and_allow_blocked_nan_sentinels(self):
        fields = self.events[1]["fields"]
        fields["embeddings"] = [0.1] * (3*256)
        fields["runRanges"] = [0, 0, 0, 120]
        fields["runEmbeddings"] = [0.1] * 256
        fields["segmentations"] = [value for _ in range(589) for value in (1, 0, 0)]
        self.save()
        result = self.verify()
        self.assertEqual("PASS", result["status"])
        self.assertNotIn("runEmbeddings", json.dumps(result))
        fields["runEmbeddings"][0] = None
        self.save()
        self.assertEqual("FAIL", self.verify()["status"])
        fields["runEmbeddings"] = [None] * 256
        fields["segmentations"][1] = 1
        self.save()
        self.assertEqual("PASS", self.verify()["status"])
        fields["embeddings"][0] = float("inf")
        self.save()
        self.assertEqual("FAIL", self.verify()["status"])

    def test_zip_uses_explicit_run_and_full_journal_instead_of_truncated_snapshot(self):
        archive = self.root / "diagnostics.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for path in self.run.iterdir():
                zipped.write(path, "package/run-100/"+path.name)
            zipped.writestr("package/collection.json", json.dumps({"runIds": ["run-100"], "runCount": 1}))
        self.assertEqual("PASS", self.verify(archive)["status"])
        self.assertEqual("PASS", self.verify(self.run / "events.full.ndjson")["status"])
        with self.assertRaisesRegex(ValueError, "bounded"):
            self.verify(self.run / "events.ndjson")
        other = self.root / "wrong-collection.zip"
        with zipfile.ZipFile(other, "w") as zipped:
            for path in self.run.iterdir():
                zipped.write(path, "package/run-100/"+path.name)
            zipped.writestr("package/collection.json", json.dumps({"runIds": ["other"], "runCount": 1}))
        with self.assertRaisesRegex(ValueError, "collection"):
            self.verify(other)

    def test_unbound_explicit_ndjson_is_inconclusive_and_cli_cannot_overwrite(self):
        orphan = self.root / "unbound.ndjson"
        orphan.write_bytes((self.run / "events.full.ndjson").read_bytes())
        self.assertEqual("INCONCLUSIVE", self.verify(orphan)["status"])
        output = self.root / "verification.json"
        command = [sys.executable, verifier.__file__, "--run-directory", str(self.run),
                   "--report", str(self.report_path), "--build-identity", str(self.identity_path),
                   "--requested-backend", "npu", "--output", str(output)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, first.returncode, first.stderr)
        original = output.read_bytes()
        self.assertNotEqual(0, subprocess.run(command, capture_output=True).returncode)
        self.assertEqual(original, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
