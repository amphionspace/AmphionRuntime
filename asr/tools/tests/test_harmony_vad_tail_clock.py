"""Exercise the production VAD gate with a fixed detector timeline and PCM clock."""
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonyVadTailClockTest(unittest.TestCase):
    def run_gate(self, checks: str, synchronous: bool = False) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        start = "private feedChunkAndDecode(" if synchronous else "private async advanceVadGateAsync"
        end = "private async feedChunkAndDecodeAsync" if synchronous else "private async prepareVadEndpointSpeakerScoreAsync"
        method = start + source.split(start, 1)[1].split(end, 1)[0]
        if synchronous:
            method += """
              async advanceVadGateAsync(samples) {
                const before = this.events.length;
                this.feedChunkAndDecode(samples, samples);
                return { vadEndpoint: this.events.length > before };
              }
            """
        else:
            method = method.replace("private async advanceVadGateAsync", "private async advanceVadGateOnlyAsync", 1)
            method += """
              async advanceVadGateAsync(samples) {
                this.publicSamplesFed += samples.length;
                const result = await this.advanceVadGateOnlyAsync(samples);
                if (result.vadEndpoint) result.vadEndpoint = await this.confirmVadEndpointAsync();
                return result;
              }
            """
        script = f"""
            import assert from 'node:assert/strict';
            const ASR_SAMPLE_RATE_HZ = 16000;
            const Logger = {{ metric() {{}} }};
            const concatFloat32 = (parts) => Float32Array.from(parts.flatMap(p => Array.from(p)));
            class VadGateAdvance {{ vadEndpoint = false; initialSilenceTimedOut = false; }}
            class Gate {{
              vadCarry = new Float32Array(0);
              vadWindowSize = 512;
              vadProcessedSamples = 0;
              vadLastSpeechEndSample = -1;
              vadSpeechActive = true;
              trailingSilenceMs = 0;
              vadEndpointPending = false;
              vadEndpointRecheckSample = 0;
              recognizer = {{ getVadEndpointWaitSeconds: () => 0,
                getVadEndpointWaitSecondsAsync: async () => this.recognizer.getVadEndpointWaitSeconds() }};
              callbackGate = {{ invoke: fn => {{ fn(); return true; }}, isClosed: () => false }};
              initialSilenceTracker = {{ observeVad: () => false,
                observeAcousticSamples() {{}}, hasTimedOut: () => false }};
              effectiveSpeechBuffer = {{ confirmSpeech() {{}} }};
              speakerPcmBuffers = {{ observe() {{}} }};
              recognizerResetGeneration = 0;
              publicSamplesFed = 0;
              feedRecognizer() {{}}
              triggerVadActiveEndpoint() {{ this.callback.onEndpoint(); }}
              sessionConfig = {{ endpointSilenceMs: 800 }};
              config = {{ vadConfig: {{ activeEndpointSilenceMs: 800 }} }};
              reentryQueue = {{ consumeStopAtEndpoint: () => false }};
              events = [];
              callback = {{ onEndpoint: () => this.events.push('end'),
                onSpeechBegin: () => this.events.push('begin') }};
              vad = {{ acceptWaveform() {{}}, isDetected: () => false, isEmpty: () => true }};
              {method}
            }}
            {checks}
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "vad-tail.mts"
            harness.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run(["node", "--experimental-strip-types", str(harness)],
                           check=True, cwd=ROOT)

    def test_800ms_tail_uses_completed_vad_samples_for_every_pcm_frame_size(self):
        for synchronous in (False, True):
            with self.subTest(synchronous=synchronous):
                self.run_gate("""
            for (const frameSamples of [160, 320, 512, 1600]) {
              const gate = new Gate();
              let total = 0;
              while (total < 12800) {
                const size = Math.min(frameSamples, 12800 - total);
                total += size;
                const result = await gate.advanceVadGateAsync(new Float32Array(size));
                assert.equal(result.vadEndpoint, total === 12800,
                  `800ms silence: frame=${frameSamples}, sample=${total}, counted=${gate.trailingSilenceMs}ms`);
              }
              assert.deepEqual(gate.events, ['end']);
              await gate.advanceVadGateAsync(new Float32Array(1600));
              assert.deepEqual(gate.events, ['end'], 'continued silence must not duplicate the endpoint');
            }
                """, synchronous=synchronous)

    def test_partial_vad_window_does_not_count_unclassified_samples(self):
        self.run_gate("""
            const gate = new Gate();
            await gate.advanceVadGateAsync(new Float32Array(511));
            assert.equal(gate.trailingSilenceMs, 0);
            await gate.advanceVadGateAsync(new Float32Array(1));
            assert.equal(gate.trailingSilenceMs, 32);
        """)

    def test_native_silence_confirmation_is_included_in_vad_end(self):
        for synchronous in (False, True):
            with self.subTest(synchronous=synchronous):
                self.run_gate("""
            // Native segment timeline measured with the customer PCM and packaged Silero model.
            // The detector confirms silence 250ms after its actual segment end (40032).
            for (const frameSamples of [160, 320, 512]) {
              const gate = new Gate();
              gate.sessionConfig.endpointSilenceMs = 1600;
              let classified = 0;
              let segmentPending = false;
              gate.vad = {
                acceptWaveform(win) {
                  classified += win.length;
                  if (classified === 44032) segmentPending = true;
                },
                isDetected: () => classified < 44032,
                isEmpty: () => !segmentPending,
                front: () => ({ start: 0, samples: new Float32Array(40032) }),
                pop: () => { segmentPending = false; },
              };
              let fed = 0;
              while (gate.events.length === 0 && fed < 72000) {
                fed += frameSamples;
                await gate.advanceVadGateAsync(new Float32Array(frameSamples));
              }
              assert.deepEqual(gate.events, ['end']);
              assert.ok(classified >= 40032 + 25600 && classified < 40032 + 25600 + 512,
                `vadEnd=1600 includes native confirmation: classified=${classified}, fed=${fed}`);
            }
                """, synchronous=synchronous)

    def test_speech_resets_tail_and_initial_silence_emits_no_speech_end(self):
        self.run_gate("""
            const gate = new Gate();
            await gate.advanceVadGateAsync(new Float32Array(512 * 20));
            gate.vad.isDetected = () => true;
            await gate.advanceVadGateAsync(new Float32Array(512));
            assert.equal(gate.trailingSilenceMs, 0);
            assert.deepEqual(gate.events, []);
            const silent = new Gate();
            silent.vadSpeechActive = false;
            await silent.advanceVadGateAsync(new Float32Array(16000));
            assert.deepEqual(silent.events, []);
        """)

    def test_pending_speech_veto_preserves_gate_until_real_pcm_advances(self):
        for synchronous in (False, True):
            with self.subTest(synchronous=synchronous):
                self.run_gate("""
            for (const frameSamples of [160, 320, 512]) {
              const gate = new Gate();
              let probes = 0;
              gate.recognizer.getVadEndpointWaitSeconds = () => (++probes === 1 ? 0.24 : 0);
              let fed = 0;
              while (fed < 16000) {
                fed += frameSamples;
                await gate.advanceVadGateAsync(new Float32Array(frameSamples));
                assert.deepEqual(gate.events, [], 'pending real speech cannot announce an endpoint');
                assert.equal(gate.vadSpeechActive, true, 'veto must preserve the active utterance');
              }
              while (gate.events.length === 0 && fed < 18000) {
                fed += frameSamples;
                await gate.advanceVadGateAsync(new Float32Array(frameSamples));
              }
              assert.deepEqual(gate.events, ['end']);
              assert.equal(probes, 2, 'do not repeat ONNX while its known PCM condition is unchanged');
            }
                """, synchronous=synchronous)

    def test_cancel_during_native_probe_cannot_announce_endpoint(self):
        self.run_gate("""
            const gate = new Gate();
            gate.recognizer.getVadEndpointWaitSecondsAsync = async () => {
              gate.callbackGate.isClosed = () => true;
              return 0;
            };
            const result = await gate.advanceVadGateAsync(new Float32Array(12800));
            assert.equal(result.vadEndpoint, false);
            assert.deepEqual(gate.events, []);
            assert.equal(gate.vadEndpointPending, false);
        """)

    def test_already_announced_native_endpoint_is_not_announced_twice(self):
        self.run_gate("""
            const gate = new Gate();
            gate.vadEndpointPending = true;
            gate.recognizer.getVadEndpointWaitSecondsAsync = async () => {
              throw new Error('native endpoint already owns this transition');
            };
            assert.equal(await gate.confirmVadEndpointAsync(), true);
            assert.deepEqual(gate.events, []);
        """)


if __name__ == "__main__":
    unittest.main()
