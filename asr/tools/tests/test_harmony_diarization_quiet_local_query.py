"""Community sampling preserves quiet PCM without an adapter admission filter."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from asr.tools.tests.test_harmony_speaker_diarization_session import DIARIZATION, ROOT

SOURCE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'


class HarmonyDiarizationQuietLocalQueryTest(unittest.TestCase):
    def test_quiet_pcm_is_preserved_and_only_the_missing_tail_is_padded(self):
        source = (DIARIZATION / 'SpeakerDiarizationLocalClient.ets').read_text()
        read = 'private readWindow(' + source.split('private readWindow(', 1)[1].split('\n  private fail(', 1)[0]
        script = """
          import assert from 'node:assert/strict';
          const WINDOW_SAMPLES=160000;
          class SpeakerDiarizationStorageError extends Error {}
          const pcm=Int16Array.from({length:8000},(_,i)=>i%2===0?1:-100);
          const calls=[];
          class Client {
            spool={read:(offset,length)=>{calls.push([offset,length]);return pcm.buffer;}};
        """ + read + """
          }
          const samples=new Client().readWindow({offsetBytes:32000,sampleCount:8000});
          assert.deepEqual(calls,[[32000,16000]]);
          assert.equal(samples.length,160000);
          for(let i=0;i<8000;i++)assert.equal(samples[i],pcm[i]/32768);
          assert.ok(samples.slice(8000).every(x=>x===0));
          assert.notEqual(samples[0],0,'quiet real PCM cannot be dropped by an amplitude gate');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'quiet.mts'
            harness.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True, cwd=ROOT)

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
