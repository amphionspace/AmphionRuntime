import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioLimit.ts"
)
ADAPTER = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
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

    def test_positive_finite_values_are_capped_and_converted_to_pcm_bytes(self) -> None:
        self.run_policy(
            """
            const bytesPerMs = 32;
            assert.equal(maxAudioBytesOf({ maxAudioDuration: -1 }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: 0 }), 0);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: 0.001 }), 1);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: 8000 }), 8_000 * bytesPerMs);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: '25000' }), 25_000 * bytesPerMs);
            assert.equal(maxAudioBytesOf({ maxAudioDuration: 28_800_001 }), 28_800_000 * bytesPerMs);
            """
        )

    def test_adapter_checks_the_reserved_frame_without_cross_session_leakage(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        reserve = source.index("this.audioBytesWritten += audio.byteLength;")
        accept = source.index("session.acceptPcmBytes(audio);", reserve)
        generation = source.index("if (!this.sessionStartGate.isCurrent(generation)", accept)
        limit = source.index("this.audioBytesWritten >= this.maxAudioBytes", generation)
        stop = source.index("session.stop();", limit)

        self.assertLess(reserve, accept)
        self.assertLess(accept, generation)
        self.assertLess(generation, limit)
        self.assertLess(limit, stop)


if __name__ == "__main__":
    unittest.main()
