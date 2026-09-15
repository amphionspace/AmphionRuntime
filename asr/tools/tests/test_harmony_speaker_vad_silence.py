"""Replay ordered score hops through production enqueue/evaluate methods."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_inference_threading import method_body

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets'
SUPPORT = RUNTIME.with_name('RuntimeSupport.ets')
FINALIZER = RUNTIME.with_name('SpeakerTurnFinalizer.ts')
LANE = RUNTIME.with_name('SpeakerInferenceLane.ts')


class HarmonySpeakerVadSilenceTest(unittest.TestCase):
    def test_silence_does_not_enter_turn_resolver_but_real_speaker_departure_does(self):
        source = RUNTIME.read_text()
        request = 'class SpeakerVadInferenceRequest' + SUPPORT.read_text().split(
            'class SpeakerVadInferenceRequest', 1)[1].split('\nexport ', 1)[0]
        enqueue = method_body(source, 'enqueueSpeakerVadInference')
        evaluate = method_body(source, 'evaluateSpeakerVadInferenceAsync')
        finalize = method_body(source, 'finalizeAnnouncedVadEndpointAsync')
        script = f"""
import assert from 'node:assert/strict';
import {{ SpeakerTurnFinalizer }} from {FINALIZER.as_uri()!r};
import {{ SpeakerInferenceLane }} from {LANE.as_uri()!r};
const ASR_SAMPLE_RATE_HZ = 16000;
const Logger = {{ metric() {{}}, w() {{}} }};
{request}
class Session {{
  speakerVadEnabled = true; svTurnFailOpen = false; svInferenceLoopActive = false;
  targetExtractor = {{}}; targetSpeaker = {{}}; vadSpeechActive = true;
  vadEndpointPending = false; svQueuedInferences = []; svContextWaitStartedSample = -1;
  svSilentDeparturePending = false; pendingVadStopAtEndpoint = true;
  speakerInferenceLane = new SpeakerInferenceLane();
  finalizer = new SpeakerTurnFinalizer(16000, 24000, 8000, 2, 160000);
  callbackGate = {{ isClosed: () => false }};
  sample = 16000; score = 0.7; detected = true; resolverCalls = 0; delays = 0;
  vad = {{ isDetected: () => this.detected }};
  config = {{ threshold: 0.35, winSec: 1.5, hopSec: 0.5, consecutiveBelow: 2 }};
  scheduler = {{ observe: n => {{ this.sample += n; return true; }},
    totalSamples: () => this.sample, hopSamples: 8000 }};
  speakerPcmBuffers = {{ speakerVadTail: () => new Float32Array(24000) }};
  effectiveSpeakerVad() {{ return this.config; }}
  speakerVadScoreScheduler() {{ return this.scheduler; }}
  speakerTurnFinalizer() {{ return this.finalizer; }}
  async scoreSamplesAsync() {{ await new Promise(r => setTimeout(r, this.delays)); return this.score; }}
  syncSpeakerTurnState(f) {{ this.svTargetConfirmed = f.isTargetConfirmed(); }}
  discardPreparedSpeakerTurnPrefix() {{}}
  startSpeakerTurnPrefixPreparationAsync() {{}}
  async resolveSpeakerTurnSplitAsync(f) {{
    this.resolverCalls++;
    await new Promise(r => setTimeout(r, 10));
    f.deferResolution('insufficient-refine-context');
    return undefined;
  }}
  enqueueSpeakerVadInference(samplesInChunk) {{ {enqueue} }}
  async evaluateSpeakerVadInferenceAsync(request, sv, scheduler, generation) {{ {evaluate} }}
  async finalizeAnnouncedVadEndpointAsync(decodeDurationMs = 0) {{ {finalize} }}
}}
for (const delay of [0, 5]) {{
  for (const hasSpeech of [false, true]) {{
    const s = new Session(); s.delays = delay;
    for (const score of [0.656, 0.621, 0.520, 0.245, 0.021]) {{
      s.score = score;
      s.detected = score >= 0.35 || hasSpeech;
      s.finalizer.accept(new Float32Array(8000));
      s.enqueueSpeakerVadInference(8000);
      // Mutating the live detector must not change the hop's immutable acoustic evidence.
      s.detected = !s.detected;
      await s.speakerInferenceLane.drain();
    }}
    assert.equal(s.resolverCalls, hasSpeech ? 1 : 0,
      'silence after a confirmed target must wait for acoustic vadEnd, not speaker refinement');
    assert.equal(s.svContextWaitStartedSample, hasSpeech ? 56000 : -1);
    assert.equal(s.finalizer.hasPendingDeparture(), true, 'deferred evidence must survive for final filtering');
    assert.equal(s.svSilentDeparturePending, !hasSpeech);
    if (!hasSpeech) {{
      const callbacks = ['speech-end'];
      s.commitCleanSpeakerTurnAsync = async (isLast, endpointTriggered) => {{
        assert.equal(isLast, true, 'finish inside SPEECH_END must promote this same final');
        assert.equal(endpointTriggered, true);
        assert.equal(s.finalizer.hasPendingDeparture(), true);
        await new Promise(r => setTimeout(r, delay));
        callbacks.push('clean-final-last', 'complete');
        return true;
      }};
      s.dispatchFinal = () => assert.fail('must not publish speculative non-target suffix');
      await s.finalizeAnnouncedVadEndpointAsync();
      assert.deepEqual(callbacks, ['speech-end', 'clean-final-last', 'complete']);
    }}
  }}
}}
"""
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'speaker-silence.mts'
            harness.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', '--experimental-loader',
                            (ROOT / 'asr/tools/tests/ts_extension_loader.mjs').as_uri(), str(harness)],
                           check=True, cwd=ROOT)

    def test_returning_speech_resolves_pending_turn_before_new_score_or_decode(self):
        body = method_body(RUNTIME.read_text(), 'feedChunkAndDecodeAsync')
        script = f"""
import assert from 'node:assert/strict';
const shouldSettleSpeakerInferenceBeforeNextSlice = () => false;
const pcm = Float32Array.from([0.2, -0.1, 0.3, -0.2]);
class Session {{
  svSilentDeparturePending = true; publicSamplesFed = 100;
  speakerVadEnabled = true; svTargetConfirmed = true; svBelowCount = 2;
  callbackGate = {{ isClosed: () => false }};
  initialSilenceTracker = {{ hasTimedOut: () => false, isArmed: () => false,
    observeAcousticSamples() {{}} }};
  effectiveSpeechBuffer = {{ observe() {{}} }};
  speakerPcmBuffers = {{ observe() {{}} }};
  retained = []; timeline = [];
  finalizer = {{ accept: raw => this.retained.push(...raw) }};
  effectiveSpeakerVad() {{ return {{ consecutiveBelow: 2 }}; }}
  speakerTurnFinalizer() {{ return this.finalizer; }}
  vad = {{ isDetected: () => true }};
  async advanceVadGateAsync() {{ return {{ vadEndpoint: false }}; }}
  async triggerSpeakerVadEndpointAsync() {{
    assert.deepEqual(this.retained, Array.from(pcm), 'returning PCM must remain in clean-turn suffix');
    this.timeline.push('resolve-old-turn');
  }}
  enqueueSpeakerVadInference() {{ assert.fail('new target score must not erase pending departure'); }}
  async feedRecognizerAsync() {{ assert.fail('suffix must not be fed twice'); }}
  async feedChunkAndDecodeAsync(rawSamples, processedSamples, replay = false) {{ {body} }}
}}
const s = new Session();
await s.feedChunkAndDecodeAsync(pcm, pcm);
assert.deepEqual(s.timeline, ['resolve-old-turn']);
assert.equal(s.publicSamplesFed, 104);
"""
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'returning-speaker.mts'
            harness.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', str(harness)],
                           check=True, cwd=ROOT)


if __name__ == '__main__':
    unittest.main()
