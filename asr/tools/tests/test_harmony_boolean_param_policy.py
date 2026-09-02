import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PARAM_POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/BooleanParam.ts"
)
ADAPTER = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
RECOGNITION_CONFIG = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RecognitionConfig.ets"
)


class HarmonyBooleanParamPolicyTest(unittest.TestCase):
    def run_policy(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ compatibleBooleanParam, strictBooleanParam }} from {PARAM_POLICY.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_false_representations_restore_prepack(self) -> None:
        self.run_policy(
            """
            for (const value of [false, 0, 'false', 'FALSE', '0']) {
              assert.equal(compatibleBooleanParam({ value }, 'value', true), false);
            }
            """
        )

    def test_true_representations_and_default_are_preserved(self) -> None:
        self.run_policy(
            """
            for (const value of [true, 1, -2, 'true', 'TRUE', '1']) {
              assert.equal(compatibleBooleanParam({ value }, 'value', false), true);
            }
            assert.equal(compatibleBooleanParam({}, 'value', true), true);
            assert.equal(compatibleBooleanParam({ value: {} }, 'value', true), true);
            for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
              assert.equal(compatibleBooleanParam({ value }, 'value', true), true);
            }
            """
        )

    def test_strict_policy_does_not_expand_voiceprint_flag_types(self) -> None:
        self.run_policy(
            """
            assert.equal(strictBooleanParam({ value: true }, 'value', false), true);
            for (const value of ['true', 1, {}, Number.NaN]) {
              assert.equal(strictBooleanParam({ value }, 'value', false), false);
            }
            """
        )

    def test_adapter_uses_compatible_policy_only_for_prepack(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        config = RECOGNITION_CONFIG.read_text(encoding="utf-8")
        self.assertIn(
            "import { strictBooleanParam } from './BooleanParam';",
            adapter,
        )
        self.assertIn(
            "import { compatibleBooleanParam } from './BooleanParam';",
            config,
        )
        self.assertIn(
            "config.disablePrepack = compatibleBooleanParam(params.extraParams, 'disablePrepack', true);",
            config,
        )
        self.assertIn(
            "const verify = strictBooleanParam(params.extraParams, 'enableVoiceprintVerification', false);",
            adapter,
        )
        self.assertIn(
            "const speakerVad = strictBooleanParam(params.extraParams, 'enableSpeakerVad', false);",
            adapter,
        )


if __name__ == "__main__":
    unittest.main()
