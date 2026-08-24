import subprocess
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


if __name__ == "__main__":
    unittest.main()
