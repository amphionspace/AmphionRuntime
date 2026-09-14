"""Guard the two callback seams behind Dingqiao SPEECH_END."""

from pathlib import Path
import unittest


SOURCE = (
    Path(__file__).resolve().parents[2]
    / "android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt"
).read_text(encoding="utf-8")


class AndroidVadEndEventWiringTest(unittest.TestCase):
    def test_active_vad_endpoint_announces_before_flushing_final(self) -> None:
        body = SOURCE.split("private fun triggerVadActiveEndpoint()", 1)[1].split(
            "private fun triggerSpeakerVadEndpoint()", 1
        )[0]
        self.assertIn("postEndpoint()", body)
        self.assertLess(body.index("postEndpoint()"), body.index("stream.inputFinished()"))
        self.assertIn("postEndpointOnEndpoint = false", body)

    def test_asr_evidence_can_announce_speech_when_vad_misses_onset(self) -> None:
        body = SOURCE.split("private fun drainDecoder(", 1)[1].split(
            "private fun markInitialSpeechDetected", 1
        )[0]
        self.assertIn("announceAsrSpeechIfNeeded(r)", body)

    def test_vad_end_clock_uses_consumed_vad_samples_not_caller_chunk(self) -> None:
        body = SOURCE.split("private fun feedChunkAndDecode(", 1)[1].split(
            "private fun probeInitialSpeechAtTimeout", 1
        )[0]
        self.assertIn("trailingSilenceClock.observeSilence(i)", body)
        self.assertNotIn("trailingSilenceMs += (processedSamples.size", body)

if __name__ == "__main__":
    unittest.main()
