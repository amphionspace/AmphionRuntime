"""Public behavior at the Community tensor/cluster boundary.

The ERes/CAMP session profile/query seam no longer exists. These tests inject
model outputs, not reference audio: acoustic accuracy has a separate real-audio
gate. Existing registry, query, transcript and native component tests remain.
"""
import unittest
from asr.tools.tests.test_harmony_community_diarization import run_community_session


class HarmonyCommunityPublicContractTest(unittest.TestCase):

    def test_short_first_voice_and_later_interjection_are_not_duration_filtered(self):
        run_community_session("""
          const s=session();s.totalSamples=16000*12;
          for(let i=0;i<3;i++)s.onWindow(window(i));
          s.client.cluster=async()=>({speakerCount:3,hard:[0,-2,-2,1,-2,-2,2,-2,-2],
            turns:[[0,100,0],[100,5000,1],[5000,5050,2],[5050,12000,1]]});
          const out=await s.commitWindow(12000,Infinity,true,0);
          assert.equal(out.speakerCount,3);
          assert.deepEqual(out.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex]),
            [[0,100,0],[100,5000,1],[5000,5050,2],[5050,12000,1]]);
        """)

    def test_repeated_same_voice_does_not_consume_new_roles(self):
        run_community_session("""
          const s=session();s.totalSamples=16000*12;
          for(let i=0;i<3;i++)s.onWindow(window(i));
          s.client.cluster=async()=>({...clusterResult(3),turns:[[0,200,0],[2000,2200,0],[5000,12000,0]]});
          const out=await s.commitWindow(12000,Infinity,true,0);
          assert.equal(out.speakerCount,1);
          assert.ok(out.speakerTurns.every(t=>t.speakerIndex===0));
          assert.equal(out.speakerTurns.length,3,'silent gaps are retained');
        """)

    def test_later_cluster_permutation_keeps_public_ids_and_frozen_words(self):
        run_community_session("""
          const s=session();s.totalSamples=16000*13;
          for(let i=0;i<4;i++)s.onWindow(window(i));
          s.observeAsrFinal({result:'你好',beginTime:0,endTime:4000,isLast:false},
            {rawText:'你好',tokens:['你','好'],timestamps:[0,2],isLast:false,audioEndSample:64000});
          s.client.cluster=async()=>({speakerCount:2,hard:[0,-2,-2,1,-2,-2,0,-2,-2,1,-2,-2],
            turns:[[0,4000,0],[4000,6500,1],[6500,9000,0],[9000,13000,1]]});
          const first=await s.commitWindow(6500,Infinity,false,0),frozen=JSON.stringify(first);
          s.client.cluster=async()=>({speakerCount:2,hard:[1,-2,-2,0,-2,-2,1,-2,-2,0,-2,-2],
            turns:[[0,4000,1],[4000,6500,0],[6500,9000,1],[9000,13000,0]]});
          const next=await s.commitWindow(13000,Infinity,true,6500);
          assert.equal(JSON.stringify(first),frozen);
          assert.deepEqual(next.speakerTurns.map(t=>t.speakerIndex),[0,1]);
          assert.equal(next.speakerCount,2);assert.deepEqual(next.utterances,[]);
        """)

    def test_partial_run_is_clipped_at_commit_without_losing_the_remainder(self):
        run_community_session("""
          const s=session();s.totalSamples=16000*10;s.onWindow(window(0));
          s.client.cluster=async()=>({...clusterResult(1),turns:[[1000,8000,0]]});
          const first=await s.commitWindow(5000,Infinity,false,0);
          const next=await s.commitWindow(10000,Infinity,true,5000);
          assert.deepEqual(first.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex]),[[1000,5000,0]]);
          assert.deepEqual(next.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex]),[[5000,8000,0]]);
          assert.equal(next.speakerCount,1);
        """)

    def test_known_overlap_is_retained_without_splitting_complete_words(self):
        run_community_session("""
          const s=session();s.totalSamples=16000*11;s.onWindow(window(0));s.onWindow(window(1));
          s.observeAsrFinal({result:'张三你好',beginTime:100,endTime:2000,isLast:false},
            {rawText:'张三你好',tokens:['张','三','你','好'],timestamps:[.1,.3,.8,1.2],isLast:false,audioEndSample:32000});
          s.client.cluster=async()=>({speakerCount:2,hard:[0,-2,-2,1,-2,-2],
            turns:[[0,11000,0],[400,450,1]]});
          const out=await s.commitWindow(11000,Infinity,true,0);
          const overlap=out.speakerTurns.find(t=>t.overlap);
          assert.ok(overlap);assert.equal(overlap.beginTime,400);assert.equal(overlap.endTime,450);
          assert.deepEqual(overlap.secondarySpeakerIndexes,[1]);
          assert.equal(out.utterances.map(u=>u.text).join(''),'张三你好');
          assert.equal(out.utterances.length,1,'secondary-only changes cannot fragment the primary sentence');
        """)

    def test_multiple_unknown_tracks_keep_uncertainty_and_overlap(self):
        run_community_session("""
          const turns=communityTimeline([[0,1000,0],[400,450,1]],[-1,-1],0,1000);
          assert.ok(turns.every(t=>t.speakerId==='UNKNOWN'));
          assert.deepEqual(turns.map(t=>[t.beginTime,t.endTime,t.overlap]),
            [[0,400,false],[400,450,true],[450,1000,false]]);
          const s=session();s.totalSamples=16000;s.transcript.applySpeakerTurns(turns);
          const out=s.bestResult();
          assert.ok(out.speakerTurns.every(t=>t.speakerIndex===-1));
          assert.equal(out.speakerCount,0);
        """)

    def test_unenrolled_overlap_keeps_known_role_and_readable_sentence(self):
        run_community_session("""
          const s=session();s.totalSamples=160000;s.onWindow(window(0));
          s.observeAsrFinal({result:'张三你好',beginTime:100,endTime:2000,isLast:false},
            {rawText:'张三你好',tokens:['张','三','你','好'],timestamps:[.1,.3,.8,1.2],isLast:false,audioEndSample:32000});
          s.client.cluster=async()=>({...clusterResult(1),hard:[0,-2,-2],
            turns:[[0,10000,0],[400,450,-1]]});
          const out=await s.commitWindow(10000,Infinity,true,0);
          assert.equal(out.speakerCount,1,'anonymous overlap cannot reserve a role');
          assert.ok(out.speakerTurns.every(t=>t.speakerIndex===0));
          const overlap=out.speakerTurns.find(t=>t.overlap);
          assert.ok(overlap);assert.deepEqual(overlap.secondarySpeakerIndexes,[-1]);
          assert.equal(overlap.beginTime,400);assert.equal(overlap.endTime,450);
          assert.equal(out.utterances.length,1);
          assert.equal(out.utterances[0].text,'张三你好');
        """)

    def test_no_enrollment_does_not_consume_a_role_or_rewrite_frozen_unknown(self):
        run_community_session("""
          const s=session();s.totalSamples=16000;s.onWindow(window(0));
          s.client.cluster=async()=>({speakerCount:0,hard:[-2,-2,-2],centroids:[],
            turns:[[0,1000,-1],[400,450,-1]]});
          const first=await s.commitWindow(1000,Infinity,false,0);
          assert.equal(first.speakerCount,0);
          assert.deepEqual(first.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex,t.overlap]),
            [[0,400,-1,false],[400,450,-1,true],[450,1000,-1,false]]);
          const frozen=JSON.stringify(first);
          s.totalSamples=16000*12;s.onWindow(window(1));
          s.client.cluster=async()=>({speakerCount:1,hard:[0,-2,-2,0,-2,-2],centroids:[[1,0]],
            turns:[[0,12000,0]]});
          const next=await s.commitWindow(12000,Infinity,true,1000);
          assert.equal(next.speakerCount,1);
          assert.ok(next.speakerTurns.every(t=>t.speakerIndex===0));
          assert.equal(JSON.stringify(first),frozen,'new identity evidence cannot relabel committed UNKNOWN');
        """)

    def test_diagnostics_report_actual_evidence_and_do_not_change_public_results(self):
        run_community_session("""
          let clockMs=1000;Date.now=()=>clockMs;
          async function replay(diagnostic) {
            const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
              onWindowResult(){},onFinished(){}},diagnostic);
            s.totalSamples=16000*10;s.onWindow(window(0));s.client.cluster=async()=>{clockMs+=5;return clusterResult(1);};
            return await s.commitWindow(10000,Infinity,true,0);
          }
          const events=[],plain=await replay(undefined);
          assert.deepEqual(await replay((event,fields)=>events.push({event,fields})),plain);
          const w=events.find(e=>e.event==='DIARIZATION_COMMUNITY_WINDOW').fields;
          assert.equal(w.jobId,'w0');assert.equal(w.windowStartSample,0);assert.equal(w.realEndSample,160000);
          const c=events.find(e=>e.event==='DIARIZATION_COMMUNITY_COMMIT').fields;
          assert.deepEqual(c.jobIds,['w0']);assert.deepEqual(c.clusterToFrozenId,[0]);
          assert.equal(c.registryBefore,0);assert.equal(c.registryAfter,1);
          assert.deepEqual(events.find(e=>e.event==='DIARIZATION_PUBLIC_RESULT').fields.speakerTurns,plain.speakerTurns);
          assert.deepEqual(await replay(()=>{throw new Error('sink unavailable')}),plain);
        """)

    def test_diagnostic_tensor_snapshots_are_isolated_from_model_and_later_windows(self):
        run_community_session("""
          const events=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult(){},onFinished(){}},(event,fields)=>events.push({event,fields}));
          const first=window(0);first.result.embeddings[0]=Math.fround(1/3);
          s.totalSamples=176000;s.onWindow(first);
          const captured=events.find(e=>e.event==='DIARIZATION_COMMUNITY_WINDOW').fields;
          first.result.embeddings[0]=7;
          assert.equal(captured.embeddings[0],Math.fround(1/3),'captured scores cannot change after recording');
          captured.segmentations[0]=99;
          const next=window(1);s.onWindow(next);
          s.client.cluster=async(segments,embeddings)=>{
            assert.equal(segments[0],1,'diagnostic consumers cannot mutate model input');
            assert.equal(segments[589*3],1,'later windows keep independent PCM ownership');
            assert.equal(embeddings[0],7);
            assert.equal(embeddings[3*256],0);
            return clusterResult(2);
          };
          await s.commitWindow(11000,Infinity,true,0);
          assert.equal(captured.embeddings[0],Math.fround(1/3));
        """)

    def test_finish_tail_and_drain_orders_have_the_same_unique_result(self):
        run_community_session("""
          Date.now=()=>1000;
          let expected;
          for(const order of [['finish','drain','tail'],['tail','finish','drain'],['finish','tail','drain']]) {
            const outputs=[];
            const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
              onWindowResult(){},onFinished:r=>outputs.push(r)});
            s.totalSamples=160000;s.onWindow(window(0));s.client.cluster=async()=>clusterResult(1);
            const actions={finish:()=>s.finish(),drain:()=>s.onDrained(),tail:()=>s.observeAsrFinal(
              {result:'你好',beginTime:0,endTime:1000,isLast:true},
              {rawText:'你好',tokens:['你','好'],timestamps:[0,.5],isLast:true,audioEndSample:160000})};
            for(const action of order){actions[action]();await new Promise(r=>setImmediate(r));}
            assert.equal(outputs.length,1);assert.equal(outputs[0].isSessionFinal,true);
            const visible={words:outputs[0].utterances,turns:outputs[0].speakerTurns,count:outputs[0].speakerCount};
            if(expected)assert.deepEqual(visible,expected);else expected=visible;
            s.finish();s.onDrained();await new Promise(r=>setImmediate(r));assert.equal(outputs.length,1);
          }
        """)

    def test_confirmed_initial_silence_does_not_wait_for_padded_model_tail(self):
        run_community_session("""
          for(const tailFirst of [false,true]) {
            const outputs=[];
            const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){assert.fail('no speech update');},
              onWindowResult(){assert.fail('no speech window');},onFinished:r=>outputs.push(r)});
            s.totalSamples=16000;let closeCalls=0,releaseNative;
            s.client.finish=()=>{}; // Hold the model completion past the decided silence deadline.
            s.client.cancel=cb=>{closeCalls++;releaseNative=cb;};
            const tail=()=>s.observeAsrFinal({result:'',isLast:true},{isLast:true,timestamps:[],tokens:[]});
            if(tailFirst)tail();
            const leasesBefore=released;
            s.finish(true);
            await new Promise(r=>setImmediate(r));
            if(!tailFirst){assert.equal(outputs.length,0,'must still wait for the ASR tail');tail();}
            await new Promise(r=>setImmediate(r));
            assert.equal(outputs.length,1);assert.equal(outputs[0].speakerCount,0);
            assert.deepEqual(outputs[0].speakerTurns,[]);assert.equal(outputs[0].degraded,false);
            assert.equal(closeCalls,1);assert.equal(released,leasesBefore,'native work still owns its lease');
            s.onWindow(window(0));s.onDrained();s.finish(true);
            await new Promise(r=>setImmediate(r));assert.equal(outputs.length,1);
            releaseNative();assert.equal(released,leasesBefore+1);
          }
        """)

    def test_empty_asr_tail_preserves_acoustic_results_and_normal_finalization(self):
        run_community_session("""
          const outputs=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult(){},onFinished:r=>outputs.push(r)});
          s.totalSamples=160000;s.onWindow(window(0));s.client.cluster=async()=>clusterResult(1);
          s.finish();s.onDrained();s.observeAsrFinal({result:'',isLast:true},{isLast:true,timestamps:[],tokens:[]});
          await new Promise(r=>setImmediate(r));
          assert.equal(outputs.length,1);assert.equal(outputs[0].speakerCount,1);
          assert.ok(outputs[0].speakerTurns.length>0);assert.deepEqual(outputs[0].utterances,[]);
        """)

    def test_late_old_session_window_cannot_mutate_the_replacement(self):
        run_community_session("""
          const old=session(),next=session();old.totalSamples=160000;next.totalSamples=160000;
          old.onWindow(window(0));let resolve;old.client.cluster=()=>new Promise(r=>resolve=r);
          old.finishRequested=true;old.processDrained=true;old.asrTailObserved=true;old.finalizeIfReady();
          old.cleanup();next.onWindow(window(0));next.client.cluster=async()=>clusterResult(1);
          const out=await next.commitWindow(10000,Infinity,true,0),frozen=JSON.stringify(out);
          old.onWindow(window(1));resolve(clusterResult(1));await new Promise(r=>setImmediate(r));
          assert.equal(old.windows.length,1);assert.equal(old.finalSpeakerCount,0);
          assert.equal(next.finalSpeakerCount,1);assert.equal(JSON.stringify(out),frozen);
        """)

    def test_native_clustering_failure_degrades_once_without_losing_asr_words(self):
        run_community_session("""
          const outputs=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult(){},onFinished:r=>outputs.push(r)});
          s.totalSamples=160000;s.onWindow(window(0));s.client.cluster=async()=>{throw new Error('native failed')};
          s.finish();s.onDrained();s.observeAsrFinal({result:'你好',beginTime:0,endTime:1000,isLast:true},
            {rawText:'你好',tokens:['你','好'],timestamps:[0,.5],isLast:true,audioEndSample:160000});
          await new Promise(r=>setImmediate(r));
          assert.equal(outputs.length,1);assert.equal(outputs[0].degraded,true);
          assert.equal(outputs[0].utterances.map(u=>u.text).join(''),'你好');
          assert.equal(outputs[0].speakerCount,0);assert.equal(outputs[0].isSessionFinal,true);
          s.onDrained();s.finish();await new Promise(r=>setImmediate(r));assert.equal(outputs.length,1);
        """)
