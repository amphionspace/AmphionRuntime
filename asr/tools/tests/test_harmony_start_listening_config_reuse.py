import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/EndpointRulePolicy.ts"
)
ADAPTER = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
RECOGNITION_CONFIG = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RecognitionConfig.ets"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonyStartListeningConfigReuseTest(unittest.TestCase):
    def test_target_speaker_change_does_not_change_recognizer_runtime_key(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ endpointRecognizerConfigKey,
              endpointRecognizerRuntimeConfigKey }} from {POLICY.as_uri()!r};

            const engine = {{ recognizerMode: 'short' }};
            const session = {{ endpointMaxUtteranceMs: 20000 }};
            const runtimeKey = endpointRecognizerRuntimeConfigKey(engine, session);

            assert.equal(runtimeKey,
              endpointRecognizerRuntimeConfigKey(engine, session));
            assert.notEqual(
              endpointRecognizerConfigKey(false, false, engine, session),
              endpointRecognizerConfigKey(true, true, engine, session),
            );
            assert.notEqual(runtimeKey,
              endpointRecognizerRuntimeConfigKey(engine,
                {{ recognizerMode: 'short', endpointMaxUtteranceMs: 60000 }}));
            assert.notEqual(runtimeKey,
              endpointRecognizerRuntimeConfigKey(engine,
                {{ recognizerMode: 'long', endpointMaxUtteranceMs: 20000 }}));
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                (REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs").as_uri(),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_adapter_reconfigures_target_without_reloading_recognizer(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        runtime = RUNTIME.read_text(encoding="utf-8")
        start = adapter.index("  private rebuildEngine(")
        end = adapter.index("\n  handlePartial(", start)
        rebuild = adapter[start:end]

        self.assertIn("endpointRecognizerRuntimeConfigKey", adapter)
        self.assertIn("reconfigureTargetSpeaker", rebuild)
        self.assertIn("AmphionRuntime.create", rebuild)
        self.assertLess(
            rebuild.index("reconfigureTargetSpeaker"),
            rebuild.index("AmphionRuntime.create"),
        )
        self.assertIn("reconfigureTargetSpeaker", runtime)
        reconfigure_start = runtime.index("  reconfigureTargetSpeaker(")
        reconfigure_end = runtime.index("\n  close(): void", reconfigure_start)
        reconfigure = runtime[reconfigure_start:reconfigure_end]
        self.assertIn("this.config = nextConfig", reconfigure)
        self.assertNotIn("this.config.targetSpeaker =", reconfigure)

    def test_speaker_vad_defers_extractor_without_losing_runtime_toggle(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        config = RECOGNITION_CONFIG.read_text(encoding="utf-8")
        runtime = RUNTIME.read_text(encoding="utf-8")

        config_start = config.index("function buildTargetSpeakerConfig(")
        config_end = config.index("\nfunction buildSpeakerVadConfig(", config_start)
        target_config = config[config_start:config_end]
        self.assertIn("cfg.deferLoad = true;", target_config)
        self.assertNotIn("cfg.deferLoad = !withSpeakerVad;", target_config)

        toggle_start = adapter.index("  setSpeakerVadEnabled(enabled: boolean): void {")
        toggle_end = adapter.index("\n  finish(sessionId: string)", toggle_start)
        adapter_toggle = adapter[toggle_start:toggle_end]
        self.assertIn("session.setSpeakerVadEnabled(enabled);", adapter_toggle)
        self.assertNotIn("session.ensureTargetSpeakerExtractor();", adapter_toggle)

        session_toggle_start = runtime.index("  setSpeakerVadEnabled(enabled: boolean): void {")
        session_toggle_end = runtime.index("\n  private ensureSpeakerTurnSegmenterLoad", session_toggle_start)
        session_toggle = runtime[session_toggle_start:session_toggle_end]
        self.assertIn("config.deferLoad", session_toggle)
        self.assertIn("getOrCreateSpeakerExtractorAsync", session_toggle)
        self.assertIn("setTargetSpeakerExtractorAsync", session_toggle)

        # Keep the lower-level Runtime opt-in fallback intact for callers that explicitly choose
        # synchronous loading by leaving deferLoad=false.
        new_session_start = runtime.index("  newSession(callback: AsrCallback")
        new_session_end = runtime.index("\n  isClosed(): boolean", new_session_start)
        new_session = runtime[new_session_start:new_session_end]
        self.assertIn("!this.config.targetSpeaker.deferLoad", new_session)
        self.assertIn("this.createSpeakerExtractor", new_session)


if __name__ == "__main__":
    unittest.main()
