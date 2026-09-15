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
  }}
}}
"""
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'speaker-silence.mts'
            harness.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', '--experimental-loader',
                            (ROOT / 'asr/tools/tests/ts_extension_loader.mjs').as_uri(), str(harness)],
                           check=True, cwd=ROOT)


if __name__ == '__main__':
    unittest.main()
