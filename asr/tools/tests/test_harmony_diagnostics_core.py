import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CORE = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DiagnosticsCore.ts"
)
ADAPTER = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
MODELS = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DingqiaoModels.ets"
)
MODULE = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DiagnosticsModule.ets"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
SINKS = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DiagnosticSinks.ets"
)
SDK_BUILD_PROFILE = REPO_ROOT / "asr/harmony/build-profile.json5"
DELIVERY_BUILD_PROFILE = REPO_ROOT / "delivery/harmony-dingqiao/build-profile.json5"


class HarmonyDiagnosticsCoreTest(unittest.TestCase):
    def run_core(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ DiagnosticsCore }} from {CORE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_audio_is_exactly_the_validated_public_input_and_rolls_at_the_limit(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'CUSTOMER_SUPPORT', captureAudio: true,
              includeRecognitionText: false, maxSessionAudioSec: 0.04 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('customer-secret', engine, {}, 1010);
            const first = new ArrayBuffer(640);
            const second = new ArrayBuffer(640);
            new Int16Array(first).fill(1000);
            new Int16Array(second).fill(-2000);
            core.captureAudio('customer-secret', first, 1020);
            core.captureAudio('customer-secret', second, 1045);
            new Int16Array(first).fill(0);

            const snapshot = core.snapshot();
            assert.equal(snapshot.sessions.length, 1);
            assert.equal(snapshot.sessions[0].sessionId, 'session-1');
            assert.equal(snapshot.sessions[0].audio.bytes, 1280);
            assert.equal(snapshot.sessions[0].audio.frames, 2);
            assert.equal(snapshot.sessions[0].audio.durationMs, 40);
            assert.equal(snapshot.sessions[0].audio.maxFrameGapMs, 25);
            assert.equal(snapshot.sessions[0].audio.truncated, false);
            assert.equal(new Int16Array(snapshot.sessions[0].audio.pcm)[0], 1000);

            core.captureAudio('customer-secret', new ArrayBuffer(640), 1065);
            assert.equal(core.snapshot().sessions[0].audio.truncated, true);
            assert.equal(core.snapshot().sessions[0].audio.bytes, 1280);
            assert.equal(core.snapshot().sessions[0].audio.totalInputBytes, 1920);
            assert.equal(core.snapshot().sessions[0].audio.durationMs, 40);
            assert.equal(core.snapshot().sessions[0].audio.totalInputDurationMs, 60);
            assert.equal(core.snapshot().sessions[0].audio.rollingDroppedBytes, 640);
            assert.equal(new Int16Array(core.snapshot().sessions[0].audio.pcm)[0], -2000);
            """
        )

    def test_sensitive_fields_are_default_redacted_and_text_is_opt_in(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'CUSTOMER_SUPPORT', captureAudio: false,
              includeRecognitionText: false, maxSessionAudioSec: 120 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('real-session', engine, {}, 1010);
            core.record('real-session', engine, 'CALLBACK_RESULT', {
              text: 'sensitive text', tokens: 'secret token', hotwords: 'person name',
              voiceprintIds: 'secret-id', licenseText: 'private-key',
              message: '/data/storage/private/path', isLast: true
            }, 1020);
            const event = core.snapshot().events[1];
            assert.deepEqual(event.fields, { isLast: true });
            assert.equal(event.sessionId, 'session-1');

            const withText = new DiagnosticsCore();
            withText.configure({ enabled: true, mode: 'CUSTOMER_SUPPORT', captureAudio: false,
              includeRecognitionText: true, maxSessionAudioSec: 120 }, 2000);
            const secondEngine = withText.nextEngineId();
            withText.beginSession('real-session', secondEngine, {}, 2010);
            withText.record('real-session', secondEngine, 'CALLBACK_RESULT', {
              text: 'allowed', hotwords: 'still-secret'
            }, 2020);
            assert.deepEqual(withText.snapshot().events[1].fields, { text: 'allowed' });
            """
        )

    def test_schema_two_carries_required_correlation_and_monotonic_fields(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'BASIC', captureAudio: false,
              includeRecognitionText: false, maxSessionAudioSec: 120 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('public', engine, {}, 1010);
            core.record('public', engine, 'RUNTIME_ENDPOINT', {}, 1020, 2, 'native-worker');
            const events = core.snapshot().events;
            assert.equal(events[1].schemaVersion, 2);
            assert.equal(events[1].streamGeneration, 2);
            assert.equal(events[1].thread, 'native-worker');
            assert.ok(events[1].monotonicTimeNs > events[0].monotonicTimeNs);
            """
        )

    def test_diagnostics_stays_out_of_runtime_and_has_three_sink_types(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        module = MODULE.read_text(encoding="utf-8")
        sinks = SINKS.read_text(encoding="utf-8")
        self.assertNotIn("setDiagnosticObserver", runtime)
        self.assertIn("kind=SPEAKER_FINAL_GATE", runtime)
        self.assertIn("kind=STREAM_TRANSITION", runtime)
        self.assertNotIn("bindRuntimeSession", module)
        self.assertIn("BUILD_MODE_NAME", module)
        self.assertIn("class HilogDiagnosticSink", sinks)
        self.assertIn("class NdjsonDiagnosticSink", sinks)
        self.assertIn("class MemoryDiagnosticSink", sinks)

    def test_wav_export_preserves_pcm_without_copying_the_recording(self) -> None:
        source = MODULE.read_text()
        writer = source[source.index('function writeWav('):source.index('function writeText(')]
        header = source[source.index('function writeAscii('):source.index('function csvOf(')]
        script = r"""
          import assert from 'node:assert/strict';
          const WAV_HEADER_BYTES=44;
          let parts=[],closed=0,failAt=0,writes=0,allocated=0;
          const fs={OpenMode:{WRITE_ONLY:1,CREATE:2,TRUNC:4},
            openSync(){return {fd:7}},
            writeSync(fd,value){
              assert.equal(fd,7);writes++;
              if(writes===failAt)throw new Error('disk unavailable');
              parts.push(value);
            },closeSync(fp){assert.equal(typeof fp==='number'?fp:fp.fd,7);closed++}};
          const OriginalArrayBuffer=globalThis.ArrayBuffer;
          globalThis.ArrayBuffer=class extends OriginalArrayBuffer {
            constructor(size){super(size);allocated+=size}
          };
        """ + writer + header + r"""
          for(const size of [0,640,300*32000]) {
            const pcm=new OriginalArrayBuffer(size),bytes=new Uint8Array(pcm);
            for(let i=0;i<size;i++)bytes[i]=i%251;
            parts=[];writes=0;allocated=0;const before=closed;
            writeWav('capture.wav',pcm);
            assert.equal(closed,before+1);
            assert.ok(allocated<=44,'encoding overhead must not grow with recording length');
            const wav=Buffer.concat(parts.map(p=>Buffer.from(p)));
            assert.equal(wav.length,44+size);
            assert.equal(wav.toString('ascii',0,4),'RIFF');
            assert.equal(wav.readUInt32LE(4),36+size);
            assert.equal(wav.toString('ascii',8,16),'WAVEfmt ');
            assert.equal(wav.readUInt32LE(16),16);
            assert.equal(wav.readUInt16LE(20),1);
            assert.equal(wav.readUInt16LE(22),1);
            assert.equal(wav.readUInt32LE(24),16000);
            assert.equal(wav.readUInt32LE(28),32000);
            assert.equal(wav.readUInt16LE(32),2);
            assert.equal(wav.readUInt16LE(34),16);
            assert.equal(wav.toString('ascii',36,40),'data');
            assert.equal(wav.readUInt32LE(40),size);
            assert.deepEqual(wav.subarray(44),Buffer.from(pcm));
          }
          for(const failure of [1,2]) {
            writes=0;failAt=failure;const before=closed;
            assert.throws(()=>writeWav('capture.wav',new OriginalArrayBuffer(640)),/disk unavailable/);
            assert.equal(closed,before+1);
          }
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'streamed-wav.mts'
            harness.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True)

    def test_streamed_event_files_preserve_bytes_and_close_on_write_failure(self) -> None:
        sink = SINKS.read_text().split("export class NdjsonDiagnosticSink", 1)[1]
        sink = "export class NdjsonDiagnosticSink" + sink
        module = MODULE.read_text()
        writer = module[module.index("  private static writeEvents("):
                        module.index("  private static writeSnapshot(")]
        script = r"""
          import assert from 'node:assert/strict';
          import { createHash } from 'node:crypto';
          type DiagnosticEvent = object;
        """ + sink + r"""
          let closed=0, writes=0, fail=false, maximum=0, hash;
          const fs={OpenMode:{WRITE_ONLY:1,CREATE:2,TRUNC:4},
            openSync(){return {fd:7}},
            writeSync(fd,value,options){
              assert.equal(fd,7);writes++;
              if(fail)throw new Error('disk unavailable');
              const bytes=Buffer.from(value).subarray(0,options.length);
              maximum=Math.max(maximum,bytes.length);hash.update(bytes);return bytes.length;
            }, closeSync(fp){assert.equal(typeof fp==='number'?fp:fp.fd,7);closed++}};
          class DiagnosticsModule {
            static eventJournal = {write(events,append,asArray){
              new NdjsonDiagnosticSink().write(events,text=>{
                const bytes=new TextEncoder().encode(text);append(bytes.buffer,bytes.length);
              },asArray);
            }};
        """ + writer.replace('private static', 'static') + r"""
          }
          const events=Array.from({length:1000},(_,i)=>({sequence:i,event:'WINDOW',
            fields:{text:'中文 / English \" \n',scores:Array.from({length:768},(_,j)=>(i+j)/997)}}));
          for(const values of [[],events.slice(0,1),events])for(const asArray of [false,true]) {
            hash=createHash('sha256');maximum=0;
            const before=closed;
            DiagnosticsModule.writeEvents('trace',values,asArray);
            const expected=asArray?JSON.stringify(values)+'\n':values.map(e=>JSON.stringify(e)+'\n').join('');
            assert.equal(hash.digest('hex'),createHash('sha256').update(expected).digest('hex'));
            assert.equal(closed,before+1);
            assert.ok(maximum<64*1024,'temporary encoding must remain bounded by one event');
          }
          const tensor=new Float32Array([0,1,-0,NaN,Infinity,-Infinity,Math.fround(1/3)]);
          const compact=[{sequence:1001,event:'WINDOW',fields:{segmentations:tensor,embeddings:tensor.slice()}}];
          const plain=[{sequence:1001,event:'WINDOW',fields:{segmentations:Array.from(tensor),embeddings:Array.from(tensor)}}];
          for(const asArray of [false,true]) {
            hash=createHash('sha256');
            DiagnosticsModule.writeEvents('tensor-trace',compact,asArray);
            const expected=asArray?JSON.stringify(plain)+'\n':plain.map(e=>JSON.stringify(e)+'\n').join('');
            assert.equal(hash.digest('hex'),createHash('sha256').update(expected).digest('hex'),
              'compact tensors must retain the flat array schema and every raw numeric score');
          }
          fail=true;const before=closed;
          assert.throws(()=>DiagnosticsModule.writeEvents('trace',events),/disk unavailable/);
          assert.equal(closed,before+1,'write failure must still release the file');
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'streamed-events.mts'
            harness.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True)

    def test_disabled_core_has_no_capture_or_event_overhead(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            const engine = core.nextEngineId();
            core.beginSession('session', engine, {});
            core.captureAudio('session', new ArrayBuffer(640));
            core.record('session', engine, 'CALLBACK_RESULT', { isLast: true });
            const snapshot = core.snapshot();
            assert.equal(snapshot.runId, '');
            assert.deepEqual(snapshot.events, []);
            assert.deepEqual(snapshot.sessions, []);
            """
        )

    def test_reused_customer_session_id_keeps_both_diagnostic_sessions(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'CUSTOMER_SUPPORT', captureAudio: false,
              includeRecognitionText: false, maxSessionAudioSec: 120 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('reused', engine, {}, 1010);
            core.record('reused', engine, 'CALLBACK_COMPLETE', {}, 1020);
            core.beginSession('reused', engine, {}, 1030);
            const sessions = core.snapshot().sessions;
            assert.equal(sessions.length, 2);
            assert.equal(sessions[0].sessionId, 'session-1');
            assert.equal(sessions[1].sessionId, 'session-2');
            """
        )

    def test_adapter_keeps_file_io_out_of_write_audio(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        module = MODULE.read_text(encoding="utf-8")
        write_start = adapter.index("  writeAudio(sessionId: string, audio: ArrayBuffer): void {")
        write_end = adapter.index("\n  setSpeakerVadEnabled", write_start)
        write_body = adapter[write_start:write_end]
        self.assertIn("DiagnosticsModule.captureAudio(sessionId, audio)", write_body)
        self.assertNotIn("fs.", write_body)
        self.assertIn("static export(): string", module)
        self.assertIn("sdk-input.wav", module)
        self.assertIn("metadata['includesInternalReplay'] = false", module)
        self.assertIn("fs.writeSync(fp.fd, value)", module)
        self.assertNotIn("new util.TextEncoder", module)

    def test_diagnostics_build_is_the_single_full_capture_switch(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("import { BUILD_MODE_NAME }", module)
        self.assertIn("return buildModeName === 'diagnostics'", module)
        self.assertIn("enabled: true", module)
        self.assertIn("mode: DiagnosticModeValue.CUSTOMER_SUPPORT", module)
        self.assertIn("captureAudio: true", module)
        self.assertIn("includeRecognitionText: true", module)
        self.assertIn("maxSessionAudioSec: 300", module)
        compatibility_method = adapter.split(
            "static configureDiagnostics(_options: DiagnosticOptions): void {", 1
        )[1].split("}", 1)[0]
        self.assertNotIn("DiagnosticsModule.configure", compatibility_method)
        self.assertIn("@deprecated", MODELS.read_text(encoding="utf-8"))
        self.assertIn("JOURNAL_INTERVAL_MS", module)
        self.assertIn("crash-recovery.json", module)
        self.assertIn("maxDirectoryBytes", module)
        self.assertIn("maxRetainedRuns", module)
        self.assertIn("resource-samples.csv", module)
        self.assertIn("native-state.json", module)
        self.assertIn("deliveredManifest", module)
        self.assertIn('"name": "diagnostics"', SDK_BUILD_PROFILE.read_text(encoding="utf-8"))
        self.assertIn('"name": "diagnostics"', DELIVERY_BUILD_PROFILE.read_text(encoding="utf-8"))

    def test_basic_forces_private_payloads_off(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'BASIC', captureAudio: true,
              includeRecognitionText: true, maxSessionAudioSec: 120 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('session', engine, {}, 1010);
            core.captureAudio('session', new ArrayBuffer(640), 1020);
            core.record('session', engine, 'CALLBACK_RESULT', { text: 'private' }, 1030);
            const snapshot = core.snapshot();
            assert.equal(snapshot.config.captureAudio, false);
            assert.equal(snapshot.config.includeRecognitionText, false);
            assert.equal(snapshot.sessions[0].audio, undefined);
            assert.deepEqual(snapshot.events[1].fields, {});
            """
        )

    def test_failure_only_retains_only_abnormal_sessions_and_ring_audio(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'FAILURE_ONLY', captureAudio: true,
              includeRecognitionText: false, maxSessionAudioSec: 3,
              failureRingAudioSec: 1, maxSessionEvents: 64 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('normal', engine, {}, 1010);
            core.record('normal', engine, 'FINISH_REQUESTED', {}, 1020);
            core.record('normal', engine, 'CALLBACK_COMPLETE', {}, 1030);
            assert.equal(core.snapshot().sessions.length, 0);

            core.beginSession('bad', engine, {}, 1040);
            for (let i = 0; i < 60; i++) {
              core.captureAudio('bad', new ArrayBuffer(640), 1050 + i * 20);
            }
            assert.equal(core.snapshot().sessions.length, 0);
            assert.equal(core.snapshot(true).sessions.length, 1);
            core.record('bad', engine, 'CALLBACK_ERROR', { nativeErrorCode: 7 }, 2300);
            const bad = core.snapshot().sessions[0];
            assert.equal(bad.abnormal, true);
            assert.deepEqual(bad.abnormalReasons, ['callback-error']);
            assert.equal(bad.audio.ringBuffer, true);
            assert.equal(bad.audio.durationMs, 1000);
            assert.equal(bad.audio.preTriggerDroppedBytes, 6400);
            assert.equal(bad.audio.rollingDroppedBytes, 0);
            """
        )

    def test_failure_only_detects_empty_final_and_early_last(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'FAILURE_ONLY', captureAudio: false,
              includeRecognitionText: false, maxSessionAudioSec: 120 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('empty', engine, {}, 1010);
            core.record('empty', engine, 'CALLBACK_RESULT',
              { isFinal: true, isLast: true, textChars: 0 }, 1020);
            const session = core.snapshot().sessions[0];
            assert.deepEqual(session.abnormalReasons, ['empty-final']);
            """
        )

    def test_finished_session_ignores_empty_last_flush_after_nonempty_final(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'CUSTOMER_SUPPORT', captureAudio: false,
              includeRecognitionText: true, maxSessionAudioSec: 300 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('continuous', engine, {}, 1010);
            core.record('continuous', engine, 'CALLBACK_RESULT',
              { isFinal: true, isLast: false, textChars: 7, text: '请给文赋成发。' }, 1020);
            core.record('continuous', engine, 'FINISH_REQUESTED', {}, 1030);
            core.record('continuous', engine, 'CALLBACK_RESULT',
              { isFinal: true, isLast: true, textChars: 0, text: '' }, 1040);
            core.record('continuous', engine, 'CALLBACK_COMPLETE', {}, 1050);

            const session = core.snapshot().sessions[0];
            assert.equal(session.abnormal, false);
            assert.deepEqual(session.abnormalReasons, []);
            assert.equal(session.terminal, true);
            """
        )

    def test_finished_session_still_flags_empty_last_without_nonempty_final(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'CUSTOMER_SUPPORT', captureAudio: false,
              includeRecognitionText: false, maxSessionAudioSec: 300 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('silent', engine, {}, 1010);
            core.record('silent', engine, 'FINISH_REQUESTED', {}, 1020);
            core.record('silent', engine, 'CALLBACK_RESULT',
              { isFinal: true, isLast: true, textChars: 0 }, 1030);
            core.record('silent', engine, 'CALLBACK_COMPLETE', {}, 1040);

            const session = core.snapshot().sessions[0];
            assert.equal(session.abnormal, true);
            assert.deepEqual(session.abnormalReasons, ['empty-final']);
            """
        )

    def test_audio_statistics_match_retained_pcm_after_partial_trims_and_trigger(self) -> None:
        self.run_core(
            """
            for (const mode of ['CUSTOMER_SUPPORT', 'FAILURE_ONLY']) {
              const core = new DiagnosticsCore();
              core.configure({enabled:true,mode,captureAudio:true,includeRecognitionText:false,
                maxSessionAudioSec:2,failureRingAudioSec:1},1000);
              const engine=core.nextEngineId();core.beginSession('s',engine,{},1000);
              let expected=[],triggered=mode==='CUSTOMER_SUPPORT',position=0;
              const pattern=[32767,-32768,0,1000,-1234,7];
              for (const length of [11003,9999,7013,9001,27007]) {
                const pcm=Int16Array.from({length},()=>pattern[position++%pattern.length]);
                expected.push(...pcm);
                expected=expected.slice(-(triggered?32000:16000));
                core.captureAudio('s',pcm.buffer,1000+position);
                pcm.fill(0); // A caller-owned buffer can be reused immediately.
                const audio=core.snapshot(true).sessions[0].audio;
                assert.deepEqual(Array.from(new Int16Array(audio.pcm)),expected);
                const energy=expected.reduce((sum,value)=>sum+value*value,0);
                const peak=Math.max(...expected.map(Math.abs));
                const clipped=expected.filter(value=>Math.abs(value)>=32767).length;
                assert.equal(audio.rms,Math.sqrt(energy/expected.length)/32768);
                assert.equal(audio.peak,peak/32768);
                assert.equal(audio.clipRate,clipped/expected.length);
                assert.deepEqual(core.snapshot(true).sessions[0].audio,audio);
                if(position>16000&&!triggered){
                  core.record('s',engine,'CALLBACK_ERROR',{},1000+position);triggered=true;
                }
              }
            }
            """
        )

    def test_event_ring_is_bounded_without_losing_final_classification_state(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, mode: 'CUSTOMER_SUPPORT', captureAudio: false,
              includeRecognitionText: false, maxSessionAudioSec: 300,
              maxSessionEvents: 64 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('long', engine, {}, 1010);
            core.record('long', engine, 'CALLBACK_RESULT',
              { isFinal: true, isLast: false, textChars: 3 }, 1020);
            core.record('long', engine, 'FINISH_REQUESTED', {}, 1030);
            for (let i = 0; i < 80; i++) {
              core.record('long', engine, 'AUDIO_PROGRESS', { frames: i }, 1040 + i);
            }
            core.record('long', engine, 'CALLBACK_RESULT',
              { isFinal: true, isLast: true, textChars: 0 }, 1200);
            core.record('long', engine, 'CALLBACK_COMPLETE', {}, 1210);

            const session = core.snapshot().sessions[0];
            assert.ok(session.events.length <= 64);
            assert.equal(session.abnormal, false);
            assert.deepEqual(session.abnormalReasons, []);
            """
        )

    def test_summary_uses_core_empty_final_classification(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn(
            "const emptyFinal = session.abnormalReasons.indexOf('empty-final') >= 0;",
            module,
        )

    def test_crash_recovery_preserves_full_journal_with_the_latest_pending_snapshot(self) -> None:
        from asr.tools.tests.test_harmony_speaker_inference_threading import method_body

        module = MODULE.read_text(encoding="utf-8")
        body = method_body(module.replace("private static ", "private "), "recoverCrashJournals")
        script = f"""
            import assert from 'node:assert/strict';
            import fs from 'node:fs';
            fs.accessSync = fs.existsSync;
            fs.listFileSync = fs.readdirSync;
            const JOURNAL_INTERVAL_MS = 5000;
            const isDirectory = path => fs.statSync(path).isDirectory();
            const removeTree = path => fs.rmSync(path, {{recursive:true,force:true}});
            const writeText = (path,text) => fs.writeFileSync(path,text);
            class DiagnosticsModule {{
              static rootPath = '.';
              static exportRoot() {{ return './asr-diagnostics'; }}
              static markRecoveredCrash() {{}}
              static rotateRuns() {{}}
              static recoverCrashJournals() {{ {body} }}
            }}
            for (const path of ['asr-diagnostics/run-1', 'asr-diagnostics-pending/run-1',
              'asr-diagnostics-pending/run-1.next']) fs.mkdirSync(path,{{recursive:true}});
            const bytes = 'full history before the retained window\\n中文\\n';
            writeText('asr-diagnostics/run-1/events.full.ndjson',bytes);
            writeText('asr-diagnostics-pending/run-1/manifest.json','old');
            writeText('asr-diagnostics-pending/run-1.next/manifest.json','new');
            writeText('asr-diagnostics-pending/run-1.next/events.ndjson','latest window');
            DiagnosticsModule.recoverCrashJournals();
            assert.equal(fs.readFileSync('asr-diagnostics/run-1/events.full.ndjson','utf8'),bytes);
            assert.equal(fs.readFileSync('asr-diagnostics/run-1/events.ndjson','utf8'),'latest window');
            assert.equal(fs.readFileSync('asr-diagnostics/run-1/manifest.json','utf8'),'new');
            assert.equal(JSON.parse(fs.readFileSync('asr-diagnostics/run-1/crash-recovery.json')).possibleTailLossMs,5000);
            assert.deepEqual(fs.readdirSync('asr-diagnostics-pending'),[]);
        """
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "recovery.mts"
            entry.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run(["node", "--experimental-strip-types", str(entry)], check=True, cwd=directory)

    def test_journal_materializes_retained_audio_once_without_changing_evidence(self) -> None:
        from asr.tools.tests.test_harmony_speaker_inference_threading import method_body

        module = MODULE.read_text(encoding="utf-8")
        body = method_body(module.replace("private static ", "private "), "flushBackground")
        filter_function = module[
            module.index("function snapshotWithSessions(") : module.index("/** File adapter.")
        ]
        script = f"""
            import assert from 'node:assert/strict';
            import {{ DiagnosticsCore, DiagnosticModeValue }} from {CORE.as_uri()!r};
            import type {{ DiagnosticsSnapshot, DiagnosticSessionSnapshot,
              DiagnosticEvent }} from {CORE.as_uri()!r};
            {filter_function}
            const fs = {{ accessSync: () => false, renameSync: () => {{}} }};
            const ensureDirectory = () => {{}};
            const removeTree = () => {{}};
            const sampleResources = () => ({{}});
            const writes = [];
            class DiagnosticsModule {{
              static core;
              static resourceSamples = [];
              static lastTerminalExportSequence = -1;
              static persistEvents() {{}}
              static exportRoot() {{ return 'export'; }}
              static pendingRoot() {{ return 'pending'; }}
              static rotateRuns() {{}}
              static writeSnapshot(path, snapshot, automatic) {{
                writes.push({{path, snapshot: structuredClone(snapshot), automatic}});
              }}
              static flushBackground() {{ {body} }}
            }}
            for (const mode of ['BASIC', 'CUSTOMER_SUPPORT', 'FAILURE_ONLY']) {{
              const core = new DiagnosticsCore();
              core.configure({{enabled: true, mode, captureAudio: true,
                includeRecognitionText: true, maxSessionAudioSec: 300}}, 1000);
              DiagnosticsModule.core = core;
              DiagnosticsModule.lastTerminalExportSequence = -1;
              const engine = core.nextEngineId();
              core.beginSession('active', engine, {{}}, 1000);
              const pcm = Int16Array.from({{length: 16000}}, (_, i) => i % 30000);
              core.captureAudio('active', pcm.buffer, 1000);
              const snapshot = core.snapshot.bind(core);
              let persistedExport;
              for (let stage = 0; stage < 4; stage++) {{
                if (stage === 1) {{
                  core.beginSession('normal', engine, {{}}, 1100);
                  core.captureAudio('normal', pcm.buffer, 1100);
                  core.record('normal', engine, 'CANCEL_REQUESTED', {{}}, 1110);
                }}
                if (stage === 2) {{
                  core.beginSession('failed', engine, {{}}, 1200);
                  core.captureAudio('failed', pcm.buffer, 1200);
                  core.record('failed', engine, 'CALLBACK_ERROR', {{}}, 1210);
                }}
                if (stage === 3) core.record('active', engine, 'CANCEL_REQUESTED', {{}}, 1300);
                const journal = snapshot(true);
                const completed = mode === 'CUSTOMER_SUPPORT' ?
                  snapshotWithSessions(journal, journal.sessions.filter(s => s.terminal)) : snapshot(false);
                const expectedPending = snapshotWithSessions(journal,
                  journal.sessions.filter(s => !s.terminal));
                const persist = mode === 'CUSTOMER_SUPPORT' ?
                  completed.sessions.some(s => s.terminal) : completed.sessions.length > 0;
                const retainedBytes = journal.sessions.reduce((n, s) => n + (s.audio?.bytes ?? 0), 0);
                let materializedBytes = 0;
                core.snapshot = (pending = false) => {{
                  const value = snapshot(pending);
                  materializedBytes += value.sessions.reduce((n, s) => n + (s.audio?.bytes ?? 0), 0);
                  return value;
                }};
                writes.length = 0;
                DiagnosticsModule.flushBackground();
                const exported = writes.find(w => w.path.startsWith('export/'));
                const pending = writes.find(w => w.path.startsWith('pending/'));
                if (exported) persistedExport = exported;
                assert.equal(Boolean(persistedExport), persist);
                if (persist) assert.deepEqual(persistedExport.snapshot, completed);
                assert.equal(Boolean(pending), expectedPending.sessions.length > 0);
                if (pending) assert.deepEqual(pending.snapshot, expectedPending);
                assert.ok(materializedBytes <= retainedBytes,
                  `${{mode}} stage=${{stage}} copied ${{materializedBytes}} retained=${{retainedBytes}}`);
                if (mode === 'CUSTOMER_SUPPORT') {{
                  writes.length = 0;
                  DiagnosticsModule.flushBackground();
                  assert.equal(writes.filter(w => w.path.startsWith('export/')).length, 0,
                    'unchanged completed session was exported again');
                  if (stage === 1) {{
                    core.record('normal', engine, 'DIARIZATION_LOCAL_CLOSED', {{liveSessions:0}}, 1150);
                    writes.length = 0;
                    DiagnosticsModule.flushBackground();
                    const updated = writes.find(w => w.path.startsWith('export/'));
                    assert.ok(updated, 'late terminal cleanup evidence was lost');
                    assert.equal(updated.snapshot.sessions[0].events.at(-1).event, 'DIARIZATION_LOCAL_CLOSED');
                    persistedExport = updated;
                  }}
                }}
              }}
            }}
        """
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "journal.mts"
            entry.write_text(textwrap.dedent(script), encoding="utf-8")
            subprocess.run(["node", "--experimental-strip-types", str(entry)],
                           check=True, cwd=REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
