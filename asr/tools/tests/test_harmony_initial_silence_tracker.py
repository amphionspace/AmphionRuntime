import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TRACKER = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/InitialSilenceTracker.ts"


class HarmonyInitialSilenceTrackerTest(unittest.TestCase):
    def run_tracker(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ InitialSilenceTracker }} from {TRACKER.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_text_evidence_permanently_disarms_timeout(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(500, 16000);
            assert.equal(tracker.observeVad(6400, false), false);
            tracker.observeAsrResult('hello', 0);
            assert.equal(tracker.observeVad(16000, false), false);
            assert.equal(tracker.hasTimedOut(), false);
            """
        )

    def test_token_only_evidence_permanently_disarms_timeout(self) -> None:
        self.run_tracker(
            """
            const tracker = new InitialSilenceTracker(500, 16000);
            assert.equal(tracker.observeVad(6400, false), false);
            tracker.observeAsrResult('', 1);
            assert.equal(tracker.observeVad(16000, false), false);
            assert.equal(tracker.hasTimedOut(), false);
            """
        )

    def test_silence_times_out_once_and_speech_wins_at_boundary(self) -> None:
        self.run_tracker(
            """
            const silence = new InitialSilenceTracker(500, 16000);
            assert.equal(silence.observeVad(8000, false), true);
            assert.equal(silence.observeVad(8000, false), false);

            const boundarySpeech = new InitialSilenceTracker(500, 16000);
            assert.equal(boundarySpeech.observeVad(8000, true), false);
            assert.equal(boundarySpeech.hasTimedOut(), false);
            """
        )


if __name__ == "__main__":
    unittest.main()
