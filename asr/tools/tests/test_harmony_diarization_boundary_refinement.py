"""Later native evidence may refine an unpublished turn, never a committed one."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from asr.tools.tests.test_harmony_diarization_identity_stability import run_session

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'


class HarmonyDiarizationBoundaryRefinementTest(unittest.TestCase):
    def test_commit_uses_independently_matched_children_without_enrolling_or_expanding(self):
        run_session("""
          function prepare() {
            const s=session();
            for(const [v,id] of [[[1,0],'S1'],[[0,1],'S2']]) {
              s.committedRegistry.assign(new Float32Array(v),6000,0,true);
              s.committedRegistry.bindComplementaryProfile(id,[v],[6000]);
              s.publishedSpeakerIds.add(id);
            }
            s.transcript.applySpeakerTurns([
              {beginTime:1000,endTime:2500,speakerId:'S1',secondarySpeakerIds:[],evidenceKey:'old'},
              {beginTime:2700,endTime:6000,speakerId:'S1',secondarySpeakerIds:[],evidenceKey:'old'}]);
            s.transcript.addUtterance({rawText:'你好谢谢',text:'你好谢谢',tokens:['你好','谢谢'],
              tokenTimesMs:[1000,4000],beginTime:1000,endTime:6000});
            s.totalSamples=160000;
            s.onWindow({jobId:'later',windowStartSample:0,contentStartInWindowSample:0,
              realEndSample:160000,commitStartSample:96000,stableEndSample:120000,finalWindow:false,
              result:{segments:[],embeddings:[],inferenceMs:0,refinements:[{
                startSample:16000,cutSample:48000,endSample:96000,
                leftEmbedding:[0,1],leftComplementaryEmbedding:[0,1],
                rightEmbedding:[1,0],rightComplementaryEmbedding:[1,0]}]}});
            return s;
          }
          const s=prepare(),before=JSON.stringify(s.committedRegistry.snapshot());
          const result=s.commitWindow(10000,10000,true,0);
          assert.deepEqual(result.speakerTurns.map(t=>[t.beginTime,t.endTime,t.speakerIndex]),
            [[1000,2500,1],[2700,3000,1],[3000,6000,0]],'later confirmed change must revise only existing coverage');
          assert.equal(JSON.stringify(s.committedRegistry.snapshot()),before,'no profile update or enrollment');
          assert.deepEqual(result.utterances.map(u=>[u.text,u.speakerIndex]),[['你好谢谢',-1]]);
          const frozen=JSON.stringify(result);
          s.commitWindow(11000,Infinity,true,10000);
          assert.equal(JSON.stringify(result),frozen,'published results remain frozen');

          for(const mode of ['unknown','overlap','shortKnownChange','outsideCommit','lateEvidence','ambiguousChild']) {
            const x=prepare();
            if(mode==='unknown') x.transcript.turns[0].speakerId='UNKNOWN';
            if(mode==='overlap') {x.transcript.turns[0].overlap=true;x.transcript.turns[0].secondarySpeakerIds=['UNKNOWN'];}
            if(mode==='shortKnownChange') x.transcript.applySpeakerTurns([
              {beginTime:2000,endTime:2010,speakerId:'S2',secondarySpeakerIds:[]}]);
            if(mode==='ambiguousChild') x.recentRefinements[0].leftComplementaryEmbedding=[1,1];
            const expected=x.transcript.allTurns().map(t=>[t.beginTime,t.endTime,t.speakerId]);
            let observed;
            const build=x.buildResult.bind(x);
            x.buildResult=(...args)=>{observed=x.transcript.allTurns().map(t=>[t.beginTime,t.endTime,t.speakerId]);return build(...args);};
            x.commitWindow(10000,mode==='lateEvidence'?9999:10000,true,mode==='outsideCommit'?1500:0);
            assert.deepEqual(observed,expected,mode+' must preserve the existing evidence');
          }
        """)

    def test_later_boundary_queries_continuous_children_from_original_pcm(self):
        source = SOURCE.read_text()
        source = source[source.index('const SAMPLE_RATE:'):]
        driver = """
          import assert from 'node:assert/strict';
          let segments=[{startSample:16000,endSample:100000,speaker:0,speakerMask:1}];
          async function processSpeakerTurnSegmentationAsync(){return segments;}
          const inference=new SpeakerDiarizationInference();
          inference.extractor={};inference.complementaryExtractor={};
          const consumed=[];
          inference.computeEmbedding=async pcm=>{consumed.push(pcm);return Float32Array.of(pcm[0],pcm.at(-1));};
          const samples=Float32Array.from({length:160000},(_,i)=>i/160000);
          await inference.process(samples,0,60000,0);
          consumed.length=0;
          segments=[{startSample:24000,endSample:50000,speaker:1,speakerMask:2},
            {startSample:50000,endSample:105000,speaker:2,speakerMask:4}];
          const result=await inference.process(samples,90000,120000,0);
          assert.equal(result.refinements.length,1,'a historical boundary inside the earlier run needs independent child evidence');
          const r=result.refinements[0];
          assert.deepEqual([r.startSample,r.cutSample,r.endSample],[16000,50000,90000]);
          assert.deepEqual(r.leftEmbedding,[samples[16000],samples[49999]]);
          assert.deepEqual(r.leftComplementaryEmbedding,r.leftEmbedding);
          assert.deepEqual(r.rightEmbedding,[samples[50000],samples[104999]]);
          assert.deepEqual(r.rightComplementaryEmbedding,r.rightEmbedding);
          assert.deepEqual(result.segments.map(s=>[s.startSample,s.endSample,s.speakerMask]),
            [[24000,50000,2],[50000,105000,4]],'raw native boundaries stay intact');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'refinement.mts'
            harness.write_text(source + driver)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True, cwd=ROOT)
