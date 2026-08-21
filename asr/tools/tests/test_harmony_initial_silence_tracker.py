import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TRACKER = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/InitialSilenceTracker.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonyInitialSilenceTrackerTest(unittest.TestCase):
    def run_tracker(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ InitialSilenceTracker }} from {TRACKER.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                str(TS_LOADER),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_text_evidence_permanently_disarms_timeout(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(500, 16000);
            assert.equal(tracker.observeVad(6400, false), false);
            tracker.observeAsrResult('hello', 0);
            assert.equal(tracker.observeVad(16000, false), false);
            assert.equal(tracker.hasTimedOut(), false);
            """
        )

    def test_token_only_evidence_permanently_disarms_timeout(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(500, 16000);
            assert.equal(tracker.observeVad(6400, false), false);
            tracker.observeAsrResult('', 1);
            assert.equal(tracker.observeVad(16000, false), false);
            assert.equal(tracker.hasTimedOut(), false);
            """
        )

    def test_sustained_activity_grants_one_bounded_confirmation_window(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(500, 16000, 1500);
            const signal = new Float32Array(320).fill(0.02);
            tracker.observeAcousticSamples(signal);
            tracker.observeAcousticSamples(signal);
            tracker.observeAcousticSamples(signal);
            assert.equal(tracker.observeVad(8000, false), false);
            assert.equal(tracker.needsAsrProbe(), true);
            assert.equal(tracker.observeVad(23999, false), false);
            assert.equal(tracker.observeVad(1, false), true);
            tracker.observeAsrResult('speech', 1);
            assert.equal(tracker.confirmTimeout(), false);
            assert.equal(tracker.hasTimedOut(), false);
            """
        )

    def test_activity_is_chunk_invariant_and_never_permanently_disarms_timeout(self) -> None:
        self.run_tracker(
            """
            const merged = new InitialSilenceTracker(500, 16000, 1500);
            const framed = new InitialSilenceTracker(500, 16000, 1500);
            const signal = new Float32Array(960).fill(0.02);
            merged.observeAcousticSamples(signal);
            framed.observeAcousticSamples(signal.slice(0, 137));
            framed.observeAcousticSamples(signal.slice(137, 593));
            framed.observeAcousticSamples(signal.slice(593));
            assert.equal(merged.observeVad(8000, false), false);
            assert.equal(framed.observeVad(8000, false), false);
            assert.equal(merged.observeVad(24000, false), true);
            assert.equal(framed.observeVad(24000, false), true);
            assert.equal(merged.confirmTimeout(), true);
            assert.equal(framed.confirmTimeout(), true);
            assert.equal(merged.hasTimedOut(), true);
            assert.equal(framed.hasTimedOut(), true);
            """
        )

    def test_fixed_decision_slices_do_not_look_ahead_past_timeout(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(1000, 16000, 1500);
            const input = new Float32Array(16960);
            input.fill(0.02, 16000);
            let timedOut = false;
            for (let offset = 0; offset < input.length && tracker.isArmed(); offset += 320) {
              const chunk = input.slice(offset, Math.min(input.length, offset + 320));
              tracker.observeAcousticSamples(chunk);
              if (tracker.observeVad(chunk.length, false)) {
                timedOut = tracker.confirmTimeout();
                break;
              }
            }
            assert.equal(timedOut, true);
            assert.equal(tracker.hasTimedOut(), true);
            """
        )

    def test_runtime_320_sample_chunks_timeout_before_512_sample_vad_carry_can_look_ahead(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(1000, 16000);
            const state = { carry: 0, vadSamples: 0 };
            const feedRuntimeFrame = (speechDetected) => {
              tracker.observeAcousticSamples(new Float32Array(320));
              const merged = state.carry + 320;
              const processed = Math.floor(merged / 512) * 512;
              state.carry = merged - processed;
              state.vadSamples += processed;
              return tracker.observeVad(processed, speechDetected);
            };

            let reachedDeadline = false;
            for (let frame = 0; frame < 50; frame++) {
              reachedDeadline = feedRuntimeFrame(false);
              assert.equal(reachedDeadline, frame === 49);
            }
            assert.equal(state.vadSamples, 15872);
            assert.equal(state.carry, 128);
            assert.equal(tracker.confirmTimeout(), true);

            // Speech arriving after sample 16000 cannot use the unresolved carry to reverse the decision.
            assert.equal(feedRuntimeFrame(true), false);
            assert.equal(tracker.hasTimedOut(), true);
            """
        )

    def test_vad_window_ending_exactly_at_deadline_keeps_boundary_speech_priority(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(512, 16000);
            let carry = 0;
            let vadSamples = 0;
            const feedRuntimeFrame = (speechDetected) => {
              tracker.observeAcousticSamples(new Float32Array(320));
              const merged = carry + 320;
              const processed = Math.floor(merged / 512) * 512;
              carry = merged - processed;
              vadSamples += processed;
              return tracker.observeVad(processed, speechDetected);
            };

            for (let frame = 0; frame < 25; frame++) {
              assert.equal(feedRuntimeFrame(false), false);
            }
            // Frame 26 carries 128 samples after the deadline, but the completed VAD window itself
            // ends exactly at sample 8192. Its speech evidence must win at the boundary.
            assert.equal(feedRuntimeFrame(true), false);
            assert.equal(vadSamples, 8192);
            assert.equal(carry, 128);
            assert.equal(tracker.isArmed(), false);
            assert.equal(tracker.hasTimedOut(), false);
            """
        )

    def test_asr_evidence_after_deadline_cannot_reverse_pending_timeout(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(1000, 16000);
            tracker.observeAcousticSamples(new Float32Array(16000));
            assert.equal(tracker.observeVad(15872, false), true);
            tracker.observeAcousticSamples(new Float32Array(320));
            tracker.observeAsrResult('late', 1);
            assert.equal(tracker.confirmTimeout(), true);
            assert.equal(tracker.hasTimedOut(), true);
            """
        )

    def test_runtime_uses_the_chunk_and_vad_window_sizes_exercised_above(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("const INITIAL_DECISION_CHUNK_SAMPLES: number = ASR_SAMPLE_RATE_HZ / 50;", runtime)
        self.assertIn("this.vadWindowSize = 512;", runtime)
        self.assertLess(
            runtime.index("this.initialSilenceTracker.observeAcousticSamples(rawSamples)"),
            runtime.index("const initialSilenceTimedOut = this.initialSilenceTracker.observeVad(i, anySpeech)"),
        )

    def test_low_noise_and_interrupted_clicks_do_not_grant_grace(self) -> None:
        self.run_tracker(
            """
            const lowNoise = new InitialSilenceTracker(500, 16000, 1500);
            lowNoise.observeAcousticSamples(new Float32Array(3200).fill(0.005));
            assert.equal(lowNoise.observeVad(8000, false), true);

            const clicks = new InitialSilenceTracker(500, 16000, 1500);
            clicks.observeAcousticSamples(new Float32Array(640).fill(0.02));
            clicks.observeAcousticSamples(new Float32Array(320));
            clicks.observeAcousticSamples(new Float32Array(320).fill(0.02));
            assert.equal(clicks.observeVad(8000, false), true);
            """
        )

    def test_varying_speech_like_activity_is_distinguished_from_steady_tone(self) -> None:
        self.run_tracker(
            """
            const speech = new InitialSilenceTracker(500, 16000, 1500);
            const tone = new InitialSilenceTracker(500, 16000, 1500);
            for (const level of [0.02, 0.08, 0.03, 0.12]) {
              const speechFrame = new Float32Array(320);
              const toneFrame = new Float32Array(320);
              for (let i = 0; i < 320; i++) {
                speechFrame[i] = i % 20 < 10 ? level : -level;
                toneFrame[i] = i % 2 === 0 ? 0.02 : -0.02;
              }
              speech.observeAcousticSamples(speechFrame);
              tone.observeAcousticSamples(toneFrame);
            }
            assert.equal(speech.confirmSpeechLikeActivity(), true);
            assert.equal(tone.confirmSpeechLikeActivity(), false);
            assert.equal(speech.hasTimedOut(), false);
            """
        )

    def test_separated_varying_pulses_do_not_become_speech_like_activity(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(500, 16000, 1500);
            for (const level of [0.02, 0.08, 0.03]) {
              const pulse = new Float32Array(320);
              for (let i = 0; i < 320; i++) pulse[i] = i % 20 < 10 ? level : -level;
              tracker.observeAcousticSamples(pulse);
              tracker.observeAcousticSamples(new Float32Array(320));
            }
            assert.equal(tracker.observeVad(8000, false), true);
            assert.equal(tracker.confirmSpeechLikeActivity(), false);
            assert.equal(tracker.confirmTimeout(), true);
            """
        )

    def test_one_new_pulse_does_not_refresh_old_speech_like_activity(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(500, 16000, 1500);
            for (const level of [0.02, 0.08, 0.03, 0.12]) {
              const frame = new Float32Array(320);
              for (let i = 0; i < 320; i++) frame[i] = i % 20 < 10 ? level : -level;
              tracker.observeAcousticSamples(frame);
            }
            tracker.observeAcousticSamples(new Float32Array(16000));
            const pulse = new Float32Array(320);
            for (let i = 0; i < 320; i++) pulse[i] = i % 20 < 10 ? 0.08 : -0.08;
            tracker.observeAcousticSamples(pulse);
            assert.equal(tracker.confirmSpeechLikeActivity(), false);
            """
        )

    def test_old_variation_cannot_be_kept_recent_by_a_steady_tone(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(1000, 16000, 1500);
            for (const level of [0.02, 0.08, 0.03, 0.12]) {
              const frame = new Float32Array(320);
              for (let i = 0; i < frame.length; i++) {
                frame[i] = i % 20 < 10 ? level : -level;
              }
              tracker.observeAcousticSamples(frame);
            }

            const steadyTone = new Float32Array(320);
            for (let i = 0; i < steadyTone.length; i++) {
              steadyTone[i] = Math.sin(2 * Math.PI * 100 * i / 16000) * 0.04;
            }
            for (let frame = 4; frame < 50; frame++) {
              tracker.observeAcousticSamples(steadyTone);
            }
            assert.equal(tracker.observeVad(16000, false), false);
            assert.equal(tracker.needsAsrProbe(), true);

            for (let frame = 0; frame < 75; frame++) {
              tracker.observeAcousticSamples(steadyTone);
            }
            assert.equal(tracker.observeVad(24000, false), true);
            assert.equal(tracker.confirmSpeechLikeActivity(), false);
            assert.equal(tracker.confirmTimeout(), true);
            assert.equal(tracker.hasTimedOut(), true);
            """
        )

    def test_early_short_speech_still_gets_confirmation_after_recent_window_expires(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(1000, 16000, 1500);
            for (const level of [0.02, 0.08, 0.03, 0.12]) {
              const frame = new Float32Array(320);
              for (let i = 0; i < 320; i++) frame[i] = i % 20 < 10 ? level : -level;
              tracker.observeAcousticSamples(frame);
            }
            tracker.observeAcousticSamples(new Float32Array(14720));
            assert.equal(tracker.observeVad(16000, false), false);
            assert.equal(tracker.needsAsrProbe(), true);
            assert.equal(tracker.observeVad(24000, false), true);
            assert.equal(tracker.confirmSpeechLikeActivity(), false);
            tracker.observeAsrResult('speech', 1);
            assert.equal(tracker.confirmTimeout(), false);
            """
        )

    def test_silence_times_out_once_and_speech_wins_at_boundary(self) -> None:
        self.run_tracker(
            """
            const silence = new InitialSilenceTracker(500, 16000);
            assert.equal(silence.observeVad(8000, false), true);
            assert.equal(silence.confirmTimeout(), true);
            assert.equal(silence.shouldDiscardAsrResult(), true);
            silence.observeAsrResult('late decoder hallucination', 1);
            assert.equal(silence.shouldDiscardAsrResult(), true);
            assert.equal(silence['speechDetected'], false);
            assert.equal(silence.observeVad(8000, false), false);
            assert.equal(silence.confirmTimeout(), false);

            const boundarySpeech = new InitialSilenceTracker(500, 16000);
            assert.equal(boundarySpeech.observeVad(8000, true), false);
            assert.equal(boundarySpeech.hasTimedOut(), false);
            assert.equal(boundarySpeech.shouldDiscardAsrResult(), false);
            """
        )


if __name__ == "__main__":
    unittest.main()
