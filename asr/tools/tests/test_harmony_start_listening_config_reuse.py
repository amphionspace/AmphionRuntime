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


if __name__ == "__main__":
    unittest.main()
