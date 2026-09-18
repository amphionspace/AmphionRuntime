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
    def test_later_loud_voice_does_not_erase_an_independently_admitted_new_person(self):
        run_session("""
          const s=session(); let start=0;
          const cases=[[[1,0,0,0],.1,6000],[[0,1,0,0],.06,6000],
            [[1,0,0,0],.06,6000],[[0,0,1,0],.15,6000],[[0,0,0,1],.02,6000]];
          cases.forEach(([embedding,rms,ms],i)=>{
            const count=ms*16;
            s.onWindow({jobId:`w${i}`,windowStartSample:start,contentStartInWindowSample:0,
              realEndSample:start+count,commitStartSample:start,stableEndSample:start+count,
              finalWindow:false,result:{inferenceMs:0,
                segments:[{startSample:0,endSample:count,speaker:0,speakerMask:1,queryEmbedding:embedding}],
                embeddings:[{localSpeaker:0,speechSamples:count,speechRms:rms,embedding,queryEmbedding:embedding}]}});
            start+=count;
          });
          s.totalSamples=start;const result=s.commitWindow(start/16,Infinity,true);
          const ids=result.speakerTurns.map(t=>t.speakerIndex);
          assert.ok(ids[1]>=0,'a later louder person must not erase an independently admitted new voice');
          assert.equal(new Set([ids[0],ids[1],ids[3]]).size,3);
          assert.equal(result.speakerCount,3);
          assert.equal(ids[2],-1,'novel admission must not broaden existing quiet identity recovery');
          assert.equal(ids[4],-1,'speech that never passed the level gate must not enroll');
        """)

    def test_historical_admission_still_requires_unique_speech_and_available_capacity(self):
        run_session("""
          function run(ms,capacity) {
            const s=new SpeakerDiarizationSession({},'',capacity,{
              onSpeakerDiarizationUpdate(){},onWindowResult(){},onFinished(){}});
            let start=0;
            const cases=[[[1,0,0],.1,6000],...Array.from({length:4},()=>[[0,1,0],.06,ms]),[[0,0,1],.15,6000]];
            cases.forEach(([embedding,rms,duration],i)=>{
              const count=duration*16;
              s.onWindow({jobId:`w${i}`,windowStartSample:start,contentStartInWindowSample:0,
                realEndSample:start+count,commitStartSample:start,stableEndSample:start+count,
                finalWindow:false,result:{inferenceMs:0,
                  segments:[{startSample:0,endSample:count,speaker:0,speakerMask:1,queryEmbedding:embedding}],
                  embeddings:[{localSpeaker:0,speechSamples:count,speechRms:rms,embedding,queryEmbedding:embedding}]}});
              start+=count;
            });
            s.totalSamples=start;return s.commitWindow(start/16,Infinity,true);
          }
          const short=run(2999,4);
          assert.equal(short.speakerCount,2);
          assert.ok(short.speakerTurns.slice(1,-1).every(t=>t.speakerIndex<0),
            'summed short observations cannot qualify an additional person');
          const full=run(6000,2);
          assert.equal(full.speakerCount,2);
          assert.ok(full.speakerTurns.slice(1,-1).every(t=>t.speakerIndex<0),
            'historical admission cannot evict existing identities at capacity');
        """)

    def test_historical_admission_uses_a_previous_committed_foreground_reference(self):
        run_session("""
          const s=session();let start=0;
          function add(embedding,rms,id) {
            s.onWindow({jobId:id,windowStartSample:start,contentStartInWindowSample:0,
              realEndSample:start+96000,commitStartSample:start,stableEndSample:start+96000,
              finalWindow:false,result:{inferenceMs:0,
                segments:[{startSample:0,endSample:96000,speaker:0,speakerMask:1,queryEmbedding:embedding}],
                embeddings:[{localSpeaker:0,speechSamples:96000,speechRms:rms,embedding,queryEmbedding:embedding}]}});
            start+=96000;s.totalSamples=start;
          }
          add([1,0,0],.1,'first');
          const first=s.commitWindow(6000,Infinity,false,0), frozen=JSON.stringify(first);
          add([0,1,0],.06,'second');add([0,0,1],.15,'louder');
          const second=s.commitWindow(18000,Infinity,true,6000);
          assert.equal(JSON.stringify(first),frozen,'the previously committed window stays frozen');
          assert.equal(second.speakerCount,3);
          assert.ok(second.speakerTurns.every(t=>t.speakerIndex>=0));
          assert.notEqual(second.speakerTurns[0].speakerIndex,second.speakerTurns[1].speakerIndex);
        """)

    def test_fixed_original_references_recover_a_diluted_centroid_without_cross_matching(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const v=d=>[Math.cos(d*Math.PI/180),Math.sin(d*Math.PI/180)];
          const r=new OnlineSpeakerRegistry();
          r.assign(new Float32Array([1,0]),6000,0);
          r.assign(new Float32Array([-1,0]),6000,0);
          r.bindComplementaryProfile('S1',[v(-40),v(40)],[3000,3000]);
          r.bindComplementaryProfile('S2',[v(180)],[3000]);
          const p=v(60), ids=new Set(['S1','S2']);
          const match=(q=v(60),c=v(60))=>r.matchComplementaryQuery(p,p,q,c,ids);
          assert.equal(match()?.speakerId,'S1','averaging loses a supported original reference');
          assert.equal(match(v(60),v(-60)),undefined,'context and query cannot use conflicting references');
          assert.equal(match(v(88),v(88)),undefined,'reference matching requires its own higher threshold');
          assert.equal(r.fork().matchComplementaryQuery(p,p,v(60),v(60),ids)?.speakerId,'S1');
          r.bindComplementaryProfile('S1',[v(120)],[6000]);
          assert.equal(match(v(120),v(120)),undefined,'later references cannot extend the profile');
          const bounded=new OnlineSpeakerRegistry();bounded.assign(new Float32Array([1,0]),6000,0);
          bounded.bindComplementaryProfile('S1',[...Array.from({{length:8}},()=>v(0)),v(90)],Array(9).fill(1000));
          assert.equal(bounded.matchComplementaryQuery(p,p,v(90),v(90),new Set(['S1'])),undefined,
            'only the independently calibrated maximum of eight references is eligible');
        """)

    def test_complementary_recovery_preserves_known_roles_and_quiet_exclusion(self):
        run_session("""
          const vector=d=>[Math.cos(d*Math.PI/180),Math.sin(d*Math.PI/180)];
          function run(available) {
            const s=session();let start=0;
            const cases=[[0,0,6000,.1],[180,180,6000,.1],[60,45,1300,.1],
              [60,45,1300,.01],[180,0,1300,.1]];
            cases.forEach(([primary,secondary,ms,rms],i)=>{
              const count=ms*16;
              s.onWindow({jobId:`w${i}`,windowStartSample:start,contentStartInWindowSample:0,
                realEndSample:start+count,commitStartSample:start,stableEndSample:start+count,
                finalWindow:false,result:{inferenceMs:0,
                  segments:[{startSample:0,endSample:count,speaker:0,speakerMask:1,
                    queryEmbedding:vector(primary),complementaryEmbedding:available?vector(secondary):undefined}],
                  embeddings:[{localSpeaker:0,speechSamples:count,speechRms:rms,embedding:vector(primary),
                    queryEmbedding:vector(primary),complementaryEmbedding:available?vector(secondary):undefined}]}});
              start+=count;
            });
            s.totalSamples=start;return s.commitWindow(start/16,Infinity,true);
          }
          const baseline=run(false), supplemented=run(true);
          const [first,second]=baseline.speakerTurns.map(t=>t.speakerIndex);
          assert.ok(first>=0 && second>=0 && first!==second);
          assert.deepEqual(baseline.speakerTurns.map(t=>t.speakerIndex),[first,second,-1,-1,second]);
          assert.deepEqual(supplemented.speakerTurns.map(t=>t.speakerIndex),[first,second,first,-1,second]);
          assert.equal(supplemented.speakerCount,2,'complementary evidence cannot enroll another person');
        """)

    def test_complementary_profile_is_fixed_and_both_models_must_agree(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const r=new OnlineSpeakerRegistry();
          r.assign(new Float32Array([1,0]),6000,0);
          r.assign(new Float32Array([-1,0]),6000,0);
          const weak=[.52,Math.sqrt(1-.52**2)], strong=[.7,Math.sqrt(1-.7**2)];
          const ids=new Set(['S1','S2']);
          const match=(p=weak,c=weak,q=strong,x=strong)=>r.matchComplementaryQuery(p,c,q,x,ids);
          assert.equal(match(),undefined,'missing complementary model must not fabricate identity');
          r.bindComplementaryProfile('S1',[[1,0],[1,0]],[1000,2000]);
          r.bindComplementaryProfile('S2',[[-1,0]],[3000]);
          assert.equal(r.matchQuery(weak,ids),undefined);
          const before=JSON.stringify(r.snapshot());
          assert.equal(match()?.speakerId,'S1');
          assert.equal(r.fork().matchComplementaryQuery(weak,weak,strong,strong,ids)?.speakerId,'S1');
          assert.equal(match(weak,[-1,0]),undefined,'primary context disagreement');
          assert.equal(match(weak,weak,[-1,0],[-1,0]),undefined,'models disagree');
          assert.equal(match(weak,weak,[.63,Math.sqrt(1-.63**2)]),undefined,'independent threshold');
          assert.equal(match([0,1],[0,1]),undefined,'primary candidate is ambiguous');
          assert.equal(r.matchComplementaryQuery(weak,weak,strong,strong,new Set()),undefined);
          r.bindComplementaryProfile('S1',[[-1,0]],[3000]);
          assert.equal(match()?.speakerId,'S1','later evidence cannot overwrite the reference');
          assert.equal(JSON.stringify(r.snapshot()),before,'complementary matching cannot update primary identities');
        """)

    def test_leading_initial_short_voice_keeps_first_identity_eligibility(self):
        run_session("""
          const s=session(); s.totalSamples=224000;
          const windows=[0,1,2,3].map(i=>({start:0,end:2900,embedding:[1,0],owned:i===0}));
          windows.push({start:7000,end:13000,embedding:[0,1],owned:true});
          windows.forEach((w,i)=>s.onWindow({jobId:`w${i}`,windowStartSample:0,
            contentStartInWindowSample:0,realEndSample:224000,
            commitStartSample:w.owned ? 0 : 176000,stableEndSample:224000,
            finalWindow:false,result:{inferenceMs:0,
              segments:[{startSample:w.start*16,endSample:w.end*16,speaker:0,speakerMask:1}],
              embeddings:[{localSpeaker:0,speechRms:.1,speechSamples:(w.end-w.start)*16,
                embedding:w.embedding,queryEmbedding:w.owned ? w.embedding : undefined}]}}));
          const result=s.commitWindow(14000,Infinity,true);
          assert.equal(result.speakerCount,2,'initial voice must not lose its first-role eligibility to a later long voice');
          assert.deepEqual(result.speakerTurns.map(t=>t.speakerIndex),[0,1]);
        """)

    def test_quiet_independent_context_prevents_duplicate_without_enrolling_quiet_speech(self):
        run_session("""
          const vector=degrees=>[Math.cos(degrees*Math.PI/180),Math.sin(degrees*Math.PI/180)];
          function run(ownedDegrees) {
            const s=session();s.totalSamples=480000;
            const cases=[[0,0,.1],[50,35,.04],[80,ownedDegrees,.1],[180,180,.04],[80,ownedDegrees,.04]];
            cases.forEach(([context,query,rms],i)=>s.onWindow({
              jobId:`w${i}`,windowStartSample:i*96000,contentStartInWindowSample:0,
              realEndSample:(i+1)*96000,commitStartSample:i*96000,
              stableEndSample:(i+1)*96000,finalWindow:false,result:{inferenceMs:0,
                segments:[{startSample:0,endSample:96000,speaker:0,speakerMask:1,queryEmbedding:vector(query)}],
                embeddings:[{localSpeaker:0,speechSamples:96000,speechRms:rms,
                  embedding:vector(context),queryEmbedding:vector(query)}]}}));
            return s.commitWindow(30000,Infinity,true);
          }
          const supported=run(90);
          assert.equal(supported.speakerCount,1,'independent context must prevent duplicate enrollment');
          assert.deepEqual(supported.speakerTurns.map(t=>t.speakerIndex),[0,-1,0,-1,0],
            'quiet support alone cannot label output; a strong established alternative can recover its own speech');
          const different=run(180);
          assert.equal(different.speakerCount,2,'contradicting owned speech must remain a distinct person');
          assert.deepEqual(different.speakerTurns.map(t=>t.speakerIndex),[0,-1,1,-1,-1]);
        """)

    def test_quiet_output_requires_strong_existing_alternative_support(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const v=d=>[Math.cos(d*Math.PI/180),Math.sin(d*Math.PI/180)];
          const r=new OnlineSpeakerRegistry();
          r.assign(new Float32Array(v(0)),6000,0);
          assert.equal(r.matchQuietQuery?.(v(80),v(80),new Set(['S1'])),undefined);
          r.assign(new Float32Array(v(80)),6000,10000,true,[v(90)],
            [{{embedding:v(50),queryEmbedding:v(35)}}]);
          const before=JSON.stringify(r.snapshot());
          assert.equal(r.matchQuietQuery?.(v(80),v(80),new Set(['S1']))?.speakerId,'S1');
          assert.equal(r.fork().matchQuietQuery?.(v(80),v(80),new Set(['S1']))?.speakerId,'S1');
          assert.equal(r.matchQuietQuery?.(v(35),v(50),new Set(['S1'])),undefined,
            'weaker identity support alone must not authorize quiet output');
          assert.equal(r.matchQuietQuery?.(v(180),v(80),new Set(['S1'])),undefined);
          assert.equal(r.matchQuietQuery?.(v(80),v(80),new Set()),undefined);
          assert.equal(JSON.stringify(r.snapshot()),before,'queries cannot update or enroll profiles');
        """)

    def test_independent_known_query_prevents_duplicate_enrollment_without_chaining(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const first=[1,0,0,0], changed=[.55,Math.sqrt(1-.55**2),0,0];
          const y=(.64-.55*.64)/changed[1];
          const bridge=[.64,y,Math.sqrt(1-.64**2-y*y),0];
          const support=[{{embedding:bridge,queryEmbedding:bridge}}];
          function registry() {{
            const r=new OnlineSpeakerRegistry();
            r.assign(new Float32Array(first),6000,0);
            return r;
          }}
          const r=registry();
          assert.equal(r.assign(new Float32Array(changed),3200,10000,true,
            [changed],support).speakerId,'S1',
            'an independently recognized voice must not occupy a second role');
          assert.deepEqual(r.speakerIds(),['S1']);
          assert.equal(r.matchQuery(changed,new Set(['S1'])).speakerId,'S1');
          assert.equal(r.fork().matchQuery(changed,new Set(['S1'])).speakerId,'S1');
          assert.equal(r.matchKnown(changed),undefined,
            'an alternative query reference must not become a primary enrollment anchor');
          assert.equal(r.matchQuery(changed,new Set()),undefined);
          assert.equal(registry().assign(new Float32Array(changed),3200,10000,true,
            [changed],[]).speakerId,'S2','do not merge a different voice without independent support');
          const inconsistent=registry();
          inconsistent.assign(new Float32Array([0,0,0,1]),6000,0);
          assert.equal(inconsistent.assign(new Float32Array(changed),3200,10000,true,
            [changed],[{{embedding:[0,0,0,1],queryEmbedding:bridge}}]).speakerId,'S3',
            'context and owned query must independently agree');
          const again=[.1,.7,Math.sqrt(.5),0];
          assert.equal(r.assign(new Float32Array(again),3200,20000,true,[again]).speakerId,'S1');
          const next=[0,.45,Math.sqrt(1-.45**2),0];
          assert.equal(r.assign(new Float32Array(next),3200,30000,true,
            [next],[{{embedding:again,queryEmbedding:again}}]).speakerId,'S2',
            'a corrected alternative must not recursively qualify more alternatives');
        """)

    def test_independent_output_queries_can_confirm_an_ambiguous_context_cluster(self):
        run_session("""
          function run(queryCount, query) {
            const s=session(); s.totalSamples=320000;
            const context=[.61,Math.sqrt(1-.61**2)];
            for(let i=0;i<4;i++) {
              const embedding=i<2?[1,0]:context;
              const begin=i*5000, end=begin+5000;
              s.onWindow({jobId:`w${i}`,windowStartSample:begin*16,contentStartInWindowSample:0,
                realEndSample:end*16,commitStartSample:begin*16,stableEndSample:end*16,
                finalWindow:false,result:{inferenceMs:0,
                  segments:[{startSample:0,endSample:80000,speaker:0,speakerMask:1}],
                  embeddings:[{localSpeaker:0,speechRms:.1,speechSamples:i<2?80000:64000,
                    embedding,queryEmbedding:i<2?[1,0]:(i-2<queryCount?query:undefined)}]}});
            }
            return s.commitWindow(20000,Infinity,true);
          }
          const distinct=[.45,Math.sqrt(1-.45**2)];
          const result=run(2,distinct);
          assert.equal(result.speakerCount,2,'a supported second voice must not disappear at finalization');
          assert.deepEqual(result.speakerTurns.map(t=>t.speakerIndex),[0,0,1,1]);
          assert.equal(run(1,distinct).speakerCount,1,'one short query cannot prove a new identity');
          assert.equal(run(2,[1,0]).speakerCount,1,'queries matching an existing person cannot create a duplicate');
        """)

    def test_separate_runs_on_one_local_channel_keep_their_own_query_and_commit_boundary(self):
        run_session("""
          const s=session();s.totalSamples=160000;
          s.committedRegistry.assignBatch([new Float32Array([1,0]),new Float32Array([0,1])],
            [6000,6000],0);
          s.publishedSpeakerIds.add('S1');s.publishedSpeakerIds.add('S2');
          s.registry=s.committedRegistry.fork();
          s.onWindow({jobId:'mixed-channel',windowStartSample:0,contentStartInWindowSample:0,
            realEndSample:160000,commitStartSample:0,stableEndSample:160000,finalWindow:true,
            result:{inferenceMs:0,segments:[
              {startSample:0,endSample:32000,speaker:0,speakerMask:1,queryEmbedding:[1,0]},
              {startSample:64000,endSample:96000,speaker:0,speakerMask:1,queryEmbedding:[0,1]}],
              embeddings:[{localSpeaker:0,speechRms:.1,speechSamples:64000,
                embedding:[1,0],queryEmbedding:[1,0]}]}});
          const first=s.commitWindow(3000,10000,false,0);
          const frozen=JSON.stringify(first);
          const second=s.commitWindow(10000,Infinity,true,3000);
          assert.deepEqual(first.speakerTurns.map(t=>t.speakerIndex),[0]);
          assert.deepEqual(second.speakerTurns.map(t=>t.speakerIndex),[1],
            'another run on the same local channel must not inherit historical identity');
          assert.equal(JSON.stringify(first),frozen);
          assert.equal(s.committedRegistry.speakerIds().length,2,'run queries never enroll identities');
        """)

    def test_context_only_candidate_leaves_capacity_for_a_supported_fourth_speaker(self):
        run_session("""
          const s=session(); s.totalSamples=160000;
          const vector=index=>Array.from({length:5},(_,i)=>i===index?1:0);
          s.committedRegistry.assignBatch([0,1,2].map(i=>new Float32Array(vector(i))),
            [6000,6000,6000],0);
          s.registry=s.committedRegistry.fork();
          function window(id,begin,end,contextBegin,index,hasQuery) {
            s.onWindow({jobId:id,windowStartSample:0,contentStartInWindowSample:0,
              realEndSample:160000,commitStartSample:begin*16,stableEndSample:end*16,
              finalWindow:false,result:{inferenceMs:0,segments:[{
                startSample:contextBegin*16,endSample:end*16,speaker:0,speakerMask:1}],
                embeddings:[{localSpeaker:0,speechRms:0.1,speechSamples:(end-contextBegin)*16,
                  embedding:vector(index),queryEmbedding:hasQuery?vector(index):undefined}]}});
          }
          // The longer historical mixture is considered before the genuine new voice.
          window('mixed-context',4000,4600,1000,3,false);
          window('fourth-person',4600,7800,4600,4,true);
          const result=s.commitWindow(10000,Infinity,true);
          assert.deepEqual(result.speakerTurns.map(t=>t.speakerIndex),[-1,3],
            'rejecting a context-only role must preserve capacity for a real fourth speaker');
          assert.equal(result.speakerCount,4);
          assert.deepEqual(s.committedRegistry.speakerIds(),['S1','S2','S3','S4']);
        """)

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
                embeddings:[{localSpeaker:0,speechRms:0.1,speechSamples:(end-contextBegin)*16,
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
          function run(embedding, speechMs, seedMs=6000, speechSamples=speechMs*16) {
            const s=session(); s.totalSamples=224000;
            const windows=[{start:0,end:seedMs,embedding:[1,0]}];
            for(let i=0;i<4;i++) windows.push({start:7000,end:7000+speechSamples/16,embedding});
            for(let i=0;i<windows.length;i++) {
              const w=windows[i];
              s.onWindow({jobId:`w${i}`,windowStartSample:0,contentStartInWindowSample:0,
                realEndSample:224000,commitStartSample:i<2 ? 0 : 176000,
                stableEndSample:224000,finalWindow:false,result:{inferenceMs:0,
                  segments:[{startSample:w.start*16,endSample:w.end*16,speaker:0,speakerMask:1}],
                  embeddings:[{localSpeaker:0,speechRms:0.1,speechSamples:(w.end-w.start)*16,embedding:w.embedding,
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
          assert.equal(run([0,1],3000,6000,47999).result.speakerCount,1,
            'rounding milliseconds must not enroll a voice one sample below three seconds');
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
              embeddings:[{localSpeaker:0,speechRms:0.1,speechSamples:32000,embedding:[1,0,0]},
                {localSpeaker:1,speechRms:0.1,speechSamples:38400,embedding:current}]}};
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
                embeddings:[{localSpeaker:0,speechRms:0.1,speechSamples:51200,embedding:[1,0],queryEmbedding:[1,0]},
                  {localSpeaker:1,speechRms:0.1,speechSamples:51200,embedding:[0,1],queryEmbedding:[0,1]}]}});
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
