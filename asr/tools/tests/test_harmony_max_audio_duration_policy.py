import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioLimit.ts"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonyMaxAudioDurationPolicyTest(unittest.TestCase):
    def run_policy(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ maxAudioBytesOf }} from {POLICY.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                str(TS_LOADER),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_omission_and_invalid_values_disable_the_limit(self) -> None:
        self.run_policy(
            """
            assert.equal(maxAudioBytesOf({}), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: Number.NaN }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: Number.POSITIVE_INFINITY }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: Number.NEGATIVE_INFINITY }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: '' }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: '   ' }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: 'not-a-number' }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: true }), 0);
            """
        )

    def test_explicit_finite_values_are_clamped_and_converted_to_pcm_bytes(self) -> None:
        self.run_policy(
            """
            const bytesPerMs = 32;
            assert.equal(maxAudioBytesOf({ maxAudioDuration: -1 }), 20_000 * bytesPerMs);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: '25000' }), 25_000 * bytesPerMs);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: 28_800_001 }), 28_800_000 * bytesPerMs);
            """
        )


if __name__ == "__main__":
    unittest.main()
