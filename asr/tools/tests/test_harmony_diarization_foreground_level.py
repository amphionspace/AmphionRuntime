"""Community role visibility is independent of a global recording-level gate."""
import unittest
from asr.tools.tests.test_harmony_community_diarization import run_community_session


class HarmonyDiarizationForegroundLevelTest(unittest.TestCase):
    def test_four_distinct_voices_keep_roles_without_a_global_level_gate(self):
        run_community_session("""
          async function replay(gain) {
            const s=session();s.totalSamples=16000*13;
            for(let i=0;i<4;i++) {const w=window(i);w.result.speechRms=[.01,.03,.2,.02][i]*gain;s.onWindow(w);}
            s.client.cluster=async()=>({speakerCount:4,hard:[0,-2,-2,1,-2,-2,2,-2,-2,3,-2,-2],
              turns:[[0,1000,0],[1000,2000,1],[2000,3000,2],[3000,13000,3]]});
            const out=await s.commitWindow(13000,Infinity,true,0);
            return {count:out.speakerCount,turns:out.speakerTurns};
          }
          const normal=await replay(1);
          assert.equal(normal.count,4);
          assert.deepEqual(normal.turns.map(t=>t.speakerIndex),[0,1,2,3]);
          assert.deepEqual(await replay(.01),normal);
        """)
