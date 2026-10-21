"""Student route: committed roles, ASR tail barrier and stable public results."""
import subprocess
import tempfile
import unittest
import json
import shutil
from pathlib import Path
from asr.tools.tests.test_harmony_speaker_diarization_session import ROOT, DIARIZATION, SESSION, TS_LOADER


def run_session(body):
    imports = '\n'.join(
        f'import {{ {name} }} from {(DIARIZATION / file).as_uri()!r};'
        for name, file in [
            ('DiarizationCommitClock', 'DiarizationCommitClock.ts'),
            ('SpeakerDiarizationTranscriptState', 'SpeakerDiarizationTranscriptState.ts'),
            ('nmnetTimeline', 'NmnetTimeline.ts'),
            ('speakerIndexFromInternalId, speakerIndexesFromInternalIds', 'SpeakerDiarizationSpeakerIndex.ts')])
    stubs = '''
      import assert from 'node:assert/strict';
      const SAMPLE_RATE=16000;
      const ResultAudioTimeline={endSample:r=>r.audioEndSample};
      const SpeakerDiarizationDegradedReason={NONE:0,INFERENCE_UNAVAILABLE:1,FINISH_TIMEOUT:4};
      class SpeakerDiarizationResult {utterances=[];speakerTurns=[];}
      class DiarizedUtterance {} class SpeakerTurn {} class SpeakerTextSpan {} class SpeakerDiarizationUpdate {}
      class SpeakerDiarizationLocalClient {
        append(){} cancel(cb){cb?.()} cleanup(cb){cb?.()} finish(){} stopInference(){}
        pendingWindowCount(){return 0}
      }
      let released=0;
      const SpeakerDiarizationRuntimeLeaseRegistry={acquire:()=>({release(){released++}})};
      const tick=()=>new Promise(r=>setImmediate(r));
      function delta(inferred,committed,turns) {return {inferenceThroughSample:inferred*16,
        rolesCommittedThroughSample:committed*16,turns,speakerCount:2,encoderBackend:'cpu'};}
      function sentence(s,begin,end,text,last=false) {
        const r={rawText:text,tokens:[text],timestamps:[begin/1000],isLast:last,audioEndSample:end*16};
        s.observeAsrFinal({result:text,beginTime:begin,endTime:end,isLast:last},r);
        if(!last)s.asrFinalDelivered(r);
      }
    '''
    source = SESSION.read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory() as directory:
        harness = Path(directory) / 'nmnet.mts'
        harness.write_text(imports + stubs + source[source.index('export class SpeakerDiarizationSession'):] + body, encoding='utf-8')
        subprocess.run(['node', '--experimental-strip-types', '--experimental-loader', TS_LOADER.as_uri(), str(harness)], check=True, cwd=ROOT)


class NmnetRoutingTest(unittest.TestCase):
    def test_executor_padding_order_finish_and_cancel_during_flush(self):
        source = (DIARIZATION/'SpeakerDiarizationLocalClient.ets').read_text(encoding='utf-8')
        prelude = f"import {{ DiarizationWindowScheduler }} from {(DIARIZATION/'DiarizationWindowScheduler.ts').as_uri()!r};"
        prelude += '''
          import assert from 'node:assert/strict';
          const fs={accessSync:()=>true,listFileSync:()=>[],rmdirSync(){}};
          const SpeakerDiarizationDegradedReason={};
          const tick=()=>new Promise(r=>setImmediate(r));
          let calls=[],finishes=0,closes=0,flushResolve;
          class NmnetDiarizationInference {
            load(){return Promise.resolve()}
            async process(pcm,valid,index){
              assert.equal(pcm.length,320000);assert.equal(pcm[0],.5);
              if(valid<320000)assert.equal(pcm[valid],0);
              calls.push([valid,index]);
              return {rolesCommittedThroughSample:(index+1)*32000};
            }
            finish(){finishes++;return new Promise(r=>flushResolve=r)}
            close(){closes++}
          }
          class DiarizationPcmSpool {
            data=new Uint8Array();
            append(audio){const next=new Uint8Array(this.data.length+audio.byteLength);next.set(this.data);next.set(new Uint8Array(audio),this.data.length);this.data=next}
            read(offset,size){return this.data.slice(offset,offset+size).buffer}
            discardBefore(){} endOffset(){return this.data.length} close(){} remove(){}
          }
        '''
        body = '''
          for(const tail of [0,123]) {
            calls=[];finishes=0;closes=0;const seen=[];
            const c=new SpeakerDiarizationLocalClient({},'',{onWindow(){seen.push('window')},
              onFlushed(){seen.push('flush')},onDrained(){seen.push('drained')},onDegraded(){assert.fail('degraded')}});
            c.append(new Int16Array(320000+tail).fill(16384).buffer);c.finish();c.finish();
            await tick();await tick();
            assert.deepEqual(calls,tail?[[320000,0],[288000+tail,1]]:[[320000,0]]);
            assert.equal(finishes,1);assert.ok(!seen.includes('drained'));
            if(tail){c.cancel(()=>seen.push('closed'));assert.equal(closes,0)}
            flushResolve({});await tick();
            if(tail){assert.deepEqual(seen,['window','window','closed']);assert.equal(closes,1)}
            else {assert.deepEqual(seen,['window','flush','drained']);c.cleanup();assert.equal(closes,1)}
          }
        '''
        with tempfile.TemporaryDirectory() as directory:
            harness=Path(directory)/'client.mts'
            harness.write_text(prelude+source[source.index('const SAMPLE_RATE'):]+body, encoding='utf-8')
            subprocess.run(['node','--experimental-strip-types','--experimental-loader',TS_LOADER.as_uri(),str(harness)],check=True,cwd=ROOT)

    def test_native_projection_caps_identity_without_merging_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'projection.cpp'
            binary = Path(directory) / 'projection.exe'
            source.write_text('''
              #include "nmnet_sdk_session.h"
              #include <iostream>
              int main() {
                nmnet::PublicProjection p(1); nmnet::SessionDelta d;
                d.inferenceThroughSample=2500;d.rolesCommittedThroughSample=2500;
                d.committed.push_back({0,{true,true},{{5,{1,1}},{7,{0,1}},{9,{0,1}}}});
                std::cout<<p.Json(d)<<"\\n";
                d.committed={{2,{true},{{7,{1}},{5,{1}}}}};
                d.inferenceThroughSample=3000;d.rolesCommittedThroughSample=3000;
                std::cout<<p.Json(d)<<"\\n";
              }
            ''')
            subprocess.run([shutil.which('g++'), '-std=c++17', '-static',
                            '-I'+str(ROOT/'asr/harmony/sdk/src/main/cpp'), str(source), '-o', str(binary)], check=True)
            a,b = [json.loads(line) for line in subprocess.check_output([str(binary)], text=True).splitlines()]
            self.assertEqual(a['speakerCount'], 1)
            self.assertEqual(a['turns'], [[0,156.25,0],[80,156.25,-1],[80,156.25,-1]])
            self.assertEqual(b['turns'], [[160,187.5,0],[160,187.5,-1]])

    def test_native_unlimited_projection_twelve_stable_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'unlimited.cpp';binary=Path(directory)/'unlimited.exe'
            source.write_text('''
#include "nmnet_sdk_session.h"
#include <cassert>
#include <iostream>
int main() {
  nmnet::PublicProjection p(0);nmnet::SessionDelta d;
  for(int i=0;i<12;++i) {
    d.inferenceThroughSample=(i+1)*1280;d.rolesCommittedThroughSample=d.inferenceThroughSample;
    d.committed={{static_cast<uint64_t>(i),{true},{{100+i,{1}}}}};
    std::cout<<p.Json(d)<<"\\n";
  }
  d.inferenceThroughSample=13*1280;d.rolesCommittedThroughSample=d.inferenceThroughSample;
  d.committed={{12,{true},{{100,{1}},{111,{1}}}}};
  std::cout<<p.Json(d)<<"\\n";
  try {nmnet::PublicProjection invalid(-1);return 1;} catch(const std::invalid_argument&) {}
}
''')
            subprocess.run([shutil.which('g++'),'-std=c++17','-static','-I'+str(ROOT/'asr/harmony/sdk/src/main/cpp'),str(source),'-o',str(binary)],check=True)
            rows=[json.loads(x) for x in subprocess.check_output([str(binary)],text=True).splitlines()]
            self.assertEqual([r['turns'][0][2] for r in rows[:12]],list(range(12)))
            self.assertEqual(rows[-1]['speakerCount'],12)
            self.assertEqual([t[2] for t in rows[-1]['turns']],[0,11])

    def test_unlimited_public_ids_and_secondary_roles(self):
        run_session(''' 
          const published=[];
          const s=new SpeakerDiarizationSession({},'',0,{onSpeakerDiarizationUpdate(){},
            onWindowResult:r=>published.push(r),onFinished:r=>published.push(r)},undefined,undefined,30000);
          s.totalSamples=50000*16;
          sentence(s,0,10000,'多人对话');s.asrAudioProcessed(50000*16);
          const d=delta(50000,34000,[[0,10000,4],[0,10000,11]]);d.speakerCount=12;
          s.onWindow({result:d,inferenceWallMs:0});await tick();
          assert.ok(published.length>0);
          const roles=published.flatMap(r=>r.speakerTurns).flatMap(t=>[t.speakerIndex,...t.secondarySpeakerIndexes]);
          assert.ok(roles.includes(4));assert.ok(roles.includes(11));assert.ok(!roles.includes(-1));
          assert.equal(speakerIndexFromInternalId('S12',0),11);
          assert.equal(speakerIndexFromInternalId('S12',4),-1);
          s.cancel();
        ''')

    def test_committed_progress_freezes_sentence_and_tail_waits_for_asr(self):
        run_session('''
          const published=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult:r=>published.push(r),onFinished:r=>published.push(r)},undefined,undefined,30000);
          s.totalSamples=50000*16;
          sentence(s,0,10000,'完整词语');s.asrAudioProcessed(30000*16);
          s.onWindow({result:delta(50000,2000,[[0,2000,0]]),inferenceWallMs:0});
          await tick();assert.equal(published.length,0,'inferred audio must not commit unfinalized roles');
          s.onWindow({result:delta(50000,34000,[[2000,34000,0]]),inferenceWallMs:0});
          await tick();assert.equal(published.length,1);assert.equal(published[0].windowEndTime,10000);
          assert.equal(published[0].utterances.map(u=>u.text).join(''),'完整词语');
          const frozen=JSON.stringify(published[0]);
          s.finish();s.onFlushed(delta(50000,50000,[[34000,50000,1]]));s.onDrained();
          await tick();assert.equal(published.length,1,'native finish must wait for ASR tail');
          sentence(s,34000,50000,'另一个人',true);await tick();
          assert.equal(published.length,2);assert.equal(published[1].isSessionFinal,true);
          assert.equal(JSON.stringify(published[0]),frozen);
          assert.equal(published[1].utterances.map(u=>u.text).join(''),'另一个人');
          assert.notEqual(published[0].speakerTurns[0].speakerIndex,published[1].speakerTurns.at(-1).speakerIndex);
          s.onDrained();await tick();assert.equal(published.length,2);
        ''')

    def test_cancel_drops_late_windows_and_flush(self):
        run_session('''
          const seen=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate:r=>seen.push(r),
            onWindowResult:r=>seen.push(r),onFinished:r=>seen.push(r)});
          s.totalSamples=20000*16;sentence(s,0,20000,'测试');s.finish();s.cancel();
          s.onWindow({result:delta(20000,2000,[[0,2000,0]]),inferenceWallMs:0});
          s.onFlushed(delta(20000,20000,[[2000,20000,0]]));s.onDrained();await tick();
          assert.deepEqual(seen,[]);assert.equal(released,1);
        ''')
