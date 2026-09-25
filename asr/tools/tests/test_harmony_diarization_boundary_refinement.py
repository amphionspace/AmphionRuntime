"""Later native evidence may refine an unpublished turn, never a committed one."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'


class HarmonyDiarizationBoundaryRefinementTest(unittest.TestCase):

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
