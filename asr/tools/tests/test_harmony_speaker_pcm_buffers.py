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

    def test_fallback_speech_samples_cut_at_the_vad_speech_end(self) -> None:
        """final 分数只用到语音结束为止的 PCM，vadEnd 尾部静音不进评分窗口。"""
        self.run_buffers(
            """
            const buffers = new SpeakerPcmBuffers(1000);
            const speech = new Float32Array(300).fill(0.5);
            const silence = new Float32Array(200);
            buffers.observe(speech, true, true);
            buffers.observe(silence, true, true);

            const bounded = buffers.fallbackSpeechSamples(200);
            assert.equal(bounded.length, 300);
            assert.ok(bounded.every((v) => v === 0.5));
            assert.equal(buffers.fallbackSamples().length, 500);

            // trailing=0 等价于整段；trailing 超过观测总数时为空，由调用方决定退回整段。
            assert.equal(buffers.fallbackSpeechSamples(0).length, 500);
            assert.equal(buffers.fallbackSpeechSamples(600).length, 0);
            """
        )

    def test_fallback_speech_samples_are_chunking_invariant(self) -> None:
        """同一 PCM 一次写入与多次小块写入必须得到逐样本相同的评分 PCM。"""
        self.run_buffers(
            """
            const pcm = Float32Array.from({ length: 1200 }, (_, i) => Math.sin(i / 7));
            const whole = new SpeakerPcmBuffers(10_000);
            whole.observe(pcm, true, true);

            const chunked = new SpeakerPcmBuffers(10_000);
            for (let offset = 0; offset < pcm.length; offset += 37) {
              chunked.observe(pcm.subarray(offset, Math.min(pcm.length, offset + 37)), true, true);
            }
            for (const trailing of [0, 1, 36, 37, 38, 500, 1199]) {
              const a = whole.fallbackSpeechSamples(trailing);
              const b = chunked.fallbackSpeechSamples(trailing);
              assert.equal(a.length, 1200 - trailing);
              assert.deepEqual(Array.from(a), Array.from(b));
            }
            """
        )

    def test_fallback_speech_end_is_measured_against_uncapped_observation(self) -> None:
        """封顶后仍按真实观测总数定位语音结束，否则尾静音会被误算进评分 PCM。"""
        self.run_buffers(
            """
            const buffers = new SpeakerPcmBuffers(100);
            buffers.observe(new Float32Array(90).fill(1), true, true);
            buffers.observe(new Float32Array(60), true, true);  // 只保留 10 个，观测到 150
            // 语音结束在观测位置 90：150 - 60 = 90，正好在封顶之内。
            assert.equal(buffers.fallbackSpeechSamples(60).length, 90);
            // 语音结束在封顶之后（观测位置 120）时按封顶长度返回整段保留内容。
            assert.equal(buffers.fallbackSpeechSamples(30).length, 100);
            """
        )

    def test_public_utterance_clear_bumps_the_epoch(self) -> None:
        """投机算好的分数只能在同一代缓冲上消费：清空公开句必须换代，清 native 段不换。"""
        self.run_buffers(
            """
            const buffers = new SpeakerPcmBuffers(100);
            const epoch = buffers.fallbackEpoch();
            buffers.observe(new Float32Array(10), true, true);
            buffers.clearNativeSegment();
            assert.equal(buffers.fallbackEpoch(), epoch);
            buffers.clearPublicUtterance();
            assert.equal(buffers.fallbackEpoch(), epoch + 1);
            assert.equal(buffers.fallbackSpeechSamples(0).length, 0);
            buffers.clearAll();
            assert.equal(buffers.fallbackEpoch(), epoch + 2);
            """
        )


if __name__ == "__main__":
    unittest.main()
