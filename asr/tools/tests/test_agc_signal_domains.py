import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID = ROOT / "asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt"
HARMONY = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
HARMONY_BACKEND = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeAgcBackend.ets"


class AgcSignalDomainsTest(unittest.TestCase):
    def test_android_limits_processed_pcm_to_asr(self) -> None:
        source = ANDROID.read_text(encoding="utf-8")

        self.assertIn("stream.acceptWaveform(processedSamples, sampleRate)", source)
        self.assertIn(
            "val merged = if (vadCarry.isEmpty()) rawSamples else vadCarry + rawSamples",
            source,
        )
        self.assertNotIn(
            "val merged = if (vadCarry.isEmpty()) processedSamples",
            source,
        )

    def test_harmony_limits_processed_pcm_to_asr_in_sync_and_async_lanes(self) -> None:
        source = HARMONY.read_text(encoding="utf-8")

        self.assertEqual(1, source.count("this.feedRecognizer(processedSamples, false)"))
        self.assertEqual(1, source.count("await this.feedRecognizerAsync(processedSamples, false)"))
        self.assertEqual(
            2,
            source.count("this.vadCarry.length === 0 ? rawSamples"),
        )
        self.assertNotIn("this.vadCarry.length === 0 ? processedSamples", source)

    def test_harmony_native_agc_clones_before_in_place_processing(self) -> None:
        source = HARMONY_BACKEND.read_text(encoding="utf-8")

        self.assertIn("const output = frame.slice();", source)
        self.assertIn("return processAgc(this.handle, output);", source)


if __name__ == "__main__":
    unittest.main()
