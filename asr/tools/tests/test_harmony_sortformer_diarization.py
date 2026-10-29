"""Sortformer chain: slot identities, previews, frozen commits and the public boundary.

These tests inject engine reports (final/preview events with per-slot runs),
not audio: acoustic accuracy has its own real-device gate (dq5 DER).
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_diarization_session import (
    ROOT, DIARIZATION, SESSION, TS_LOADER, run_node,
)

IDENTITY = DIARIZATION / 'SortformerSpeakerIdentity.ts'
CLIENT = DIARIZATION / 'SortformerLocalClient.ets'
ENGINE = ROOT / 'asr/harmony/sdk/src/main/cpp/sortformer_diarization.cpp'


def run_sortformer_session(body):
    imports = "\n".join(
        f"import {{ {name} }} from {(DIARIZATION / (name + '.ts')).as_uri()!r};"
        for name in ["DiarizationCommitClock", "SpeakerDiarizationTranscriptState", "SortformerSpeakerIdentity"]
    )
    imports += f"\nimport {{ timelineTurns }} from {(DIARIZATION / 'SpeakerTimeline.ts').as_uri()!r};"
    imports += f"\nimport {{ speakerIndexFromInternalId, speakerIndexesFromInternalIds }} from {(DIARIZATION / 'SpeakerDiarizationSpeakerIndex.ts').as_uri()!r};"
    stubs = """
      import assert from 'node:assert/strict';
      const SAMPLE_RATE=16000;
      const ResultAudioTimeline={endSample:r=>r.audioEndSample};
      const SpeakerDiarizationDegradedReason={NONE:0,INFERENCE_UNAVAILABLE:1,MODEL_UNAVAILABLE:2,INFERENCE_TIMEOUT:3,FINISH_TIMEOUT:4,STORAGE_UNAVAILABLE:5};
      class SpeakerDiarizationResult {utterances=[];speakerTurns=[];}
      class DiarizedUtterance {} class SpeakerTurn {} class SpeakerTextSpan {} class SpeakerDiarizationUpdate {}
      class SortformerLocalClient {
        constructor(context, observer){this.observer=observer;}
        append(){} finish(){this.finished=true;} cancel(cb){cb?.()} cleanup(cb){cb?.()} stopInference(){this.stopped=true}
        pendingWindowCount(){return this.pending??0}
      }
      let released=0;
      const SpeakerDiarizationRuntimeLeaseRegistry={acquire:()=>({release(){released++}})};
      function session(maxSpeakers=4, observer={}) {return new SpeakerDiarizationSession({},'',maxSpeakers,{
        onSpeakerDiarizationUpdate(){},onWindowResult(){},onFinished(){},...observer});}
      // One engine report: runs per slot in ms; kind 'final' or 'preview'.
      function feed(jobId, kind, beginTime, endTime, runsBySlot, extra={}) {
        const runs=[0,1,2,3].map(slot=>runsBySlot[slot]??[]);
        return {jobId,audioEndSample:endTime*16,melEndTime:endTime,inferenceWallMs:1,flushed:false,
          events:[{kind,beginTime,endTime,inferenceMs:1,runs}],...extra};
      }
      const settle=()=>new Promise(r=>setImmediate(r));
    """
    source = SESSION.read_text()
    with tempfile.TemporaryDirectory() as directory:
        harness = Path(directory) / "sortformer.mts"
        harness.write_text(imports + stubs + source[source.index("export class SpeakerDiarizationSession"):] + body)
        subprocess.run(["node", "--experimental-strip-types", "--experimental-loader",
                        TS_LOADER.as_uri(), str(harness)], check=True, cwd=ROOT)


class HarmonySortformerIdentityTest(unittest.TestCase):
    def test_slots_become_roles_in_arrival_order_and_stop_at_the_cap(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SortformerSpeakerIdentity }} from {IDENTITY.as_uri()!r};
          const id=new SortformerSpeakerIdentity(2);
          // slot 2 speaks first in this chunk, slot 0 second, slot 1 silent.
          let m=id.commit([3000,-1,100,-1]);
          assert.deepEqual(m.mapping,[1,-1,0,-1]); assert.equal(m.after,2);
          // a third voice is beyond the caller's cap and stays anonymous forever
          m=id.commit([-1,500,-1,-1]);
          assert.deepEqual(m.mapping,[1,-1,0,-1]); assert.equal(id.publishedCount(),2);
          // published ids never move when a slot speaks again later
          m=id.commit([9000,9100,9200,9300]);
          assert.deepEqual(m.mapping,[1,-1,0,-1]);
        """)

    def test_identity_is_idempotent_for_silence(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SortformerSpeakerIdentity }} from {IDENTITY.as_uri()!r};
          const id=new SortformerSpeakerIdentity(4);
          assert.deepEqual(id.commit([-1,-1,-1,-1]).mapping,[-1,-1,-1,-1]);
          assert.equal(id.publishedCount(),0);
        """)


class HarmonySortformerSessionTest(unittest.TestCase):
    def test_final_chunk_publishes_roles_by_arrival_and_keeps_overlap(self):
        run_sortformer_session("""
          const s=session();s.totalSamples=16000*12;
          s.observeAsrFinal({result:'你好',beginTime:0,endTime:4000,isLast:false},
            {rawText:'你好',tokens:['你','好'],timestamps:[0,2],isLast:false,audioEndSample:64000});
          // slot 1 opens the meeting, slot 0 answers, both overlap 4000-4500
          s.onFeedResult(feed('f1','final',0,9920,{1:[[0,4500]],0:[[4000,9920]]}));
          const out=await s.commitWindow(9920,Infinity,true,0);
          assert.equal(out.speakerCount,2);
          assert.deepEqual(out.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex,t.overlap]),
            [[0,4000,0,false],[4000,4500,0,true],[4500,9920,1,false]]);
          assert.equal(out.utterances[0].speakerIndex,0,'first voice is role 0');
        """)

    def test_preview_shows_known_roles_but_not_unconfirmed_slots(self):
        run_sortformer_session("""
          const updates=[];const s=session(4,{onSpeakerDiarizationUpdate:u=>updates.push(u)});
          s.totalSamples=16000*20;
          s.onFeedResult(feed('f1','final',0,9920,{0:[[0,9920]]}));
          s.observeAsrFinal({result:'第二句',beginTime:10000,endTime:14000,isLast:false},
            {rawText:'第二句',tokens:['第','二','句'],timestamps:[10,12,13],isLast:false,audioEndSample:14000*16});
          // preview of the next chunk: slot 0 continues, slot 2 is new and not yet committed
          s.onFeedResult(feed('f2','preview',9920,14880,{0:[[9920,12000]],2:[[12000,14880]]}));
          const last=updates[updates.length-1];
          assert.ok(last!==undefined,'a preview refreshes provisional roles');
          assert.equal(last.speakerIndex,-1,'half the sentence is an unconfirmed slot: no owner yet');
          assert.deepEqual(last.secondarySpeakerIndexes,[0,-1]);
          // the final chunk confirms slot 2 as role 1 and the sentence settles
          s.onFeedResult(feed('f3','final',9920,19840,{0:[[9920,12000]],2:[[12000,19840]]}));
          const settled=updates[updates.length-1];
          assert.deepEqual([settled.speakerIndex,settled.secondarySpeakerIndexes],[-1,[0,1]],
            'a sentence split between two confirmed roles keeps both, with no single owner');
          assert.equal(s.identities.publishedCount(),2);
        """)

    def test_committed_turns_are_frozen_while_later_chunks_arrive(self):
        run_sortformer_session("""
          const published=[];const s=session(4,{onWindowResult:r=>published.push(r),onFinished:r=>published.push(r)});
          s.totalSamples=16000*30;
          s.onFeedResult(feed('f1','final',0,9920,{0:[[0,9920]]}));
          const first=await s.commitWindow(9920,9920,false,0);const frozen=JSON.stringify(s.committedTurns);
          assert.deepEqual(first.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex]),[[0,9920,0]]);
          s.onFeedResult(feed('f2','final',9920,19840,{1:[[9920,19840]]}));
          s.onFeedResult(feed('f3','final',19840,29760,{0:[[19840,29760]]}));
          const next=await s.commitWindow(29760,Infinity,true,9920);
          assert.equal(JSON.stringify(s.committedTurns.slice(0,1)),frozen);
          assert.deepEqual(next.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex]),
            [[9920,19840,1],[19840,29760,0]]);
          assert.equal(next.speakerCount,2);
        """)

    def test_degraded_client_yields_a_degraded_final_without_roles(self):
        run_sortformer_session("""
          const finished=[];const s=session(4,{onFinished:r=>finished.push(r)});
          s.totalSamples=16000*5;
          s.onFeedResult(feed('f1','preview',0,4960,{0:[[0,4960]]}));
          s.onDegraded(SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT,'stalled');
          s.observeAsrFinal({result:'',isLast:true},{rawText:'',tokens:[],timestamps:[],isLast:true,audioEndSample:80000});
          s.finish();s.onDrained();
          await settle();
          assert.equal(finished.length,1);
          assert.equal(finished[0].degradedReason,SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
          assert.deepEqual(finished[0].speakerTurns,[],'provisional roles are not promoted by a failure');
        """)

    def test_flush_marks_the_stream_complete_for_the_commit_clock(self):
        run_sortformer_session("""
          const finished=[];const s=session(4,{onFinished:r=>finished.push(r)});
          s.totalSamples=16000*12.5;
          s.onFeedResult(feed('f1','final',0,9920,{0:[[0,9920]]}));
          // tail chunk of 2.56 s inferred at flush; the last 20 ms never reaches an encoder frame
          s.onFeedResult(feed('f2','final',9920,12480,{0:[[9920,12480]]},{flushed:true,melEndTime:12500}));
          assert.equal(s.inferenceEndMs,12500);
          s.observeAsrFinal({result:'',isLast:true},{rawText:'',tokens:[],timestamps:[],isLast:true,audioEndSample:200000});
          s.finish();s.onDrained();
          await settle();
          assert.equal(finished.length,1);
          assert.ok(finished[0].isSessionFinal);
          assert.deepEqual(finished[0].speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex]),[[0,12480,0]]);
        """)


class HarmonySortformerSourceContractTest(unittest.TestCase):
    def test_client_feeds_in_order_with_one_call_in_flight(self):
        client = CLIENT.read_text(encoding='utf-8')
        self.assertIn("this.activeJobId.length > 0) return;", client)
        self.assertIn("flush", client)
        self.assertIn("INFERENCE_TIMEOUT_MS", client)
        self.assertIn("MAX_PENDING_SAMPLES", client)

    def test_engine_keeps_the_delivery_streaming_constants(self):
        engine = ENGINE.read_text(encoding='utf-8')
        for constant in ("kSpkCache = 188", "kChunk = 124", "kFifo = 188", "kRightCtx = 1",
                         "kPreemph = 0.97", "5.9604644775390625e-08"):
            self.assertIn(constant, engine)
        self.assertIn('"amphion-dingqiao/sortformer-66M-4spk/"', engine)
        self.assertNotIn("XNNPACK", engine, "the int8 encoder measured 4x slower on XNNPACK")


if __name__ == "__main__":
    unittest.main()
