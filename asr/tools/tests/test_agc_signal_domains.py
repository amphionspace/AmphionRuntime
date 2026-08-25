import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID = ROOT / "asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt"
HARMONY = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
HARMONY_BACKEND = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeAgcBackend.ets"
HARMONY_BRIDGE = ROOT / "asr/harmony/sdk/src/main/cpp/agc_bridge.cpp"


class AgcSignalDomainsTest(unittest.TestCase):
    def test_android_limits_processed_pcm_to_asr(self) -> None:
        source = ANDROID.read_text(encoding="utf-8")

        self.assertIn('processAgc("agc.process") { agcIngress.accept(copy, ::feedAndDecode) }', source)
        self.assertIn('processAgc("agc.flush(stop)") { agcIngress.flush(::feedAndDecode) }', source)
        self.assertNotIn("agcProcessor.process", source)
        self.assertNotIn("agcProcessor.flush", source)
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

        self.assertEqual(1, source.count("this.agcIngress.accept(samples"))
        self.assertEqual(1, source.count("this.agcIngress.acceptAsync(samples"))
        self.assertEqual(1, source.count("this.agcIngress.flush((frame: ProcessedAudioFrame)"))
        self.assertEqual(1, source.count("this.agcIngress.flushAsync(async (frame: ProcessedAudioFrame)"))
        self.assertNotIn("this.agcProcessor.process", source)
        self.assertNotIn("this.agcProcessor.flush", source)
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

    def test_harmony_bridge_delegates_to_the_shared_native_agc(self) -> None:
        source = HARMONY_BRIDGE.read_text(encoding="utf-8")

        self.assertIn("amphion_agc_create(sample_rate)", source)
        self.assertIn("amphion_agc_process(holder->agc, samples, sample_count)", source)
        self.assertIn("amphion_agc_destroy(holder->agc)", source)


if __name__ == "__main__":
    unittest.main()
