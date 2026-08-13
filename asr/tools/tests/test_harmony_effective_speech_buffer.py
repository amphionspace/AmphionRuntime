import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BUFFER = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/EffectiveSpeechBuffer.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonyEffectiveSpeechBufferTest(unittest.TestCase):
    def run_buffer(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ EffectiveSpeechBuffer }} from {BUFFER.as_uri()!r};

            const sampleRate = 16000;
            const frameSamples = sampleRate / 50;
            const speech = (durationSamples, scale = 1) => {{
              const output = new Float32Array(durationSamples);
              const levels = [0.012 * scale, 0.040 * scale, 0.020 * scale, 0.055 * scale];
              for (let offset = 0; offset < durationSamples; offset += frameSamples) {{
                const level = levels[Math.floor(offset / frameSamples) % levels.length];
                for (let i = offset; i < Math.min(durationSamples, offset + frameSamples); i++) {{
                  output[i] = (i - offset) % 16 < 8 ? level : -level;
                }}
              }}
              return output;
            }};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_leading_silence_does_not_satisfy_minimum_speech_duration(self) -> None:
        self.run_buffer(
            """
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(new Float32Array(sampleRate));
            buffer.observe(speech(sampleRate / 2));
            const effective = buffer.take();
            assert.equal(effective.length, sampleRate / 2);
            assert.equal(effective.length >= 1.5 * sampleRate, false);
            """
        )

    def test_exactly_minimum_effective_speech_is_retained(self) -> None:
        self.run_buffer(
            """
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(speech(1.5 * sampleRate));
            assert.equal(buffer.take().length, 1.5 * sampleRate);
            """
        )

    def test_trailing_silence_does_not_satisfy_minimum_speech_duration(self) -> None:
        self.run_buffer(
            """
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(speech(0.75 * sampleRate));
            buffer.observe(new Float32Array(sampleRate));
            const effective = buffer.take();
            assert.equal(effective.length, 0.75 * sampleRate);
            assert.equal(effective.length >= 1.5 * sampleRate, false);

            const nearBoundary = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            nearBoundary.observe(speech(1.49 * sampleRate));
            nearBoundary.observe(new Float32Array(sampleRate));
            assert.equal(nearBoundary.take().length >= 1.5 * sampleRate, false);
            """
        )

    def test_effective_speech_selection_is_caller_chunk_invariant(self) -> None:
        self.run_buffer(
            """
            const input = new Float32Array(2.5 * sampleRate);
            input.set(speech(1.5 * sampleRate), sampleRate / 2);

            const merged = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            const framed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            merged.observe(input);
            for (let offset = 0; offset < input.length;) {
              const size = Math.min(input.length - offset, (offset % 997) + 1);
              framed.observe(input.slice(offset, offset + size));
              offset += size;
            }
            assert.deepEqual(framed.take(), merged.take());
            """
        )

    def test_low_level_boundary_is_deterministic(self) -> None:
        self.run_buffer(
            """
            const below = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            const usable = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            below.observe(speech(1.5 * sampleRate, 0.20));
            usable.observe(speech(1.5 * sampleRate, 1.00));
            assert.equal(below.take().length, 0);
            assert.equal(usable.take().length, 1.5 * sampleRate);
            """
        )

    def test_vad_or_asr_evidence_retains_scaled_low_volume_speech(self) -> None:
        self.run_buffer(
            """
            const noEvidence = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            noEvidence.observe(speech(1.5 * sampleRate, 0.05));
            assert.equal(noEvidence.take().length, 0);

            const vadConfirmed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            vadConfirmed.observe(speech(1.5 * sampleRate, 0.05));
            vadConfirmed.confirmSpeech();
            assert.equal(vadConfirmed.take().length, 1.5 * sampleRate);

            const asrConfirmed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            asrConfirmed.observe(speech(1.5 * sampleRate, 0.05));
            assert.equal(asrConfirmed.take(true).length, 1.5 * sampleRate);

            const belowMinimum = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            belowMinimum.observe(speech(1.49 * sampleRate, 0.05));
            belowMinimum.observe(new Float32Array(sampleRate));
            belowMinimum.confirmSpeech();
            assert.equal(belowMinimum.take().length >= 1.5 * sampleRate, false);
            """
        )

    def test_isolated_candidates_are_not_promoted_by_later_vad_evidence(self) -> None:
        self.run_buffer(
            """
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(speech(2 * frameSamples, 0.05));
            buffer.observe(new Float32Array(sampleRate / 2));
            buffer.confirmSpeech();
            assert.equal(buffer.take().length, 0);
            """
        )

    def test_vad_or_asr_evidence_retains_constant_envelope_candidates(self) -> None:
        self.run_buffer(
            """
            const constantEnvelope = (durationSamples, level) => {
              const output = new Float32Array(durationSamples);
              for (let i = 0; i < durationSamples; i++) {
                output[i] = i % 16 < 8 ? level : -level;
              }
              return output;
            };

            const noEvidence = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            noEvidence.observe(constantEnvelope(2 * sampleRate, 0.04));
            assert.equal(noEvidence.take().length, 0);

            const vadConfirmed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            vadConfirmed.observe(constantEnvelope(1.5 * sampleRate, 0.002));
            vadConfirmed.confirmSpeech();
            assert.equal(vadConfirmed.take().length, 1.5 * sampleRate);

            const asrConfirmed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            asrConfirmed.observe(constantEnvelope(1.5 * sampleRate, 0.002));
            assert.equal(asrConfirmed.take(true).length, 1.5 * sampleRate);

            const belowMinimum = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            belowMinimum.observe(constantEnvelope(1.49 * sampleRate, 0.002));
            belowMinimum.confirmSpeech();
            assert.equal(belowMinimum.take().length >= 1.5 * sampleRate, false);
            """
        )

    def test_external_evidence_does_not_authorize_a_disjoint_steady_tone(self) -> None:
        self.run_buffer(
            """
            const steadyTone = new Float32Array(sampleRate);
            for (let i = 0; i < steadyTone.length; i++) {
              steadyTone[i] = Math.sin(2 * Math.PI * 100 * i / sampleRate) * 0.04;
            }
            const separator = new Float32Array(sampleRate / 5);
            const shortSpeech = speech(sampleRate / 2);

            const vadConfirmed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            vadConfirmed.observe(steadyTone);
            vadConfirmed.observe(separator);
            vadConfirmed.observe(shortSpeech);
            vadConfirmed.confirmSpeech();
            assert.equal(vadConfirmed.take().length < 1.5 * sampleRate, true);

            const asrConfirmed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            asrConfirmed.observe(steadyTone);
            asrConfirmed.observe(separator);
            asrConfirmed.observe(shortSpeech);
            assert.equal(asrConfirmed.take(true).length < 1.5 * sampleRate, true);
            """
        )

    def test_external_evidence_does_not_collect_a_disjoint_mildly_varying_tone(self) -> None:
        self.run_buffer(
            """
            const varyingTone = new Float32Array(sampleRate);
            for (let i = 0; i < varyingTone.length; i++) {
              const window = Math.floor(i / frameSamples);
              const level = window % 2 === 0 ? 0.040 : 0.045;
              varyingTone[i] = Math.sin(2 * Math.PI * 100 * i / sampleRate) * level;
            }
            const shortSpeech = speech(sampleRate / 2);
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(varyingTone);
            buffer.observe(new Float32Array(sampleRate / 5));
            buffer.observe(shortSpeech);
            buffer.confirmSpeech();
            assert.equal(buffer.take().length, shortSpeech.length);
            """
        )

    def test_vad_evidence_for_a_future_run_expires_after_bounded_lag(self) -> None:
        self.run_buffer(
            """
            const constantEnvelope = new Float32Array(1.5 * sampleRate);
            for (let i = 0; i < constantEnvelope.length; i++) {
              constantEnvelope[i] = i % 16 < 8 ? 0.002 : -0.002;
            }

            const recent = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            recent.confirmSpeech();
            recent.observe(new Float32Array(frameSamples));
            recent.observe(constantEnvelope);
            assert.equal(recent.take().length, constantEnvelope.length);

            const expired = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            expired.confirmSpeech();
            expired.observe(new Float32Array(sampleRate));
            expired.observe(constantEnvelope);
            assert.equal(expired.take().length, 0);
            """
        )

    def test_external_evidence_selection_is_caller_chunk_invariant(self) -> None:
        self.run_buffer(
            """
            const input = new Float32Array(2 * sampleRate);
            for (let i = sampleRate / 4; i < 1.75 * sampleRate; i++) {
              input[i] = i % 16 < 8 ? 0.002 : -0.002;
            }

            const merged = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            merged.observe(input);
            merged.confirmSpeech();

            const framed = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            for (let offset = 0; offset < input.length;) {
              const size = Math.min(input.length - offset, (offset % 997) + 1);
              framed.observe(input.slice(offset, offset + size));
              offset += size;
            }
            framed.confirmSpeech();
            assert.deepEqual(framed.take(), merged.take());
            """
        )

    def test_empty_non_last_final_preserves_audio_for_the_next_public_result(self) -> None:
        self.run_buffer(
            """
            const constantEnvelope = (durationSamples) => {
              const output = new Float32Array(durationSamples);
              for (let i = 0; i < durationSamples; i++) {
                output[i] = i % 16 < 8 ? 0.002 : -0.002;
              }
              return output;
            };
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(constantEnvelope(1.5 * sampleRate));

            const tokenOnly = buffer.resolveFinal('', true, false);
            assert.equal(tokenOnly.publish, false);
            assert.equal(tokenOnly.samples.length, 0);

            buffer.observe(new Float32Array(frameSamples));
            buffer.observe(constantEnvelope(0.5 * sampleRate));
            const publicResult = buffer.resolveFinal('recognized', true, false);
            assert.equal(publicResult.publish, true);
            assert.equal(publicResult.samples.length, 2 * sampleRate);
            """
        )

    def test_empty_last_final_publishes_retained_speech_and_clears_audio(self) -> None:
        self.run_buffer(
            """
            const constantEnvelope = new Float32Array(2 * sampleRate);
            for (let i = 0; i < constantEnvelope.length; i++) {
              constantEnvelope[i] = i % 16 < 8 ? 0.002 : -0.002;
            }
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(constantEnvelope);

            const terminal = buffer.resolveFinal('', true, true);
            assert.equal(terminal.publish, true);
            assert.equal(terminal.samples.length, 2 * sampleRate);

            const afterTerminal = buffer.resolveFinal('late', true, false);
            assert.equal(afterTerminal.publish, true);
            assert.equal(afterTerminal.samples.length, 0);
            """
        )

    def test_empty_last_final_with_only_silence_has_no_scoring_samples(self) -> None:
        self.run_buffer(
            """
            const buffer = new EffectiveSpeechBuffer(sampleRate, 25 * sampleRate);
            buffer.observe(new Float32Array(2 * sampleRate));

            const terminal = buffer.resolveFinal('', false, true);
            assert.equal(terminal.publish, true);
            assert.equal(terminal.samples.length, 0);
            """
        )

    def test_runtime_falls_back_to_confirmed_utterance_pcm_for_scoring(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        # Voiceprint fallback must observe the original signal, not the AGC-normalized ASR domain.
        self.assertIn("this.effectiveSpeechBuffer.observe(rawSamples)", runtime)
        self.assertIn("this.effectiveSpeechBuffer.confirmSpeech()", runtime)
        self.assertIn("this.effectiveSpeechBuffer.resolveFinal(result.text, hasEvidence, isLast)", runtime)
        suppressed_final = """if (!boundary.publish) {
      if (this.speakerVadEnabled) this.speakerPcmBuffers.clearNativeSegment();
      return hasEvidence;
    }"""
        self.assertIn(suppressed_final, runtime)
        self.assertIn(
            "selectSpeakerScoreSamples(boundary.samples, utteranceSamples, minSpeakerSamples, hasEvidence)",
            runtime,
        )
        self.assertIn("scoreSelection.samples,", runtime)
        self.assertIn(
            "(scoreSelection.samples.length > 0 || this.pendingSpeakerFinals.length > 0)",
            runtime,
        )
        self.assertIn(
            "this.speakerPcmBuffers.observe(rawSamples, this.speakerVadEnabled, this.targetSpeakerEnabled)",
            runtime,
        )
        self.assertIn(
            "this.speakerPcmBuffers.fallbackSamples()",
            runtime,
        )
        self.assertIn("this.speakerPcmBuffers.clearAll();", runtime)
        self.assertNotIn("this.effectiveSpeechBuffer.take(hasEvidence)", runtime)
        self.assertNotIn("suppressEmpty", runtime)

        boundary = runtime.index(
            "const boundary = this.effectiveSpeechBuffer.resolveFinal(result.text, hasEvidence, isLast);"
        )
        publish_guard = runtime.index(suppressed_final, boundary)
        external_count = runtime.index("this.utteranceIndex += 1;", publish_guard)
        external_reset = runtime.index("this.pcmBytesAccepted = 0;", external_count)
        self.assertLess(boundary, publish_guard)
        self.assertLess(publish_guard, external_count)
        self.assertLess(external_count, external_reset)

        self.assertIn("private recognizerResetGeneration: number = 0;", runtime)
        self.assertIn("const resetGenerationBefore = this.recognizerResetGeneration;", runtime)
        self.assertIn(
            "if (this.recognizerResetGeneration !== resetGenerationBefore)", runtime
        )
        self.assertNotIn("const utteranceBefore = this.utteranceIndex;", runtime)

    def test_buffer_caps_audio_and_run_metadata_at_the_same_limit(self) -> None:
        self.run_buffer(
            """
            const limit = 5 * frameSamples;
            const buffer = new EffectiveSpeechBuffer(sampleRate, limit);
            buffer.observe(speech(10 * frameSamples));
            buffer.confirmSpeech();
            for (let i = 0; i < 100; i++) {
              buffer.observe(new Float32Array(frameSamples));
              buffer.observe(speech(3 * frameSamples));
            }
            assert.equal(buffer.take().length, limit);
            """
        )
        source = BUFFER.read_text(encoding="utf-8")
        self.assertIn("if (this.retainedSamples >= this.maxSamples) return;", source)


if __name__ == "__main__":
    unittest.main()
