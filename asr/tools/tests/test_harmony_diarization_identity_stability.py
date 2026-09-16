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

