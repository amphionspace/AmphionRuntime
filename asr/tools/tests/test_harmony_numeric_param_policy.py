import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PARAM_POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/NumericParam.ts"
)
RECOGNITION_CONFIG = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RecognitionConfig.ets"
)


class HarmonyNumericParamPolicyTest(unittest.TestCase):
    def run_policy(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ finiteNumberParam }} from {PARAM_POLICY.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_blank_non_numeric_and_non_finite_values_are_absent(self) -> None:
        self.run_policy(
            """
            for (const value of ['', '   ', '\\t\\n', 'not-a-number', Number.NaN,
              Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, true, {}]) {
              assert.equal(finiteNumberParam({ value }, 'value'), undefined);
            }
            assert.equal(finiteNumberParam({}, 'value'), undefined);
            """
        )

    def test_finite_numbers_and_trimmed_numeric_strings_are_preserved(self) -> None:
        self.run_policy(
            """
            assert.equal(finiteNumberParam({ value: 0 }, 'value'), 0);
            assert.equal(finiteNumberParam({ value: -1.5 }, 'value'), -1.5);
            assert.equal(finiteNumberParam({ value: ' 25000 ' }, 'value'), 25000);
            assert.equal(finiteNumberParam({ value: '1e3' }, 'value'), 1000);
            """
        )

    def test_adapter_uses_the_shared_policy_for_optional_and_defaulted_params(self) -> None:
        config = RECOGNITION_CONFIG.read_text(encoding="utf-8")
        self.assertIn("return finiteNumberParam(params, key) ?? defaultValue;", config)
        self.assertIn("return finiteNumberParam(params, key);", config)


if __name__ == "__main__":
    unittest.main()
