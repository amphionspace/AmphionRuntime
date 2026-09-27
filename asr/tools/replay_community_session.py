#!/usr/bin/env python3
"""Replay one saved session through production SDK identity and transcript state.

Compile replay_community_cluster.cpp with the native include directory and supply
that binary, the locked PLDA and single-session events.full.ndjson. Optional JSON
windows replace acoustic evidence only, delivered by the next recorded window's
realEndSample. No audio or reference labels enter clustering. Output includes
private transcript data: keep it local. First compare an original-window replay
with the device's public payloads. This is not device resource/lifecycle evidence.
"""
from pathlib import Path
import argparse,json,hashlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--events',type=Path,required=True);p.add_argument('--windows',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--native-replay',type=Path,required=True);p.add_argument('--plda',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
root=Path(__file__).resolve().parents[2];d=root/'asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization';src=d/'SpeakerDiarizationSession.ets'
es=[json.loads(s) for s in a.events.read_text().splitlines()];es=[e for e in es if e['event'] in ['DIARIZATION_AUDIO_APPENDED','DIARIZATION_ASR_ALIGNMENT','DIARIZATION_ASR_ENDPOINT','DIARIZATION_ASR_PROCESSED','DIARIZATION_COMMUNITY_WINDOW','DIARIZATION_FINISH','DIARIZATION_DRAINED','DIARIZATION_PUBLIC_RESULT','CALLBACK_RESULT']]
sessions={e.get('sessionId') for e in es if e.get('sessionId')}
if len(sessions)!=1:raise ValueError('select exactly one session before replay')
(a.output/'input.json').write_text(json.dumps({'events':es,'windows':json.loads(a.windows.read_text()) if a.windows else None}))
imports="\n".join(f"import {{ {n} }} from {json.dumps((d/(n+'.ts')).as_uri())};" for n in ['DiarizationCommitClock','SpeakerDiarizationTranscriptState'])
imports+=f"\nimport {{ CommunitySpeakerIdentity, communityTimeline }} from {json.dumps((d/'CommunitySpeakerIdentity.ts').as_uri())};"
imports+=f"\nimport {{ speakerIndexFromInternalId, speakerIndexesFromInternalIds }} from {json.dumps((d/'SpeakerDiarizationSpeakerIndex.ts').as_uri())};"
js=r'''
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const output=process.argv[2],replay=process.argv[3],plda=process.argv[4];
const input=JSON.parse(fs.readFileSync(path.join(output,'input.json'),'utf8'));
const SAMPLE_RATE=16000;
const ResultAudioTimeline={endSample:r=>r.audioEndSample};
const SpeakerDiarizationDegradedReason={NONE:0,INFERENCE_UNAVAILABLE:1};
class SpeakerDiarizationResult {utterances=[];speakerTurns=[];}
class DiarizedUtterance {} class SpeakerTurn {} class SpeakerTextSpan {} class SpeakerDiarizationUpdate {}
let leases=0;
const SpeakerDiarizationRuntimeLeaseRegistry={acquire:()=>{leases++;return {release(){leases--}}}};
class SpeakerDiarizationLocalClient {
 evidence=[]; clusterCalls=0;
 append(){} finish(){} cancel(cb){cb?.()} cleanup(cb){cb?.()}
 retainEvidence(w){this.evidence.push(w)}
 readEvidence(n){
  const selected=this.evidence.slice(0,n);
  const segments=new Float32Array(n*589*3),embeddings=new Float32Array(n*768);
  const rows=selected.reduce((a,w)=>a+w.runRanges.length/4,0);
  const runEmbeddings=new Float32Array(rows*256),runRanges=new Float32Array(rows*4);let offset=0;
  for(let i=0;i<n;i++){
   const w=selected[i];segments.set(w.segments,i*589*3);embeddings.set(w.embeddings,i*768);
   runEmbeddings.set(w.runEmbeddings,offset*256);runRanges.set(w.runRanges,offset*4);
   for(let j=0;j<w.runRanges.length/4;j++)runRanges[(offset+j)*4]=i;
   offset+=w.runRanges.length/4;
  }
  return {segments,embeddings,runEmbeddings,runRanges};
 }
 async cluster(segments,embeddings,cap,starts,begin,runEmbeddings,runRanges){
  const header=Buffer.alloc(24);header.writeUInt32LE(0x43525031,0);header.writeUInt32LE(starts.length,4);
  header.writeUInt32LE(runRanges.length/4,8);header.writeUInt32LE(cap,12);header.writeDoubleLE(begin,16);
  const arrays=[starts,segments,embeddings,runEmbeddings,new Int32Array(runRanges)];
  const file=path.join(output,`cluster-${this.clusterCalls++}.bin`);
  fs.writeFileSync(file,Buffer.concat([header,...arrays.map(a=>Buffer.from(a.buffer,a.byteOffset,a.byteLength))]));
  return JSON.parse(execFileSync(replay,[plda,file],{maxBuffer:16*1024*1024}).toString());
 }
}
'''
body=src.read_text();js=imports+'\n'+js+'\n'+body[body.index('export class SpeakerDiarizationSession'):]+r'''
const records=[],publicResults=[],snapshots=[],updates=[];
const s=new SpeakerDiarizationSession({},'',4,{
 onSpeakerDiarizationUpdate:u=>updates.push(JSON.parse(JSON.stringify(u))),
 onWindowResult:r=>{publicResults.push(r);snapshots.push(JSON.stringify(r))},
 onFinished:r=>{publicResults.push(r);snapshots.push(JSON.stringify(r))},
},(event,fields)=>{if(!['DIARIZATION_AUDIO_APPENDED','DIARIZATION_ASR_PROCESSED','DIARIZATION_COMMUNITY_WINDOW'].includes(event))records.push({event,fields})});
let next=0;
function window(w){
 const f=v=>new Float32Array(v.map(x=>x===null?NaN:x));
 return {jobId:`sample-${w.windowStartSample}`,windowStartSample:w.windowStartSample,realEndSample:w.realEndSample,
 result:{segments:f(w.segmentations),embeddings:f(w.embeddings),runEmbeddings:f(w.runEmbeddings),runRanges:f(w.runRanges),segmentationMs:0,featureMs:0,embeddingMs:0}};
}
async function settle(){await new Promise(r=>setImmediate(r));assert.equal(s.committing,false)}
for(const e of input.events){
 const f=e.fields;
 switch(e.event){
 case 'DIARIZATION_AUDIO_APPENDED':s.append(new ArrayBuffer((f.audioEndSample-s.totalSamples)*2));break;
 case 'DIARIZATION_ASR_PROCESSED':s.asrAudioProcessed(f.audioEndSample);break;
 case 'DIARIZATION_ASR_ENDPOINT':s.asrFinalDelivered({audioEndSample:f.audioEndSample,isLast:false});break;
 case 'DIARIZATION_ASR_ALIGNMENT':s.observeAsrFinal({result:f.text,beginTime:f.beginTime,endTime:f.endTime,isLast:f.isLast},
  {rawText:f.rawText,textNormalization:f.textNormalization,tokens:f.tokens,timestamps:f.tokenTimesMs.map(t=>t/1000),audioEndSample:f.audioEndSample,isLast:f.isLast});break;
 case 'DIARIZATION_COMMUNITY_WINDOW':
  if(input.windows){while(next<input.windows.length&&input.windows[next].realEndSample<=f.realEndSample){s.onWindow(window(input.windows[next++]));await settle()}}
  else s.onWindow(window(f));break;
 case 'DIARIZATION_FINISH':s.finish(f.confirmedInitialSilence??false);break;
 case 'DIARIZATION_DRAINED':s.onDrained();break;
 case 'CALLBACK_RESULT':
  if(f.isLast&&f.textChars===0&&!s.asrTailObserved)s.observeAsrFinal({result:'',isLast:true},{tokens:[],timestamps:[],isLast:true});break;
 }
 await settle();
}
assert.equal(s.finished,true);assert.equal(publicResults.filter(r=>r.isSessionFinal).length,1);
assert.deepEqual(publicResults.map(r=>JSON.stringify(r)),snapshots,'published objects remain frozen');
if(input.windows)assert.equal(next,input.windows.length);
s.cleanup();assert.equal(leases,0);
fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({scope:'host production session with stored ASR/tensors; no realtime/phone lifecycle claim',publicResults,updates,records},null,2)+'\n');
console.log(JSON.stringify({publicResults:publicResults.length,previews:records.filter(e=>e.event==='DIARIZATION_COMMUNITY_PREVIEW').length,updates:updates.length,clusterCalls:s.client.clusterCalls,finalSpeakerCount:publicResults.at(-1).speakerCount}));
'''
f=a.output/'replay.mts';f.write_text(js)
subprocess.run(['node','--experimental-strip-types','--experimental-loader',(root/'asr/tools/tests/ts_extension_loader.mjs').as_uri(),str(f),str(a.output),str(a.native_replay),str(a.plda)],check=True)
rec=lambda p:{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
(a.output/'provenance.json').write_text(json.dumps({'scope':'host production session; not device resource/lifecycle acceptance','sessionSource':rec(src),'stateSources':{n:rec(d/n) for n in ['CommunitySpeakerIdentity.ts','DiarizationCommitClock.ts','SpeakerDiarizationTranscriptState.ts']},'events':rec(a.events),'windows':rec(a.windows) if a.windows else None,'nativeReplay':rec(a.native_replay),'plda':rec(a.plda),'harness':rec(f)},indent=2)+'\n')
