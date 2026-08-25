import importlib.util
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
SERVICE_PATH = (
    ROOT
    / "delivery/harmony-dingqiao/delivery/run_speaker_diarization_service.py"
)
EVALUATOR_PATH = (
    ROOT
    / "delivery/harmony-dingqiao/delivery/evaluate_speaker_diarization_report.py"
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load speaker diarization service")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_service():
    return load_module("speaker_diarization_service", SERVICE_PATH)


class HarmonySpeakerDiarizationEvaluatorTest(unittest.TestCase):
    def test_frame_metrics_score_overlap_and_global_speaker_mapping(self) -> None:
        evaluator = load_module("speaker_diarization_evaluator", EVALUATOR_PATH)
        turns = [
            {"beginTime": 0, "endTime": 1000, "speakerIndex": 1,
             "secondarySpeakerIndexes": [], "overlap": False},
            {"beginTime": 1000, "endTime": 2000, "speakerIndex": 1,
             "secondarySpeakerIndexes": [0], "overlap": True},
            {"beginTime": 2000, "endTime": 3000, "speakerIndex": 0,
             "secondarySpeakerIndexes": [], "overlap": False},
        ]
        reference = [(0.0, 2.0, "A"), (1.0, 3.0, "B")]
        result = evaluator.evaluate(turns, reference, 4.0)
        self.assertEqual(result["speakerMapping"], {"0": "B", "1": "A"})
        self.assertEqual(result["speakerCountError"], 0)
        self.assertEqual(result["der"], 0.0)
        self.assertEqual(result["overlapDetectionRecall"], 1.0)
        self.assertEqual(result["identifiedSecondaryRecall"], 1.0)


@unittest.skipUnless(importlib.util.find_spec("sherpa_onnx"), "sherpa_onnx is not installed")
class HarmonySpeakerDiarizationServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = load_service()

    def test_overlap_segments_preserve_primary_and_secondary_mask(self) -> None:
        raw = [
            SimpleNamespace(start=0.0, end=2.0, speaker=7),
            SimpleNamespace(start=1.0, end=3.0, speaker=12),
        ]
        segments = self.service._to_overlap_aware_segments(raw)
        self.assertEqual(
            [(item.start_sample, item.end_sample, item.speaker, item.speaker_mask)
             for item in segments],
            [
                (0, 16000, 0, 1),
                (16000, 32000, 0, 3),
                (32000, 48000, 1, 2),
            ],
        )

    def test_http_protocol_echoes_window_metadata_and_pcm_body(self) -> None:
        captured = {}

        class FakeModels:
            def process(self, pcm16, metadata):
                captured["pcm16"] = pcm16
                captured["metadata"] = metadata
                return {
                    "protocolVersion": 1,
                    "jobId": metadata.job_id,
                    "windowStartSample": metadata.window_start_sample,
                    "contentStartInWindowSample": metadata.content_start_sample,
                    "realEndSample": metadata.real_end_sample,
                    "commitStartSample": metadata.commit_start_sample,
                    "stableEndSample": metadata.stable_end_sample,
                    "finalWindow": metadata.final_window,
                    "result": {"segments": [], "embeddings": [], "inferenceMs": 1},
                }

        server = self.service.DiarizationHttpServer(("127.0.0.1", 0), FakeModels(), "token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = b"\x01\x00\x02\x00"
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}{self.service.WINDOW_PATH}",
                data=body,
                method="POST",
                headers={
                    "Authorization": "Bearer token",
                    "Content-Type": "application/octet-stream",
                    "X-Amphion-Protocol-Version": "1",
                    "X-Amphion-Job-Id": "w00000001",
                    "X-Amphion-Sample-Rate": "16000",
                    "X-Amphion-Sample-Count": "2",
                    "X-Amphion-Window-Start-Sample": "0",
                    "X-Amphion-Content-Start-Sample": "159998",
                    "X-Amphion-Real-End-Sample": "2",
                    "X-Amphion-Commit-Start-Sample": "0",
                    "X-Amphion-Stable-End-Sample": "2",
                    "X-Amphion-Final-Window": "true",
                },
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = json.load(response)
            self.assertEqual(payload["jobId"], "w00000001")
            self.assertTrue(payload["finalWindow"])
            self.assertEqual(captured["pcm16"], body)
            self.assertEqual(captured["metadata"].content_start_sample, 159998)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_protocol_rejects_missing_bearer_token_before_inference(self) -> None:
        class FailIfCalledModels:
            def process(self, _pcm16, _metadata):
                self.fail("unauthorized request reached inference")

        models = FailIfCalledModels()
        models.fail = self.fail
        server = self.service.DiarizationHttpServer(("127.0.0.1", 0), models, "secret")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}{self.service.WINDOW_PATH}",
                data=b"\x00\x00",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
