from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MATRIX = Path(__file__).with_name("diarization_acceptance_matrix.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATRIX_MODULE = load_module("acceptance_matrix", Path(__file__).with_name("validate_diarization_acceptance_matrix.py"))
ANALYZER = load_module("diagnostics_analyzer", Path(__file__).with_name("analyze_diarization_diagnostics.py"))


class AcceptanceMatrixTest(unittest.TestCase):
    def test_repository_matrix_is_valid_and_keeps_public_precision_blocked(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        result = MATRIX_MODULE.validate(matrix, repo_root=ROOT, check_evidence=True)
        self.assertEqual("PASS", result["validationStatus"])
        self.assertEqual("FAIL", result["matrixStatus"])
        self.assertEqual(8, result["caseCount"])
        self.assertEqual("FAIL", matrix["cases"][1]["status"])
        self.assertEqual("FAIL", matrix["cases"][1]["gates"]["identityAccuracy"])

    def test_pass_case_cannot_hide_a_failed_gate(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        matrix["cases"][0]["status"] = "PASS"
        matrix["cases"][0]["gates"]["identityAccuracy"] = "FAIL"
        matrix["cases"][0]["blockingReasons"] = []
        with self.assertRaisesRegex(MATRIX_MODULE.MatrixError, "cannot be PASS"):
            MATRIX_MODULE.validate(matrix, repo_root=ROOT)


def event(sequence: int, name: str, fields: dict | None = None, session: str = "session-1") -> dict:
    return {"sequence": sequence, "sessionId": session, "event": name, "fields": fields or {}}


class DiagnosticsAnalyzerTest(unittest.TestCase):
    def test_complete_pipeline_keeps_caller_separate_from_sdk_alignment(self):
        events = [
            event(1, "START_LISTENING"),
            event(2, "AUDIO_FIRST_FRAME", {"frames": 1, "audioBytesWritten": 640}),
            event(3, "DIARIZATION_ASR_ALIGNMENT", {"text": "你好"}),
            event(4, "DIARIZATION_COMMUNITY_WINDOW", {"segmentations": [1], "embeddings": [0.1]}),
            event(5, "DIARIZATION_COMMUNITY_SAMPLES", {"embeddingSelection": [0]}),
            event(6, "DIARIZATION_COMMUNITY_COMMIT", {"clusterToFrozenId": ["speaker-0"], "registryAfter": ["speaker-0"]}),
            event(7, "DIARIZATION_PUBLIC_RESULT", {"speakerCount": 1, "isSessionFinal": True}),
            event(8, "FINISH_REQUESTED"),
            event(9, "CALLBACK_RESULT", {"isFinal": True, "isLast": True}),
            event(10, "CALLBACK_COMPLETE"),
            event(11, "DIARIZATION_QUEUE", {"pendingJobs": 0, "nativeCallsInFlight": 0, "audioDelayMs": 30}),
            event(12, "DIARIZATION_QUEUE", {"pendingJobs": 0, "nativeCallsInFlight": 1, "audioDelayMs": 25}),
            event(13, "DIARIZATION_QUEUE", {"pendingJobs": 0, "nativeCallsInFlight": 0, "audioDelayMs": 20}),
        ]
        result = ANALYZER.summarize(events, caller={"text": "你好", "speakerTurns": [{"speakerIndex": 0}]})
        self.assertIsNone(result["firstDivergenceStage"])
        self.assertEqual("INCONCLUSIVE", result["overallStatus"])
        self.assertEqual("INCONCLUSIVE", result["stages"]["sdk_alignment"]["status"])
        self.assertEqual("INCONCLUSIVE", result["stages"]["caller_display"]["status"])
        self.assertEqual("INCONCLUSIVE", result["queue"]["status"])
        self.assertEqual("PASS", result["lifecycle"]["status"])

    def test_partial_capture_does_not_invent_clustering_failure(self):
        events = [
            event(1, "START_LISTENING"),
            event(2, "AUDIO_FIRST_FRAME", {"frames": 1}),
            event(3, "DIARIZATION_ASR_PROCESSED", {"audioEndSample": 32000}),
            event(4, "DIARIZATION_COMMUNITY_WINDOW", {"segmentations": [1]}),
            event(5, "DIARIZATION_COMMUNITY_SAMPLES", {"embeddingSelection": [0]}),
        ]
        result = ANALYZER.summarize(events)
        self.assertIsNone(result["firstDivergenceStage"])
        self.assertEqual("UNVERIFIED", result["stages"]["clustering"]["status"])
        self.assertEqual("UNVERIFIED", result["stages"]["caller_display"]["status"])

    def test_queue_growth_and_last_before_finish_are_failures(self):
        events = [
            event(1, "START_LISTENING"),
            event(2, "AUDIO_FIRST_FRAME", {"frames": 1}),
            event(3, "CALLBACK_RESULT", {"isLast": True}),
            event(4, "FINISH_REQUESTED"),
            event(5, "DIARIZATION_QUEUE", {"pendingJobs": 1, "nativeCallsInFlight": 1}),
            event(6, "DIARIZATION_QUEUE", {"pendingJobs": 3, "nativeCallsInFlight": 1}),
            event(7, "DIARIZATION_QUEUE", {"pendingJobs": 4, "nativeCallsInFlight": 1}),
            event(8, "CALLBACK_COMPLETE"),
        ]
        result = ANALYZER.summarize(events)
        self.assertEqual("FAIL", result["queue"]["status"])
        self.assertEqual("FAIL", result["lifecycle"]["status"])
        self.assertTrue(result["lifecycle"]["isLastBeforeFinish"])

    def test_lifecycle_is_checked_per_session_before_aggregation(self):
        events = []
        sequence = 1
        for session in ("session-1", "session-2"):
            events.extend([
                event(sequence, "START_LISTENING", session=session),
                event(sequence + 1, "AUDIO_FIRST_FRAME", {"frames": 1}, session=session),
                event(sequence + 2, "FINISH_REQUESTED", session=session),
                event(sequence + 3, "CALLBACK_RESULT", {"isLast": True}, session=session),
                event(sequence + 4, "CALLBACK_COMPLETE", session=session),
            ])
            sequence += 5
        result = ANALYZER.summarize(events)
        self.assertEqual("PASS", result["lifecycle"]["status"])
        self.assertEqual(2, result["lifecycle"]["sessionCount"])
        self.assertEqual({"session-1", "session-2"}, set(result["sessions"]))

    def test_evaluation_reports_missing_speaker_and_identity_switch(self):
        result = ANALYZER._identity({
            "metrics": {"weightedStrictDer": 0.3},
            "results": {
                "clip": {
                    "speakerCountError": -1,
                    "minoritySpeakerRecall": 0,
                    "identityStability": {"sameSpeakerIdSwitchCount": 1},
                }
            },
        })
        self.assertEqual("FAIL", result["status"])
        self.assertEqual(3, len(result["failures"]))

        count_result = ANALYZER._identity(
            None, observed_speaker_counts=[1], expected_speaker_count=4
        )
        self.assertEqual("FAIL", count_result["status"])
        self.assertIn("speakerCount=1", count_result["failures"][0])

        events = [
            event(1, "START_LISTENING"),
            event(2, "AUDIO_FIRST_FRAME", {"frames": 1}),
            event(3, "DIARIZATION_ASR_PROCESSED", {"audioEndSample": 32000}),
            event(4, "DIARIZATION_COMMUNITY_WINDOW", {"segmentations": [1], "embeddings": [0.1]}),
            event(5, "DIARIZATION_COMMUNITY_SAMPLES", {"embeddingSelection": [0]}),
            event(6, "DIARIZATION_COMMUNITY_COMMIT", {"clusterToFrozenId": ["speaker-0"]}),
            event(7, "DIARIZATION_PUBLIC_RESULT", {"speakerCount": 1, "isSessionFinal": True}),
        ]
        summary = ANALYZER.summarize(events, evaluation={
            "results": {"clip": {"speakerCountError": -1, "minoritySpeakerRecall": 0}}
        })
        self.assertEqual("identity_accuracy", summary["firstObservedFailure"])
        self.assertEqual("FAIL", summary["overallStatus"])

    def test_load_events_rejects_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.ndjson"
            path.write_text('{"event":"START_LISTENING"}\nnot-json\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                ANALYZER.load_events(path)

    def test_complete_before_last_and_late_nonlast_final_after_cancel_fail(self):
        for events in ([event(1, "FINISH_REQUESTED"), event(2, "CALLBACK_COMPLETE"),
                        event(3, "CALLBACK_RESULT", {"isLast": True})],
                       [event(1, "CANCEL_REQUESTED"),
                        event(2, "CALLBACK_RESULT", {"isFinal": True, "isLast": False})],
                       [event(1, "CALLBACK_RESULT", {"isLast": True}), event(2, "CALLBACK_COMPLETE")]):
            self.assertEqual("FAIL", ANALYZER.summarize(events)["lifecycle"]["status"])

    def test_cancel_preserves_earlier_endpoint(self):
        result = ANALYZER.summarize([event(1, "CALLBACK_RESULT", {"isFinal": True}),
                                     event(2, "CANCEL_REQUESTED")])
        self.assertEqual("PASS", result["lifecycle"]["status"])


if __name__ == "__main__":
    unittest.main()
