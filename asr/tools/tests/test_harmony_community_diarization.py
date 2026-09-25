"""Community input geometry and irreversible SDK publication boundaries."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_diarization_session import (
    ROOT, DIARIZATION, SESSION, TS_LOADER, run_node,
)


def run_community_session(body):
    imports = "\n".join(
        f"import {{ {name} }} from {(DIARIZATION / (name + '.ts')).as_uri()!r};"
        for name in ["DiarizationCommitClock", "SpeakerDiarizationTranscriptState"]
    )
    imports += f"\nimport {{ CommunitySpeakerIdentity, communityTimeline }} from {(DIARIZATION / 'CommunitySpeakerIdentity.ts').as_uri()!r};"
    imports += f"\nimport {{ speakerIndexFromInternalId, speakerIndexesFromInternalIds }} from {(DIARIZATION / 'SpeakerDiarizationSpeakerIndex.ts').as_uri()!r};"
    stubs = """
      import assert from 'node:assert/strict';
      const SAMPLE_RATE=16000;
      const ResultAudioTimeline={endSample:r=>r.audioEndSample};
      const SpeakerDiarizationDegradedReason={NONE:0,INFERENCE_UNAVAILABLE:1};
      class SpeakerDiarizationResult {utterances=[];speakerTurns=[];}
      class DiarizedUtterance {} class SpeakerTurn {} class SpeakerDiarizationUpdate {}
      class SpeakerDiarizationLocalClient {cancel(cb){cb?.()} cleanup(cb){cb?.()} finish(){}}
      function session() {return new SpeakerDiarizationSession({},'',4,{
        onSpeakerDiarizationUpdate(){},onWindowResult(){},onFinished(){}});}
      let released=0;
      const SpeakerDiarizationRuntimeLeaseRegistry={acquire:()=>({release(){released++}})};
      function window(index) {
        const segments=new Float32Array(589*3);for(let f=0;f<589;f++)segments[f*3]=1;
        return {jobId:`w${index}`,windowStartSample:index*16000,realEndSample:(index+10)*16000,
          result:{segments,embeddings:new Float32Array(3*256),segmentationMs:0,featureMs:0,embeddingMs:0}};
      }
      function clusterResult(windows) {return {speakerCount:1,hard:Array(windows*3).fill(0),
        trainingIndices:[],ahc:[],priors:[1],turns:[[0,(windows+9)*1000,0]]};}
    """
    source = SESSION.read_text()
    with tempfile.TemporaryDirectory() as directory:
        harness = Path(directory) / "community.mts"
        harness.write_text(imports + stubs + source[source.index("export class SpeakerDiarizationSession"):] + body)
        subprocess.run(["node", "--experimental-strip-types", "--experimental-loader",
                        TS_LOADER.as_uri(), str(harness)], check=True, cwd=ROOT)


class HarmonyCommunityDiarizationTest(unittest.TestCase):
    def test_silence_placeholder_cannot_enroll_or_consume_a_role(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ CommunitySpeakerIdentity }} from {(DIARIZATION/'CommunitySpeakerIdentity.ts').as_uri()!r};
          const ids=new CommunitySpeakerIdentity(1);
          assert.equal(ids.assign([-2,-2,-2],1,[0,0,0]).after,0);
          const voice=ids.assign([-2,-2,-2,0,-2,-2],1,[0,0,0,200,0,0]);
          assert.deepEqual(voice.mapping,[0]);assert.equal(voice.after,1);
        """)

    def test_official_windows_are_frame_independent_and_do_not_repeat_tail(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ DiarizationWindowScheduler }} from {(DIARIZATION/'DiarizationWindowScheduler.ts').as_uri()!r};
          function schedule(samples,frame) {{
            const s=new DiarizationWindowScheduler(16000),windows=[];
            for(let p=0;p<samples;p+=frame)windows.push(...s.acceptSamples(Math.min(frame,samples-p)));
            const tail=s.finish();if(tail)windows.push(tail);return windows;
          }}
          for(const seconds of [0,0.5,9,9.9,10,10.1,11,180,180.125]) {{
            const n=Math.round(seconds*16000),a=schedule(n,320),b=schedule(n,Math.max(n,1));
            assert.deepEqual(a,b,'caller framing must not change the model windows');
            assert.equal(a.length,seconds===0?0:Math.max(1,Math.ceil(seconds-10)+1));
            a.forEach((w,i)=>{{assert.equal(w.startSample,i*16000);assert.equal(w.endSample,(i+10)*16000);
              assert.equal(w.realEndSample,Math.min(n,w.endSample));}});
          }}
        """)

    def test_frozen_identity_permutation_short_turn_and_overlap(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ CommunitySpeakerIdentity, communityTimeline }} from {(DIARIZATION/'CommunitySpeakerIdentity.ts').as_uri()!r};
          import {{ speakerIndexFromInternalId }} from {(DIARIZATION/'SpeakerDiarizationSpeakerIndex.ts').as_uri()!r};
          const ids=new CommunitySpeakerIdentity(3);
          assert.deepEqual(ids.assign([0,1,-2,0,1,-2],2,[200,100,0,200,100,0]).mapping,[0,1]);
          const mapped=ids.assign([1,0,-2,1,0,-2,2,-2,-2],3,[200,100,0,200,100,0,50,0,0]);
          assert.deepEqual(mapped.mapping,[1,0,2],'cluster renumbering cannot rename an established voice');
          const turns=communityTimeline([[0,1000,1],[400,450,0],[1000,1100,2]],mapped.mapping,0,1100);
          assert.deepEqual(turns.map(t=>[t.beginTime,t.endTime,t.speakerId,t.secondarySpeakerIds,t.overlap]),[
            [0,400,'S1',[],false],[400,450,'S1',['S2'],true],[450,1000,'S1',[],false],[1000,1100,'S3',[],false]]);
          assert.deepEqual(turns.map(t=>speakerIndexFromInternalId(t.speakerId)),[0,0,0,2]);
        """)

    def test_reclustering_does_not_forget_a_previously_published_identity(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ CommunitySpeakerIdentity }} from {(DIARIZATION/'CommunitySpeakerIdentity.ts').as_uri()!r};
          const ids=new CommunitySpeakerIdentity(2);
          assert.deepEqual(ids.assign([0,1],2,[200,100]).mapping,[0,1]);
          ids.assign([0,0,0],1,[200,100,20]);
          const restored=ids.assign([0,1,0,1],2,[200,100,20,50]);
          assert.deepEqual(restored.mapping,[0,1],
            'a temporary cluster merge cannot erase the already published second identity');
          assert.equal(restored.after,2);
        """)

    def test_unpublished_context_cannot_consume_a_public_role(self):
        run_community_session("""
          const s=session();s.totalSamples=11000*16;
          s.onWindow(window(0));s.onWindow(window(1));
          s.client.cluster=async()=>({...clusterResult(2),speakerCount:2,
            hard:[0,-2,-2,1,-2,-2],turns:[[0,4000,0],[6000,11000,1]]});
          const first=await s.commitWindow(5000,11000,false,0);
          assert.equal(first.speakerCount,1,'lookahead alone cannot reserve another public identity');
          const second=await s.commitWindow(11000,Infinity,true,5000);
          assert.equal(second.speakerCount,2);
          assert.ok(second.speakerTurns.every(t=>t.speakerIndex===1));
        """)

    def test_commit_snapshot_excludes_late_windows_and_does_not_rewrite_published_text(self):
        run_community_session("""
          const published=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult:r=>published.push(r),onFinished:r=>published.push(r)});
          s.totalSamples=13000*16;
          s.observeAsrFinal({result:'你好',beginTime:100,endTime:1000,isLast:false},
            {rawText:'你好',tokens:['你','好'],timestamps:[.1,.5],isLast:false,audioEndSample:16000});
          s.onWindow(window(0));s.onWindow(window(1));
          let resolve,observed;
          s.client.cluster=(segments,embeddings)=>{observed=[segments.slice(),embeddings.slice()];
            return new Promise(r=>resolve=r);};
          const first=s.commitWindow(5000,11000,false,0);
          s.onWindow(window(2));
          assert.equal(observed[0].length,2*589*3,'future audio cannot enter the queued commit');
          resolve(clusterResult(2));const committed=await first;
          assert.equal(committed.utterances.map(u=>u.text).join(''),'你好');
          assert.ok(committed.speakerTurns.every(t=>t.speakerIndex===0));
          const frozen=JSON.stringify(committed);
          s.client.cluster=async()=>clusterResult(3);
          await s.commitWindow(13000,Infinity,true,5000);
          assert.equal(JSON.stringify(committed),frozen);
          assert.equal(s.transcript.sentenceUtterances(13000).length,0,'committed words cannot be reissued');
        """)

    def test_cancel_during_async_final_cluster_emits_no_final(self):
        run_community_session("""
          const published=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult:r=>published.push(r),onFinished:r=>published.push(r)});
          s.totalSamples=160000;s.onWindow(window(0));
          let resolve;s.client.cluster=()=>new Promise(r=>resolve=r);
          s.finishRequested=true;s.processDrained=true;s.asrTailObserved=true;
          s.finalizeIfReady();s.cancel();resolve(clusterResult(1));
          await new Promise(r=>setImmediate(r));
          assert.deepEqual(published,[]);
          assert.equal(s.finalSpeakerCount,0,'cancelled cluster cannot mutate the identity registry');
          assert.equal(released,1);
        """)

    def test_cancel_from_update_stops_later_updates_and_publication(self):
        run_community_session("""
          const updates=[], finals=[];
          const s=new SpeakerDiarizationSession({},'',4,{
            onSpeakerDiarizationUpdate:u=>{updates.push(u);s.cancel();},
            onWindowResult:r=>finals.push(r),onFinished:r=>finals.push(r)});
          s.totalSamples=160000;
          for (let i=0;i<2;i++) s.observeAsrFinal({result:'你好',beginTime:i*1000,
            endTime:(i+1)*1000,isLast:false},{rawText:'你好',tokens:['你','好'],
            timestamps:[i,i+.5],isLast:false,audioEndSample:(i+1)*16000});
          s.onWindow(window(0));s.client.cluster=async()=>clusterResult(1);
          s.finishRequested=true;s.processDrained=true;s.asrTailObserved=true;
          s.finalizeIfReady();await new Promise(r=>setImmediate(r));
          assert.equal(updates.length,1,'cancel in the first callback closes the callback stream');
          assert.deepEqual(finals,[]);assert.equal(released,1);
        """)

    def test_finish_reentry_during_update_drains_once_after_intermediate_result(self):
        run_community_session("""
          const events=[];
          const s=new SpeakerDiarizationSession({},'',4,{
            onSpeakerDiarizationUpdate(){events.push('update');s.finish();s.onDrained();},
            onWindowResult:r=>events.push('window'),onFinished:r=>events.push('final')});
          s.totalSamples=130000*16;
          s.observeAsrFinal({result:'你好',beginTime:0,endTime:1000,isLast:false},
            {rawText:'你好',tokens:['你','好'],timestamps:[0,.5],isLast:false,audioEndSample:16000});
          s.asrTailObserved=true;
          s.onWindow(window(0));s.inferenceEndMs=130000;
          s.client.cluster=async()=>clusterResult(1);
          s.asrFinalDelivered({isLast:false,audioEndSample:120000*16});
          s.asrAudioProcessed(130000*16);
          await new Promise(r=>setImmediate(r));
          assert.deepEqual(events,['update','window','final']);
          s.finish();s.onDrained();await new Promise(r=>setImmediate(r));
          assert.deepEqual(events,['update','window','final']);
        """)

    def test_final_waits_for_both_drained_audio_and_asr_tail_and_is_unique(self):
        run_community_session("""
          const published=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult:r=>published.push(r),onFinished:r=>published.push(r)});
          s.totalSamples=160000;s.onWindow(window(0));
          let resolve;s.client.cluster=()=>new Promise(r=>resolve=r);
          s.finish();s.onDrained();
          assert.equal(resolve,undefined,'drained diarization cannot bypass the ASR tail');
          s.observeAsrFinal({result:'你好',beginTime:100,endTime:1000,isLast:true},
            {rawText:'你好',tokens:['你','好'],timestamps:[.1,.5],isLast:true,audioEndSample:160000});
          assert.equal(published.length,0,'do not publish before native clustering returns');
          resolve(clusterResult(1));await new Promise(r=>setImmediate(r));
          assert.equal(published.length,1);assert.equal(published[0].isSessionFinal,true);
          assert.equal(published[0].utterances.map(u=>u.text).join(''),'你好');
          s.finish();s.onDrained();s.finalizeIfReady();await new Promise(r=>setImmediate(r));
          assert.equal(published.length,1,'reentrant or duplicate finish must not republish');
        """)

    def test_client_retains_native_lease_until_delayed_cluster_is_quiescent(self):
        source=(DIARIZATION/'SpeakerDiarizationLocalClient.ets').read_text()
        source=source[source.index('export class SpeakerDiarizationStorageError'):]
        stubs="""
          import assert from 'node:assert/strict';
          const SAMPLE_RATE=16000,WINDOW_SAMPLES=160000,INFERENCE_TIMEOUT_MS=10000;
          let nextDiarizationJobId=1,closeCount=0,resolveCluster;
          class DiarizationWindowScheduler {}
          class DiarizationPcmSpool {close(){} remove(){}}
          class CommunityDiarizationInference {
            async load(){} close(){closeCount++;}
            cluster(){return new Promise(r=>resolveCluster=r);}
          }
          const fs={accessSync:()=>true,rmdirSync(){}};
        """
        body="""
          const c=new SpeakerDiarizationLocalClient({},'',{onDegraded(){},onDrained(){}});
          const pending=c.cluster(new Float32Array(1),new Float32Array(1),4);
          await new Promise(r=>setImmediate(r));
          function session() {return new SpeakerDiarizationSession({},'',4,{
        onSpeakerDiarizationUpdate(){},onWindowResult(){},onFinished(){}});}
      let released=0;c.cancel(()=>released++);
          assert.equal(closeCount,0);assert.equal(released,0);
          resolveCluster({});await pending;
          assert.equal(closeCount,1);assert.equal(released,1);
        """
        with tempfile.TemporaryDirectory() as directory:
            harness=Path(directory)/'client.mts'
            harness.write_text(stubs+source+body)
            subprocess.run(['node','--experimental-strip-types',str(harness)],check=True,cwd=ROOT)
