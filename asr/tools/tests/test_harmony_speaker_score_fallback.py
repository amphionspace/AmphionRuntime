import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerScoreFallback.ts"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonySpeakerScoreFallbackTest(unittest.TestCase):
    def run_policy(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ selectSpeakerScoreSamples, speakerScoreSelectionDiagnostic }} from {POLICY.as_uri()!r};
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

    def test_unconfirmed_strict_audio_is_not_scored(self) -> None:
        self.run_policy(
            """
            const minimum = 24_000;
            const exactStrict = new Float32Array(minimum);
            const longStrict = new Float32Array(minimum + 16_000);
            assert.equal(
              selectSpeakerScoreSamples(exactStrict, new Float32Array(0), minimum, false).source,
              'insufficient'
            );
            assert.equal(
              selectSpeakerScoreSamples(longStrict, new Float32Array(0), minimum, false).source,
              'insufficient'
            );
            """
        )

    def test_diagnostic_explains_insufficient_selection(self) -> None:
        self.run_policy(
            """
            const selection = selectSpeakerScoreSamples(
              new Float32Array(16_000), new Float32Array(20_000), 24_000, false
            );
            assert.equal(
              speakerScoreSelectionDiagnostic(selection, 16_000, 20_000, 24_000, 16_000, false),
              'voiceprint score selection: source=insufficient effectiveSpeechMs=1000 ' +
                'utterancePcmMs=1250 minimumMs=1500 asrEvidence=false'
            );
            """
        )

    def test_runtime_correlates_score_diagnostic_with_session(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn(
            "Logger.d(`session ${this.sessionId} ` + speakerScoreSelectionDiagnostic(",
            source,
        )


if __name__ == "__main__":
    unittest.main()
