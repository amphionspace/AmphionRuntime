import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/AudioInfoValidation.ts"
)


class HarmonyAudioInfoValidationTest(unittest.TestCase):
    def run_policy(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ validateAudioInfo }} from {POLICY.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_invalid_sample_rate_returns_the_public_failure_message(self) -> None:
        self.run_policy(
            """
            assert.equal(validateAudioInfo({
              audioType: 'pcm', sampleRate: 8000, sampleBit: 16, soundChannel: 1,
            }), 'sampleRate must be 16000');
            """
        )

    def test_default_audio_info_is_accepted(self) -> None:
        self.run_policy(
            """
            assert.equal(validateAudioInfo({
              audioType: 'pcm', sampleRate: 16000, sampleBit: 16, soundChannel: 1,
            }), '');
            """
        )


if __name__ == "__main__":
    unittest.main()
