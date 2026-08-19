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

    def test_overlap_is_320_ms(self) -> None:
        self.assertIn(
            "MAX_SEGMENT_OVERLAP_SAMPLES: number = Math.round(0.32 * ASR_SAMPLE_RATE_HZ)",
            self.source,
        )

    def test_sync_and_async_paths_retain_overlap(self) -> None:
        self.assertEqual(self.source.count("this.rememberMaxSegmentOverlap(samples);"), 2)

    def test_forced_rotation_primes_new_stream_without_recounting_pcm(self) -> None:
        method = self.source.split("private triggerMaxSegmentEndpoint(): void {", 1)[1]
        method = method.split("private flushEndpointTail(): number {", 1)[0]
        self.assertLess(method.index("const overlap = this.maxSegmentOverlap.slice();"), method.index("this.finishUtterance(true);"))
        self.assertLess(method.index("this.resetVadGateState();"), method.index("this.stream.acceptWaveform(wave);"))
        priming = method.split("this.resetVadGateState();", 1)[1]
        self.assertNotIn("pcmBytesAccepted", priming)
        self.assertNotIn("vadActiveSegmentSamples +=", priming)


if __name__ == "__main__":
    unittest.main()
