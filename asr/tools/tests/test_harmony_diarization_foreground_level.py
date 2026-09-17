"""The loud-speaker mode must leave role capacity for four principal voices."""
import unittest

from asr.tools.tests.test_harmony_diarization_identity_stability import run_session


class HarmonyDiarizationForegroundLevelTest(unittest.TestCase):
    def test_later_louder_speech_revises_only_uncommitted_quiet_evidence(self):
        run_session("""
          const s=session();s.totalSamples=160000;
          for(let i=0;i<2;i++) {
            const embedding=i===0?[1,0]:[0,1], begin=i*80000;
            s.onWindow({jobId:`w${i}`,windowStartSample:begin,contentStartInWindowSample:0,
              realEndSample:begin+80000,commitStartSample:begin,stableEndSample:begin+80000,
              finalWindow:false,result:{inferenceMs:0,
                segments:[{startSample:0,endSample:80000,speaker:0,speakerMask:1}],
                embeddings:[{localSpeaker:0,speechSamples:80000,embedding,queryEmbedding:embedding,
                  speechRms:i===0?.01:.1}]}});
          }
          const result=s.commitWindow(10000,Infinity,true);
          assert.deepEqual(result.speakerTurns.map(t=>t.speakerIndex),[-1,0],
            'excluded early evidence must not retain an old provisional ID');
          assert.equal(result.speakerCount,1);
        """)

    def test_quieter_background_cannot_displace_four_principal_voices(self):
        run_session("""
          function replay(gain) {
            const s=session(); s.totalSamples=40000*16;
            const vector=id=>Array.from({length:6},(_,i)=>i===id?1:0);
            const speakers=[0,4,1,5,2,3,0,1,2,3];
            speakers.forEach((id,i)=>{
              const begin=i*4000, end=begin+4000;
              s.onWindow({jobId:`w${i}`,windowStartSample:begin*16,contentStartInWindowSample:0,
                realEndSample:end*16,commitStartSample:begin*16,stableEndSample:end*16,
                finalWindow:false,result:{inferenceMs:0,
                  segments:[{startSample:0,endSample:64000,speaker:0,speakerMask:1}],
                  embeddings:[{localSpeaker:0,speechSamples:64000,embedding:vector(id),
                    queryEmbedding:vector(id),speechRms:(id>=4?.01:.1)*gain}]}});
            });
            const online=s.transcript.allTurns().map(t=>t.speakerId);
            const result=s.commitWindow(40000,Infinity,true);
            return {online,result};
          }
          const expected=['S1','UNKNOWN','S2','UNKNOWN','S3','S4','S1','S2','S3','S4'];
          const normal=replay(1),quietGain=replay(.1);
          assert.deepEqual(normal.online,expected,'background must not occupy the four roles');
          assert.deepEqual(normal.result.speakerTurns.map(t=>t.speakerIndex),[0,-1,1,-1,2,3,0,1,2,3]);
          assert.equal(normal.result.speakerCount,4);
          assert.deepEqual(quietGain,normal,'overall recording gain must not change relative eligibility');
        """)


if __name__ == '__main__':
    unittest.main()
