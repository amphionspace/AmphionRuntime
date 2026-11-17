"""Protect frontend timeline and the real adapter's queue/finish/cancel seam."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = ROOT / 'asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao'


class GtcrnTest(unittest.TestCase):
    def run_js(self, body):
        imports = "import assert from 'node:assert/strict';\n"
        for name in ('GtcrnFrontend', 'SessionAudioDispatcher'):
            imports += f"import {{ {name} }} from {(SDK / (name + '.ts')).as_uri()!r};\n"
        subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', imports + body],
                       cwd=ROOT, check=True)

    def test_length_tail_and_nonfinite(self):
        self.run_js("""
          let buffered=[];
          const frontend=new GtcrnFrontend({process:async(s,flush)=>{
            buffered.push(...s);
            return {samples:Float32Array.from(buffered.splice(0,flush?buffered.length:Math.max(0,buffered.length-256))),durationMs:1};
          }});
          const input=Int16Array.from({length:640},(_,i)=>i-320);
          const a=await frontend.run(input.buffer.slice(0,640));
          const b=await frontend.run(input.buffer.slice(640));
          const tail=await frontend.flush();
          assert.deepEqual([...new Int16Array(a),...new Int16Array(b),...new Int16Array(tail)],[...input]);
          assert.equal((await frontend.flush()).byteLength,0);
          await assert.rejects(()=>frontend.run(input.buffer),/after flush/);
          const broken=new GtcrnFrontend({process:async()=>({samples:new Float32Array(0),durationMs:0})});
          await broken.run(input.buffer);await assert.rejects(()=>broken.flush(),/length mismatch/);
          const nan=new GtcrnFrontend({process:async()=>({samples:Float32Array.of(NaN),durationMs:0})});
          await assert.rejects(()=>nan.run(input.buffer),/nonfinite/);
        """)

    def test_actual_adapter_drains_before_both_finishes_and_discards_cancel(self):
        source = (SDK / 'SpeechRecognizeSdk.ets').read_text(encoding='utf-8')
        start = source.index('      let processedAsrSamples: number = 0;')
        end = source.index('}, DiagnosticsModule.isEnabled());', start) + len('}, DiagnosticsModule.isEnabled());')
        install = source[start:end]
        for annotation in (': number', ': ArrayBuffer', ': Float32Array', ': Promise<void>', ': string', ': void'):
            install = install.replace(annotation, '')
        self.run_js("""
          const DiagnosticsModule={isEnabled:()=>false},hilog={info:()=>{}};
          function install(session,audioGeneration,audioSessionId) {
        """ + install + """
          }
          const events=[],asr=[],roles=[];
          const session={acceptPcmBytesAsync:async(a)=>{asr.push(...new Int16Array(a));events.push('asr');},
            requestStopFromCallback:()=>{},stopAsync:async()=>events.push('asrFinish')};
          let buffered=[];
          const owner={active:true,ownsAudioSession(){return this.active;},
            gtcrnDenoiser:{frontend:new GtcrnFrontend({process:async(s,flush)=>{
              buffered.push(...s);return {samples:Float32Array.from(flush?buffered.splice(0):[]),durationMs:1};}})},
            speakerDiarizationSession:{append:a=>{roles.push(...new Int16Array(a));events.push('roles');},asrAudioProcessed:()=>{}},
            requestSpeakerDiarizationFinish:()=>events.push('roleFinish'),handleAsrError:()=>assert.fail('unexpected error')};
          install.call(owner,session,1,'test');
          const pcm=Int16Array.from({length:320},(_,i)=>i);
          owner.audioDispatcher.write(pcm.buffer);pcm.fill(0);
          await owner.audioDispatcher.finish();
          assert.deepEqual(asr,Array.from({length:320},(_,i)=>i));assert.deepEqual(roles,asr);
          assert.deepEqual(events,['roles','asr','roleFinish','asrFinish']);
          let release,started;
          const running=new Promise(r=>started=r),pending=new Promise(r=>release=r);
          owner.gtcrnDenoiser={frontend:{run:async()=>{started();await pending;return new ArrayBuffer(640);}}};
          install.call(owner,session,2,'test2');owner.audioDispatcher.write(new ArrayBuffer(640));
          await running;owner.active=false;owner.audioDispatcher.cancel();release();
          await owner.audioDispatcher.whenIdle();assert.equal(events.length,4);
        """)


if __name__ == '__main__':
    unittest.main()
