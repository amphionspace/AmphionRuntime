"""Identity decisions must use current speech and preserve acoustic evidence."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_diarization_session import (
    DIARIZATION, REGISTRY, ROOT, SESSION, TIMELINE, TS_LOADER, run_node,
)


def run_session(body: str) -> None:
    names = ["DiarizationCommitClock", "OnlineSpeakerRegistry",
             "SpeakerDiarizationGlobalClusterer", "SpeakerDiarizationTranscriptState"]
    imports = "\n".join(
        f"import {{ {name} }} from {(DIARIZATION / (name + '.ts')).as_uri()!r};"
        for name in names
    )
    imports += f"\nimport {{ speakerIndexFromInternalId, speakerIndexesFromInternalIds }} from {(DIARIZATION / 'SpeakerDiarizationSpeakerIndex.ts').as_uri()!r};"
    stubs = """
      import assert from 'node:assert/strict';
      const SAMPLE_RATE=16000;
      const SpeakerDiarizationDegradedReason={NONE:0};
      class SpeakerDiarizationResult {utterances=[];speakerTurns=[];}
      class DiarizedUtterance {} class SpeakerTurn {} class SpeakerDiarizationUpdate {}
      class SpeakerDiarizationLocalClient {}
      const SpeakerDiarizationRuntimeLeaseRegistry={acquire:()=>({release(){}})};
      function session() {return new SpeakerDiarizationSession({},'',4,{
        onSpeakerDiarizationUpdate(){},onWindowResult(){},onFinished(){}});}
    """
    source = SESSION.read_text()
    with tempfile.TemporaryDirectory() as directory:
        harness = Path(directory) / "identity.mts"
        harness.write_text(imports + stubs + source[source.index("export class SpeakerDiarizationSession"):] + body)
        subprocess.run(["node", "--experimental-strip-types", "--experimental-loader",
                        TS_LOADER.as_uri(), str(harness)], check=True, cwd=ROOT)


class HarmonyDiarizationIdentityStabilityTest(unittest.TestCase):
    def test_context_without_output_query_cannot_enroll_or_redirect_another_speaker(self):
        run_session("""
          const s=session(); s.totalSamples=320000;
          s.committedRegistry.assign(new Float32Array([1,0,0]),6000,0);
          const voice=[0,1,0];
          const query=[Math.sqrt(1-.57**2-.636**2),.57,.636];
          function window(id,begin,end,contextBegin,embedding,queryEmbedding) {
            s.onWindow({jobId:id,windowStartSample:0,contentStartInWindowSample:0,
              realEndSample:320000,commitStartSample:begin*16,stableEndSample:end*16,
              finalWindow:false,result:{inferenceMs:0,segments:[{
                startSample:contextBegin*16,endSample:end*16,speaker:0,speakerMask:1}],
                embeddings:[{localSpeaker:0,speechSamples:(end-contextBegin)*16,
                  embedding,queryEmbedding}]}});
          }
          window('supported',6000,10000,6000,voice,voice);
          window('query',10000,12000,8000,voice,query);
          window('mixed-context',12000,12673,9163,[0,0,1],undefined);
          const result=s.commitWindow(20000,Infinity,true);
          assert.deepEqual(result.speakerTurns.map(t=>t.speakerIndex),[1,1,-1],
            'sub-second output without a query must not create a role that steals a known turn');
          assert.equal(result.speakerCount,2);
        """)

    def test_repeated_short_context_cannot_enroll_a_new_speaker(self):
        run_session("""
          function run(embedding, speechMs, seedMs=6000) {
            const s=session(); s.totalSamples=224000;
            const windows=[{start:0,end:seedMs,embedding:[1,0]}];
            for(let i=0;i<4;i++) windows.push({start:7000,end:7000+speechMs,embedding});
            for(let i=0;i<windows.length;i++) {
              const w=windows[i];
              s.onWindow({jobId:`w${i}`,windowStartSample:0,contentStartInWindowSample:0,
                realEndSample:224000,commitStartSample:i<2 ? 0 : 176000,
                stableEndSample:224000,finalWindow:false,result:{inferenceMs:0,
                  segments:[{startSample:w.start*16,endSample:w.end*16,speaker:0,speakerMask:1}],
                  embeddings:[{localSpeaker:0,speechSamples:(w.end-w.start)*16,embedding:w.embedding,
                    queryEmbedding:i<2 ? w.embedding : undefined}]}});
            }
            const provisional=s.registry.speakerIds();
            const result=s.commitWindow(14000,Infinity,true);
            return {provisional,result};
          }
          const first=run([1,0],1200,1200);
          assert.deepEqual(first.provisional,['S1']);
          assert.equal(first.result.speakerCount,1,'do not delay the first speaker of a short session');
          assert.equal(run([0,1],2999).result.speakerCount,1,'new identity waits for sufficient evidence');
          const short=run([.53,Math.sqrt(1-.53**2)],1200);
          assert.deepEqual(short.provisional,['S1'],
            'one short uncertain fragment must not create a provisional extra person');
          assert.equal(short.result.speakerCount,1,
            'four overlapping observations of 1.2s are not 4.8s of enrollment evidence');
          assert.deepEqual(short.result.speakerTurns.map(t=>t.speakerIndex),[0,-1]);
          const known=run([1,0],1200);
          assert.deepEqual(known.result.speakerTurns.map(t=>t.speakerIndex),[0,0],
            'short evidence can still recognize an established speaker');
          const distinct=run([0,1],3000);
          assert.deepEqual(distinct.provisional,['S1','S2']);
          assert.deepEqual(distinct.result.speakerTurns.map(t=>t.speakerIndex).sort(),[0,1],
            'sufficient independent evidence can still enroll another speaker');
        """)

    def test_historical_context_cannot_compete_with_current_speech(self):
        run_session("""
          const s=session(); s.registry.assign(new Float32Array([1,0,0]),2000,4000);
          const current=[.767,Math.sqrt(1-.767**2),0];
          const window={jobId:'current',windowStartSample:0,contentStartInWindowSample:0,
            realEndSample:160000,commitStartSample:96000,stableEndSample:136000,finalWindow:false,
            result:{inferenceMs:0,segments:[
              {startSample:32000,endSample:96000,speaker:0,speakerMask:1},
              {startSample:121600,endSample:160000,speaker:1,speakerMask:2}],
              embeddings:[{localSpeaker:0,speechSamples:32000,embedding:[1,0,0]},
                {localSpeaker:1,speechSamples:38400,embedding:current}]}};
          s.onWindow(window);
          assert.deepEqual(s.transcript.allTurns().map(t=>t.speakerId),['S1'],
            'a closer historical fragment must not force the current speaker into a new role');
          assert.deepEqual(s.registry.speakerIds(),['S1']);
          assert.equal(s.recentEmbeddingObservations.length,2,
            'window-final clustering still needs the original contextual evidence');
          const other=session(); other.registry.assign(new Float32Array([1,0,0]),2000,4000);
          window.result.segments[0].endSample=136000;
          window.result.segments[1].startSample=112000;
          window.result.embeddings[1].embedding=[0,1,0];
          window.result.embeddings[1].speechSamples=48000;
          other.onWindow(window);
          assert.deepEqual(other.registry.speakerIds(),['S1','S2'],
            'two actual current speakers remain eligible for different roles');
        """)

    def test_uncertain_match_does_not_prove_a_new_identity(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const registry=new OnlineSpeakerRegistry();
          registry.assign(new Float32Array([1,0,0]),6000,0);
          const uncertain=registry.assign(new Float32Array([.68,Math.sqrt(1-.68**2),0]),2000,2000);
          assert.equal(uncertain.speakerId,'UNKNOWN',
            'below acceptance but within known-speaker query range must not create a new person');
          assert.deepEqual(registry.speakerIds(),['S1']);
          assert.equal(registry.assign(new Float32Array([0,1,0]),2000,4000).speakerId,'S2');
          assert.equal(registry.assign(new Float32Array([Math.SQRT1_2,Math.SQRT1_2,0]),2000,6000).speakerId,'UNKNOWN');
          assert.deepEqual(registry.speakerIds(),['S1','S2']);
          assert.equal(registry.assign(new Float32Array([.9,0,Math.sqrt(.19)]),2000,8000).speakerId,'S1');
        """)

    def test_final_overlap_does_not_depend_on_provisional_unknown_collisions(self):
        run_session("""
          function run(provisional) {
            const s=session(); s.totalSamples=153600;
            s.registry.assignBatch=()=>provisional.map(speakerId=>({speakerId,confidence:1,created:false}));
            s.onWindow({jobId:'same-audio',windowStartSample:0,contentStartInWindowSample:0,
              realEndSample:153600,commitStartSample:0,stableEndSample:153600,finalWindow:true,
              result:{inferenceMs:0,segments:[
                {startSample:0,endSample:51200,speaker:0,speakerMask:1},
                {startSample:51200,endSample:102400,speaker:1,speakerMask:2},
                {startSample:102400,endSample:153600,speaker:0,speakerMask:3}],
                embeddings:[{localSpeaker:0,speechSamples:51200,embedding:[1,0],queryEmbedding:[1,0]},
                  {localSpeaker:1,speechSamples:51200,embedding:[0,1],queryEmbedding:[0,1]}]}});
            return s.commitWindow(9600,9600,true);
          }
          const known=run(['S1','S2']); const unknown=run(['UNKNOWN','UNKNOWN']);
          assert.deepEqual(unknown.speakerTurns,known.speakerTurns,
            'final acoustic attribution must retain both channels regardless of provisional IDs');
          assert.deepEqual(unknown.speakerTurns.at(-1).secondarySpeakerIndexes,[1]);
        """)

    def test_remapping_a_hidden_secondary_preserves_its_evidence_binding(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const state=new SpeakerDiarizationTranscriptState();
          state.applySpeakerTurns([{{beginTime:0,endTime:2000,speakerId:'S1',
            secondarySpeakerIds:['S2','S3'],evidenceKey:'a',secondaryEvidenceKeys:['b','c']}}]);
          state.applyEvidenceRemap({{a:'S1',b:'S1',c:'S3'}});
          assert.deepEqual(state.allTurns()[0].secondarySpeakerIds,['S3']);
          state.applyEvidenceRemap({{b:'S2'}});
          assert.deepEqual(state.allTurns()[0].secondarySpeakerIds,['S2','S3'],
            'remapping b must neither consume nor replace the identity belonging to c');
        """)
