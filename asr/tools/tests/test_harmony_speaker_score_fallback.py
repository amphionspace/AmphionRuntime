import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerScoreFallback.ts"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonySpeakerScoreFallbackTest(unittest.TestCase):
    def run_policy(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ selectSpeakerScoreSamples }} from {POLICY.as_uri()!r};
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

    def test_strict_samples_remain_the_primary_scoring_source(self) -> None:
        self.run_policy(
            """
            const strict = new Float32Array(24_000);
            const utterance = new Float32Array(64_000);
            const selected = selectSpeakerScoreSamples(strict, utterance, 24_000, true);
            assert.equal(selected.samples, strict);
            assert.equal(selected.source, 'strict');
            """
        )

    def test_asr_confirmed_long_utterance_falls_back_to_real_pcm(self) -> None:
        self.run_policy(
            """
            const strict = new Float32Array(8_000);
            const utterance = new Float32Array(64_000);
            const selected = selectSpeakerScoreSamples(strict, utterance, 24_000, true);
            assert.equal(selected.samples, utterance);
            assert.equal(selected.source, 'utterance');

            const exactThreshold = new Float32Array(24_000);
            const exact = selectSpeakerScoreSamples(strict, exactThreshold, 24_000, true);
            assert.equal(exact.samples, exactThreshold);
            assert.equal(exact.source, 'utterance');
            """
        )

    def test_short_or_unconfirmed_audio_does_not_fall_back(self) -> None:
        self.run_policy(
            """
            const strict = new Float32Array(8_000);
            const shortUtterance = new Float32Array(23_999);
            assert.equal(
              selectSpeakerScoreSamples(strict, shortUtterance, 24_000, true).source,
              'insufficient'
            );
            assert.equal(
              selectSpeakerScoreSamples(strict, new Float32Array(64_000), 24_000, false).source,
              'insufficient'
            );
            """
        )


if __name__ == "__main__":
    unittest.main()
