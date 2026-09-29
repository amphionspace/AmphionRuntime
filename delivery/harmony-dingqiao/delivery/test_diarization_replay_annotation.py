import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from annotate_qwen_audio import normalize
from replay_diarization_snapshot import snapshot
from audit_diarization_embeddings import audit


class ReplayAnnotationTest(unittest.TestCase):
    def test_word_speaker_switch_and_unknown_are_preserved(self):
        result = normalize({"output": {"sentences": [{"speaker_id": 9, "words": [
            {"begin_time": 0, "end_time": 500, "speaker_id": 0, "text": "你好"},
            {"begin_time": 500, "end_time": 800, "speaker_id": 1, "text": "嗯"},
            {"begin_time": 800, "end_time": 1000, "speaker_id": None, "text": "好"},
        ]}]}}, 1000)
        self.assertEqual([0, 1, None], [s["speakerIndex"] for s in result["segments"]])
        self.assertEqual("auxiliary-not-human-truth", result["annotationStatus"])
        self.assertEqual("你好嗯好", "".join(s["text"] for s in result["segments"]))

    def test_invalid_or_truncated_annotations_are_not_silently_accepted(self):
        result = normalize({"output": {"sentences": [
            {"begin_time": 0, "end_time": 2000, "speaker_id": 0, "text": "bad"}]}}, 1000)
        self.assertEqual("INCONCLUSIVE", result["status"])
        self.assertEqual([], result["segments"])
        with self.assertRaisesRegex(ValueError, "no sentences"):
            normalize({"output": {"text": "without speaker log"}}, 1000)

    def test_snapshot_requires_actual_run_vectors_and_preserves_window_coordinates(self):
        w = {"jobId": "w2", "windowStartSample": 32000, "segmentations": [0]*1767,
             "embeddings": [0]*768, "runRanges": [0, 0, 10, 130]}
        events = [{"sessionId": "s", "_sequence": 1, "event": "DIARIZATION_COMMUNITY_WINDOW", "fields": w},
                  {"sessionId": "s", "_sequence": 2, "event": "DIARIZATION_COMMUNITY_COMMIT", "fields": {
                      "jobIds": ["w2"], "windowStartSamples": [32000], "beginTime": 2000}}]
        with self.assertRaisesRegex(ValueError, "runEmbeddings missing"):
            snapshot(events, "s", 2)
        w["runEmbeddings"] = [None]+[0]*255
        data, _ = snapshot(events, "s", 2)
        magic, windows, runs, cap, begin, start = struct.unpack('<IIIIdd', data[:32])
        self.assertEqual((0x43525031, 1, 1, 4, 32000, 32000), (magic, windows, runs, cap, begin, start))
        events[-1]["fields"]["windowStartSamples"] = [0]
        with self.assertRaisesRegex(ValueError, "window order"):
            snapshot(events, "s", 2)

    def test_missing_prefix_is_not_a_valid_clustering_snapshot(self):
        events = [{"sessionId": "s", "_sequence": 2, "event": "DIARIZATION_COMMUNITY_COMMIT",
                   "fields": {"jobIds": ["expired-window"], "windowStartSamples": [0], "beginTime": 0}}]
        with self.assertRaisesRegex(ValueError, "missing prefix"):
            snapshot(events, "s", 2)

    def test_same_pcm_in_overlapping_windows_is_not_independent_identity_evidence(self):
        events = []
        for index, start in enumerate([0, 100]):
            events.append({"sessionId": "s", "_sequence": index+1,
                "event": "DIARIZATION_COMMUNITY_WINDOW", "fields": {
                    "jobId": str(index), "windowStartSample": start, "realEndSample": 160000,
                    "segmentations": [1, 0, 0]*589, "embeddings": [0]*768,
                    "runRanges": [0, 0, 0, 120], "runEmbeddings": [1]+[0]*255}})
        events.append({"sessionId": "s", "_sequence": 3, "event": "DIARIZATION_COMMUNITY_COMMIT",
                       "fields": {"jobIds": ["0", "1"], "windowStartSamples": [0, 100], "beginTime": 0}})
        result = audit(events, [(0, 10, "A")], "s")
        self.assertEqual(2, result["perReference"]["A"]["pairEligibleRuns"])
        self.assertEqual(0, result["sameSpeakerCosine"]["count"])
        self.assertEqual([], result["nearestIndependentRunMargins"])


if __name__ == '__main__':
    unittest.main()
