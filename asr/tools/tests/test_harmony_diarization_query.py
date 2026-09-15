"""Output-slice evidence may query established roles without changing their profiles."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_diarization_session import REGISTRY, ROOT, TIMELINE, run_node


class HarmonyDiarizationQueryTest(unittest.TestCase):
    def test_corrected_confidence_is_frozen_with_its_utterance(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const transcript = new SpeakerDiarizationTranscriptState();
          transcript.addUtterance({{rawText:'甲',text:'甲',tokens:['甲'],tokenTimesMs:[100],beginTime:0,endTime:1000}});
          transcript.applySpeakerTurns([{{beginTime:0,endTime:1000,speakerId:'S2',secondarySpeakerIds:[],confidence:1,evidenceKey:'query'}}]);
          transcript.applyEvidenceRemap({{query:'S1'}},0,{{query:.63}});
          const published=transcript.commitThrough(1000)[0];
          assert.equal(published.speakerId,'S1');
          assert.equal(published.confidence,.63);
          assert.deepEqual(transcript.applyEvidenceRemap({{query:'S2'}},0,{{query:1}}),[]);
          assert.equal(published.confidence,.63);
        """)

    def test_short_query_corrects_membership_without_changing_enrollment(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const registry = new OnlineSpeakerRegistry();
          registry.assign(new Float32Array([1,0,0]), 6000, 0);
          registry.assign(new Float32Array([0,1,0]), 6000, 0);
          const before = registry.snapshot();
          const query = [.63,.41,Math.sqrt(1-.63**2-.41**2)];
          assert.equal(registry.matchKnown(query), undefined);
          const match = registry.matchQuery(query, new Set(['S1','S2']));
          assert.equal(match?.speakerId, 'S1');
          assert.ok(Math.abs(match.confidence-.63)<1e-6);
          assert.equal(match.created, false);
          assert.equal(registry.matchQuery([.67,.67,Math.sqrt(1-2*.67**2)], new Set(['S1','S2'])), undefined);
          assert.equal(registry.matchQuery([-1,0,0], new Set(['S1','S2'])), undefined);
          assert.deepEqual(registry.snapshot(), before);
        """)

    def test_query_cannot_introduce_a_context_only_role(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const registry = new OnlineSpeakerRegistry();
          registry.assign(new Float32Array([-1,0,0]), 6000, 0);
          registry.assign(new Float32Array([1,0,0]), 6000, 0);
          const query = [.693,0,Math.sqrt(1-.693**2)];
          registry.assign(new Float32Array(query), 1076, 0);
          assert.equal(registry.matchKnown(query), 'S3');
          const before = registry.snapshot();
          assert.equal(registry.matchQuery(query, new Set(['S1','S2']))?.speakerId, 'S2');
          assert.equal(registry.matchQuery(query, new Set()), undefined);
          assert.deepEqual(registry.snapshot(), before);
        """)

    def test_query_pcm_is_restricted_to_the_owned_output_slice(self):
        path = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'
        source = path.read_text()
        source = source[source.index('const SAMPLE_RATE:'):]
        driver = """
          import assert from 'node:assert/strict';
          const samples = Float32Array.from({length:160000}, (_,i)=>i/160000);
          const segments = [
            {startSample:0,endSample:48000,speaker:0,speakerMask:1},
            {startSample:48000,endSample:64000,speaker:0,speakerMask:3},
            {startSample:64000,endSample:96000,speaker:1,speakerMask:2},
            {startSample:96000,endSample:144000,speaker:0,speakerMask:1},
          ];
          async function processSpeakerTurnSegmentationAsync() { return segments; }
          const consumed=[]; let released=0;
          const inference=new SpeakerDiarizationInference();
          inference.extractor={
            createStream(){ return {acceptWaveform(w){this.samples=w.samples;},close(){released++;}}; },
            isReady(){return true;},
            async computeAsync(stream){consumed.push(stream.samples);return new Float32Array([stream.samples.length,stream.samples[0]]);},
          };
          const result=await inference.process(samples,96000,128000);
          assert.deepEqual(result.embeddings[0].queryEmbedding,[32000,samples[96000]]);
          assert.deepEqual(consumed[1],samples.slice(96000,128000));
          assert.equal(result.embeddings[0].speechSamples,96000);
          assert.equal(result.embeddings[1].queryEmbedding,undefined);
          assert.equal(released,consumed.length);
          consumed.length=0;
          const short=await inference.process(samples,136000,144000);
          assert.equal(short.embeddings[0].queryEmbedding,undefined);
          assert.equal(consumed.length,2,'sub-second queries must not borrow context or pad silence');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'query.mts'
            harness.write_text(source + driver)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True, cwd=ROOT)
