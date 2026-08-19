import pathlib
import unittest


RUNTIME = (
    pathlib.Path(__file__).resolve().parents[2]
    / "harmony"
    / "sdk"
    / "src"
    / "main"
    / "ets"
    / "com"
    / "amphion"
    / "asr"
    / "Runtime.ets"
)


class HarmonyMaxSegmentOverlapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNTIME.read_text(encoding="utf-8")

    def test_overlap_is_two_320_ms_model_chunks(self) -> None:
        self.assertIn(
            "SEGMENT_OVERLAP_SAMPLES: number = Math.round(0.64 * ASR_SAMPLE_RATE_HZ)",
            self.source,
        )

    def test_sync_and_async_paths_retain_overlap(self) -> None:
        self.assertEqual(self.source.count("this.rememberSegmentOverlap(samples);"), 2)

    def test_all_three_public_rotation_paths_use_overlap(self) -> None:
        self.assertGreaterEqual(self.source.count("const overlap = this.segmentOverlap.slice();"), 3)
        self.assertGreaterEqual(self.source.count("this.rotateStreamWithOverlap(overlap);"), 3)

    def test_rotation_primes_new_stream_without_recounting_pcm(self) -> None:
        method = self.source.split("private rotateStreamWithOverlap(overlap: Float32Array): void {", 1)[1]
        method = method.split("private observeAcceptedPcm", 1)[0]
        self.assertLess(method.index("this.finishUtterance(true);"), method.index("this.stream.acceptWaveform(wave);"))
        priming = method.split("this.resetVadGateState();", 1)[1]
        self.assertNotIn("pcmBytesAccepted", priming)
        self.assertNotIn("vadActiveSegmentSamples +=", priming)

    def test_replayed_pcm_is_voiceprint_evidence_for_the_next_public_final(self) -> None:
        method = self.source.split("private rotateStreamWithOverlap(overlap: Float32Array): void {", 1)[1]
        method = method.split("private observeAcceptedPcm", 1)[0]
        self.assertIn(
            "this.speakerPcmBuffers.observe(overlap, this.speakerVadEnabled, this.targetSpeakerEnabled);",
            method,
        )
        self.assertLess(
            method.index("this.speakerPcmBuffers.observe(overlap"),
            method.index("this.stream.acceptWaveform(wave);"),
        )
        self.assertNotIn("effectiveSpeechBuffer.observe(overlap)", method)

    def test_sync_and_async_external_pcm_share_accounting(self) -> None:
        self.assertEqual(self.source.count("this.observeAcceptedPcm(rawSamples,"), 2)
        accounting = self.source.split(
            "private observeAcceptedPcm(rawSamples: Float32Array, replay: boolean): void {", 1
        )[1].split("private flushEndpointTail", 1)[0]
        self.assertIn("if (!replay)", accounting)
        self.assertIn("this.pcmBytesAccepted += rawSamples.length * 2;", accounting)


if __name__ == "__main__":
    unittest.main()
