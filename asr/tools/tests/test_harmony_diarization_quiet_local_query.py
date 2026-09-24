"""Quiet identity recovery must be local, causal, and unable to enroll roles."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from asr.tools.tests.test_harmony_diarization_identity_stability import run_session

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'


class HarmonyDiarizationQuietLocalQueryTest(unittest.TestCase):
    def test_quiet_recovery_requires_local_agreement_and_preserves_other_evidence(self):
        run_session("""
          const s=session();
          for(const [v,id] of [[[1,0],'S1'],[[0,1],'S2']]) {
            s.committedRegistry.assign(new Float32Array(v),6000,0,true);
            s.committedRegistry.bindComplementaryProfile(id,[v],[6000]);
            s.publishedSpeakerIds.add(id);
          }
          s.speakerLevelReference=.2;
          const before=JSON.stringify(s.committedRegistry.snapshot());
          s.onWindow({jobId:'quiet',windowStartSample:0,contentStartInWindowSample:0,
            realEndSample:80000,commitStartSample:0,stableEndSample:48000,finalWindow:false,
            result:{inferenceMs:0,embeddings:[{localSpeaker:0,speechSamples:48000,speechRms:.02,
              embedding:[1,0],queryEmbedding:[1,0],complementaryEmbedding:[1,0]}],segments:[{
              startSample:0,endSample:48000,speaker:0,speakerMask:1,queryEmbedding:[1,0],complementaryEmbedding:[1,0],
              localQueries:[
                {startSample:0,endSample:4000,embedding:[1,0],complementaryEmbedding:[1,0]},
                {startSample:4000,endSample:8000,embedding:[0,1],complementaryEmbedding:[0,1]},
                {startSample:8000,endSample:12000,embedding:[1,0],complementaryEmbedding:[0,1]},
                {startSample:12000,endSample:16000,embedding:[1,1],complementaryEmbedding:[1,1]}]}]}});
          s.totalSamples=80000;
          const result=s.commitWindow(5000,5000,true,0);
          assert.equal(result.speakerTurns.find(t=>t.beginTime===0).speakerIndex,0,
            'a quiet run may recover its existing identity only where local PCM agrees');
          assert.ok(result.speakerTurns.filter(t=>t.beginTime>=250).every(t=>t.speakerIndex===-1),
            'another local identity, model disagreement, weak evidence and unqueried PCM stay UNKNOWN');
          assert.equal(JSON.stringify(s.committedRegistry.snapshot()),before,'no enrollment or profile updates');

          const transcript=new SpeakerDiarizationTranscriptState();
          const turns=[
            {beginTime:0,endTime:250,speakerId:'S2',secondarySpeakerIds:[],evidenceKey:'q'},
            {beginTime:250,endTime:500,speakerId:'UNKNOWN',secondarySpeakerIds:['UNKNOWN'],overlap:true,evidenceKey:'q'},
            {beginTime:500,endTime:1000,speakerId:'UNKNOWN',secondarySpeakerIds:[],evidenceKey:'q'}];
          transcript.applySpeakerTurns(turns);
          transcript.resolveUnknownSpan('q',0,750,'S1',.8,{});
          assert.deepEqual(transcript.allTurns().map(t=>[t.beginTime,t.endTime,t.speakerId]),
            [[0,250,'S2'],[250,500,'UNKNOWN'],[500,750,'S1'],[750,1000,'UNKNOWN']]);
          const frozen=transcript.commitThrough(1000);
          transcript.resolveUnknownSpan('q',0,1000,'S2',1,{});
          assert.equal(transcript.allTurns().length,0,'late evidence cannot revive committed turns');
        """)

    def test_local_pcm_uses_absolute_grid_and_never_reads_padding_or_future(self):
        source=SOURCE.read_text();source=source[source.index('const SAMPLE_RATE:'):]
        driver="""
          import assert from 'node:assert/strict';
          const inference=new SpeakerDiarizationInference();
          inference.extractor={};inference.complementaryExtractor={};inference.localQueryExtractor={};inference.localComplementaryExtractor={};
          inference.computeEmbedding=async pcm=>Float32Array.of(pcm[0],pcm.at(-1));
          async function collect(origin,a,b){
            const samples=Float32Array.from({length:160000},(_,i)=>origin+i);
            return inference.queryQuietLocalIdentity(samples,
              {startSample:a-origin,endSample:b-origin},a-origin,b-origin,origin);
          }
          const full=await collect(0,20000,60000), shifted=await collect(8000,20000,60000);
          assert.deepEqual(full,shifted,'same absolute PCM and output must not depend on window origin');
          assert.ok(full.length>0);
          for(const q of full){
            assert.equal(q.embedding[1]-q.embedding[0]+1,20800,'exactly 1.3 seconds of continuous original PCM');
            assert.deepEqual(q.embedding,q.complementaryEmbedding);
            assert.ok(q.startSample>=20000 && q.endSample<=60000);
          }
          const padded=await collect(-80000,0,80000);
          assert.ok(padded.every(q=>q.embedding[0]>=0 && q.embedding[1]<80000),
            'neither initial zero padding nor unavailable future PCM may become identity evidence');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness=Path(directory)/'local-query.mts';harness.write_text(source+driver)
            subprocess.run(['node','--experimental-strip-types',str(harness)],check=True,cwd=ROOT)
