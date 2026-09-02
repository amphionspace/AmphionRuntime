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
RECOGNITION_CONFIG = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RecognitionConfig.ets"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
TYPES = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets"
TARGET_CONFIG_POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/TargetSpeakerConfigPolicy.ts"
)


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

    def test_adapter_passes_configured_initial_confirmation_capability(self) -> None:
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

    def test_voiceprint_verification_is_score_only_in_customer_adapter(self) -> None:
        source = RECOGNITION_CONFIG.read_text(encoding="utf-8")
        target_config = source.split(
            "function buildTargetSpeakerConfig(", 1
        )[1].split("function buildSpeakerVadConfig", 1)[0]

        self.assertIn("cfg.threshold = -1.0", target_config)
        self.assertIn("cfg.minSegSec = 0", target_config)

    def test_target_speaker_minimum_defaults_to_zero_and_allows_zero(self) -> None:
        source = TYPES.read_text(encoding="utf-8")
        self.assertIn("minSegSec: number = 0;", source)
        self.assertIn("isValidSpeakerMinimumSegment(config.minSegSec)", source)
        self.assertIn("minSegSec must be finite and >= 0", source)
        self.assertNotIn("config.minSegSec <= 0", source)

    def test_target_speaker_minimum_requires_a_non_negative_finite_value(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ isValidSpeakerMinimumSegment }} from {TARGET_CONFIG_POLICY.as_uri()!r};

            assert.equal(isValidSpeakerMinimumSegment(0), true);
            assert.equal(isValidSpeakerMinimumSegment(1.5), true);
            assert.equal(isValidSpeakerMinimumSegment(-0.001), false);
            assert.equal(isValidSpeakerMinimumSegment(Number.NaN), false);
            assert.equal(isValidSpeakerMinimumSegment(Number.POSITIVE_INFINITY), false);
            assert.equal(isValidSpeakerMinimumSegment(Number.NEGATIVE_INFINITY), false);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )


if __name__ == "__main__":
    unittest.main()
