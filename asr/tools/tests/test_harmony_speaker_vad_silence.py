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
    def test_departure_evidence_requires_a_speech_bearing_low_hop(self):
        """离场证据必须有声学依据：至少一跳低分窗口带 VAD 语音。

        窗口是固定 winSec 的尾部音频，机主停口后被静音稀释，嵌入随之失真——同一段机主语音
        窗口满时 0.545、尾部 0.93 s 静音时 -0.072（手机 80 实测）。两跳低分都在静音里时据此
        切分，会把机主句尾切掉：缺陷 #98 实测「那我们按顺序逐项过一遍」只发布到「逐」，还
        拆开了「逐项」。只要有一跳低分带语音（真的有人接话），证据照旧保留到 vadEnd 后切分，
        #87 的非机主拦截不受影响。
        """
        source = RUNTIME.read_text()
        request = 'class SpeakerVadInferenceRequest' + SUPPORT.read_text().split(
            'class SpeakerVadInferenceRequest', 1)[1].split('\nexport ', 1)[0]
        enqueue = method_body(source, 'enqueueSpeakerVadInference')
        evaluate = method_body(source, 'evaluateSpeakerVadInferenceAsync')
        finalize = method_body(source, 'finalizeAnnouncedVadEndpointAsync')
        speech_active = method_body(source, 'speakerVadSpeechWasActive')
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
  svEndpointReady = false; svRejectCurrentUtterance = false;
  speakerInferenceLane = new SpeakerInferenceLane();
  finalizer = new SpeakerTurnFinalizer(16000, 24000, 8000, 2, 160000);
  callbackGate = {{ isClosed: () => false }};
  sample = 16000; score = 0.7; detected = true; resolverCalls = 0; delays = 0;
  published = []; vad = {{ isDetected: () => this.detected }};
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
  async prepareVadEndpointSpeakerScoreAsync() {{ return true; }}
  dispatchFinal(endpointTriggered, decodeMs, isLast) {{
    this.published.push(`final:${{isLast ? 'last' : 'non-last'}}`);
  }}
  notifyStopped() {{ this.published.push('complete'); }}
  resetVadGateState() {{}}
  async commitCleanSpeakerTurnAsync() {{ this.published.push('clean-split'); return true; }}
  speakerVadSpeechWasActive() {{ {speech_active} }}
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
const scores = [0.656, 0.621, 0.520, 0.245, 0.021];
// speech[i] 是该跳窗口有没有 VAD 语音。两跳低分分别对应 0.245 / 0.021。
const cases = [
  {{ name: 'real-departure', speech: [true, true, true, true, true],
    resolverCalls: 1, contextWait: 56000, pendingDeparture: true,
    silentPending: false, published: null }},
  {{ name: 'mixed-first-low-has-speech', speech: [true, true, true, true, false],
    resolverCalls: 0, contextWait: -1, pendingDeparture: true,
    silentPending: true, published: ['clean-split'] }},
  {{ name: 'silence-only', speech: [true, true, true, false, false],
    resolverCalls: 0, contextWait: -1, pendingDeparture: false,
    silentPending: false, published: ['final:last', 'complete'] }},
];
for (const delay of [0, 5]) {{
  for (const scenario of cases) {{
    const s = new Session(); s.delays = delay;
    for (const [index, score] of scores.entries()) {{
      s.score = score;
      s.detected = scenario.speech[index];
      s.finalizer.accept(new Float32Array(8000));
      s.enqueueSpeakerVadInference(8000);
      // Mutating the live detector must not change the hop's immutable acoustic evidence.
      s.detected = !s.detected;
      await s.speakerInferenceLane.drain();
    }}
    const where = `${{scenario.name}} delay=${{delay}}`;
    assert.equal(s.resolverCalls, scenario.resolverCalls,
      `${{where}}: silence after a confirmed target must wait for acoustic vadEnd, not refinement`);
    assert.equal(s.svContextWaitStartedSample, scenario.contextWait, where);
    assert.equal(s.finalizer.hasPendingDeparture(), scenario.pendingDeparture,
      `${{where}}: a departure needs at least one low hop carrying VAD speech`);
    assert.equal(s.svSilentDeparturePending, scenario.silentPending, where);
    if (scenario.published !== null) {{
      await s.finalizeAnnouncedVadEndpointAsync();
      assert.deepEqual(s.published, scenario.published,
        `${{where}}: silence-only evidence must publish the owner's whole utterance, ` +
        `speech-bearing evidence must still cut the turn`);
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

    def test_returning_speech_survives_clean_split_and_unresolved_fallback(self):
        body = method_body(RUNTIME.read_text(), 'feedChunkAndDecodeAsync')
        script = f"""
import assert from 'node:assert/strict';
const shouldSettleSpeakerInferenceBeforeNextSlice = () => false;
const pcm = Float32Array.from([0.2, -0.1, 0.3, -0.2]);
class Session {{
  svSilentDeparturePending = true; publicSamplesFed = 100;
  svQueuedInferences = [];
  speakerVadEnabled = true; svTargetConfirmed = true; svBelowCount = 2;
  callbackGate = {{ isClosed: () => false }};
  initialSilenceTracker = {{ hasTimedOut: () => false, isArmed: () => false,
    observeAcousticSamples() {{}} }};
  effectiveSpeechBuffer = {{ observe() {{}} }};
  speakerPcmBuffers = {{ observe() {{}} }};
  retained = []; decoded = []; timeline = []; cleanSplit = false;
  finalizer = {{ accept: raw => this.retained.push(...raw) }};
  effectiveSpeakerVad() {{ return {{ consecutiveBelow: 2 }}; }}
  speakerTurnFinalizer() {{ return this.finalizer; }}
  vad = {{ isDetected: () => true }};
  async advanceVadGateAsync() {{ return {{ vadEndpoint: false }}; }}
  async triggerSpeakerVadEndpointAsync() {{
    this.timeline.push('resolve-old-turn');
    // A clean split replays its retained suffix; an unresolved fallback resets the old turn.
    if (this.cleanSplit) this.decoded.push(...this.retained);
    this.retained = [];
    this.svSilentDeparturePending = false;
    this.svBelowCount = 0;
  }}
  enqueueSpeakerVadInference() {{
    assert.equal(this.svSilentDeparturePending, false, 'new score must not erase pending departure');
    this.timeline.push('new-score');
  }}
  async feedRecognizerAsync(raw) {{ this.decoded.push(...raw); }}
  async feedChunkAndDecodeAsync(rawSamples, processedSamples, replay = false) {{ {body} }}
}}
for (const cleanSplit of [true, false]) {{
  const s = new Session(); s.cleanSplit = cleanSplit;
  await s.feedChunkAndDecodeAsync(pcm, pcm);
  assert.equal(s.timeline[0], 'resolve-old-turn');
  assert.deepEqual(s.decoded, Array.from(pcm),
    `returning PCM must be decoded exactly once, cleanSplit=${{cleanSplit}}`);
  assert.equal(s.publicSamplesFed, 104, 'public PCM must only be counted once');
}}
"""
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'returning-speaker.mts'
            harness.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', str(harness)],
                           check=True, cwd=ROOT)


if __name__ == '__main__':
    unittest.main()
