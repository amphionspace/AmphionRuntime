import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/VoiceprintCapability.ts"
)
SDK = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonyVoiceprintCapabilityTest(unittest.TestCase):
    def test_voiceprint_ids_preconfigure_runtime_capability(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ hasVoiceprintCapability }} from {CAPABILITY.as_uri()!r};

            assert.equal(hasVoiceprintCapability(false, false, 0), false);
            assert.equal(hasVoiceprintCapability(true, false, 0), true);
            assert.equal(hasVoiceprintCapability(false, true, 0), true);
            assert.equal(hasVoiceprintCapability(false, false, 1), true);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_adapter_reserves_initial_silence_grace_for_capable_session(self) -> None:
        source = SDK.read_text(encoding="utf-8")
        self.assertIn(
            "hasVoiceprintCapability(verify, speakerVad, voiceprintIds.length)",
            source,
        )
        self.assertIn(
            "buildSessionConfig(params, configureTarget, configureTarget)",
            source,
        )
        self.assertNotIn(
            "buildSessionConfig(params, configureTarget, verify || speakerVad)",
            source,
        )

    def test_core_caps_requested_grace_at_target_minimum_segment(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn(
            "Math.round(config.targetSpeaker.minSegSec * 1000)",
            source,
        )
        self.assertIn(
            "Math.min(\n      requestedConfirmationGraceMs, maxConfirmationGraceMs)",
            source,
        )


if __name__ == "__main__":
    unittest.main()
