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
          window.result.embeddings[1].embedding=[0,1,0];
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
            const s=session(); s.totalSamples=32000;
            s.registry.assignBatch=()=>provisional.map(speakerId=>({speakerId,confidence:1,created:false}));
            s.onWindow({jobId:'same-audio',windowStartSample:0,contentStartInWindowSample:0,
              realEndSample:32000,commitStartSample:0,stableEndSample:32000,finalWindow:true,
              result:{inferenceMs:0,segments:[{startSample:0,endSample:32000,speaker:0,speakerMask:3}],
                embeddings:[{localSpeaker:0,speechSamples:32000,embedding:[1,0]},
                  {localSpeaker:1,speechSamples:32000,embedding:[0,1]}]}});
            return s.commitWindow(2000,2000,true);
          }
          const known=run(['S1','S2']); const unknown=run(['UNKNOWN','UNKNOWN']);
          assert.deepEqual(unknown.speakerTurns,known.speakerTurns,
            'final acoustic attribution must retain both channels regardless of provisional IDs');
          assert.deepEqual(unknown.speakerTurns[0].secondarySpeakerIndexes,[1]);
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
