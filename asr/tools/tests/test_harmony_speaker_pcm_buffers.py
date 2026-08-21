import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BUFFERS = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerPcmBuffers.ts"
)
SELECTION = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerScoreFallback.ts"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonySpeakerPcmBuffersTest(unittest.TestCase):
    def run_buffers(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerPcmBuffers }} from {BUFFERS.as_uri()!r};
            import {{ selectSpeakerScoreSamples }} from {SELECTION.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                TS_LOADER.as_uri(),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_suppressed_native_endpoint_preserves_public_fallback_pcm(self) -> None:
        self.run_buffers(
            """
            const sampleRate = 16_000;
            const buffers = new SpeakerPcmBuffers(25 * sampleRate);
            buffers.observe(new Float32Array(0.8 * sampleRate), true, true);

            buffers.clearNativeSegment();
            assert.equal(buffers.speakerVadLength(), 0);
            assert.equal(buffers.fallbackSamples().length, 0.8 * sampleRate);

            buffers.observe(new Float32Array(0.8 * sampleRate), true, true);
            assert.equal(buffers.speakerVadLength(), 0.8 * sampleRate);
            assert.equal(buffers.fallbackSamples().length, 1.6 * sampleRate);
            """
        )

    def test_two_short_native_segments_form_one_scored_public_utterance(self) -> None:
        self.run_buffers(
            """
            const sampleRate = 16_000;
            const buffers = new SpeakerPcmBuffers(25 * sampleRate);
            buffers.observe(new Float32Array(0.8 * sampleRate), true, true);

            // A token-only native endpoint is suppressed: Speaker VAD starts a new stream,
            // while the public voiceprint utterance remains open.
            buffers.clearNativeSegment();
            buffers.observe(new Float32Array(0.8 * sampleRate), true, true);

            const selected = selectSpeakerScoreSamples(
              new Float32Array(0.4 * sampleRate),
              buffers.fallbackSamples(),
              1.5 * sampleRate,
              true
            );
            assert.equal(selected.source, 'utterance');
            assert.equal(selected.samples.length, 1.6 * sampleRate);
            """
        )

    def test_public_final_and_close_clear_both_boundaries(self) -> None:
        self.run_buffers(
            """
            const buffers = new SpeakerPcmBuffers(100);
            buffers.observe(new Float32Array(80), true, true);
            buffers.clearAll();
            assert.equal(buffers.speakerVadLength(), 0);
            assert.equal(buffers.fallbackSamples().length, 0);
            """
        )

    def test_verification_and_speaker_vad_can_capture_independently(self) -> None:
        self.run_buffers(
            """
            const verificationOnly = new SpeakerPcmBuffers(100);
            verificationOnly.observe(new Float32Array(80), false, true);
            assert.equal(verificationOnly.speakerVadLength(), 0);
            assert.equal(verificationOnly.fallbackSamples().length, 80);

            const speakerVadOnly = new SpeakerPcmBuffers(100);
            speakerVadOnly.observe(new Float32Array(80), true, false);
            assert.equal(speakerVadOnly.speakerVadLength(), 80);
            assert.equal(speakerVadOnly.fallbackSamples().length, 0);
            """
        )

    def test_each_buffer_is_capped_independently(self) -> None:
        self.run_buffers(
            """
            const buffers = new SpeakerPcmBuffers(100);
            buffers.observe(new Float32Array(80), true, true);
            buffers.clearNativeSegment();
            buffers.observe(new Float32Array(80), true, true);
            assert.equal(buffers.speakerVadLength(), 80);
            assert.equal(buffers.fallbackSamples().length, 100);
            """
        )


if __name__ == "__main__":
    unittest.main()
