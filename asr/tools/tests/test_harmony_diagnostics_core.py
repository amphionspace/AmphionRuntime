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
MODULE = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DiagnosticsModule.ets"
)


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

    def test_audio_is_exactly_the_validated_public_input_and_is_bounded(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, captureAudio: true,
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
            """
        )

    def test_sensitive_fields_are_default_redacted_and_text_is_opt_in(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, captureAudio: false,
              includeRecognitionText: false, maxSessionAudioSec: 120 }, 1000);
            const engine = core.nextEngineId();
            core.beginSession('real-session', engine, {}, 1010);
            core.record('real-session', engine, 'CALLBACK_RESULT', {
              text: 'sensitive text', tokens: 'secret token', hotwords: 'person name',
              voiceprintIds: 'secret-id', licenseText: 'private-key', isLast: true
            }, 1020);
            const event = core.snapshot().events[1];
            assert.deepEqual(event.fields, { isLast: true });
            assert.equal(event.sessionId, 'session-1');

            const withText = new DiagnosticsCore();
            withText.configure({ enabled: true, captureAudio: false,
              includeRecognitionText: true, maxSessionAudioSec: 120 }, 2000);
            const secondEngine = withText.nextEngineId();
            withText.beginSession('real-session', secondEngine, {}, 2010);
            withText.record('real-session', secondEngine, 'CALLBACK_RESULT', {
              text: 'allowed', hotwords: 'still-secret'
            }, 2020);
            assert.deepEqual(withText.snapshot().events[1].fields, { text: 'allowed' });
            """
        )

    def test_disabled_core_has_no_capture_or_event_overhead(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            const engine = core.nextEngineId();
            core.beginSession('session', engine, {});
            core.captureAudio('session', new ArrayBuffer(640));
            core.record('session', engine, 'CALLBACK_RESULT', { isLast: true });
            assert.deepEqual(core.snapshot(), { runId: '', events: [], sessions: [] });
            """
        )

    def test_reused_customer_session_id_keeps_both_diagnostic_sessions(self) -> None:
        self.run_core(
            """
            const core = new DiagnosticsCore();
            core.configure({ enabled: true, captureAudio: false,
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


if __name__ == "__main__":
    unittest.main()
