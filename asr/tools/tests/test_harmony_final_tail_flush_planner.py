import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PLANNER = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/FinalTailFlushPlanner.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
ANDROID_SESSION = (
    REPO_ROOT / "asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt"
)
SHERPA_PATCH = (
    REPO_ROOT
    / "third_party/patches/sherpa-amphion/"
    "0026-feat-harmony-decode-one-online-chunk-asynchronously.patch"
)
SHERPA_ASYNC_PATCH = (
    REPO_ROOT
    / "third_party/patches/sherpa-amphion/"
    "0013-feat-harmony-decode-online-streams-asynchronously.patch"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonyFinalTailFlushPlannerTest(unittest.TestCase):
    def run_planner(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ FinalTailFlushPlanner }} from {PLANNER.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                TS_LOADER.as_uri(),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_all_20ms_chunk_phases_receive_two_decode_opportunities(self) -> None:
        self.run_planner(
            """
            for (let phaseMs = 0; phaseMs < 640; phaseMs += 20) {
              const planner = new FinalTailFlushPlanner(20, 1280, 2);
              let readyAudioMs = phaseMs;
              while (!planner.isComplete()) {
                if (readyAudioMs >= 640) {
                  readyAudioMs -= 640;
                  planner.recordDecode();
                  continue;
                }
                const paddingMs = planner.nextPaddingMs();
                assert.ok(paddingMs > 0);
                planner.recordPadding(paddingMs);
                readyAudioMs += paddingMs;
              }
              assert.equal(planner.decodeOpportunities(), 2);
              assert.equal(planner.paddingDurationMs(), 1280 - phaseMs);
              assert.equal(planner.usedFallback(), false);
            }
            """
        )

    def test_never_ready_stops_at_the_existing_1280ms_cap(self) -> None:
        self.run_planner(
            """
            const planner = new FinalTailFlushPlanner(20, 1280, 2);
            while (!planner.isComplete()) {
              const paddingMs = planner.nextPaddingMs();
              if (paddingMs === 0) break;
              planner.recordPadding(paddingMs);
            }
            assert.equal(planner.paddingDurationMs(), 1280);
            assert.equal(planner.decodeOpportunities(), 0);
            assert.equal(planner.usedFallback(), true);
            """
        )

    def test_adaptive_flush_is_asr_only_and_follows_speaker_turn_commit(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        async_stop = source.split("private async stopNowAsync", 1)[1].split(
            "updateHotwords", 1
        )[0]
        self.assertLess(
            async_stop.index("commitSpeakerTurnAtFinishAsync"),
            async_stop.index("flushAdaptiveFinalTailAsync"),
        )
        self.assertLess(
            async_stop.index("if (this.speakerVadEnabled)"),
            async_stop.index("flushAdaptiveFinalTailAsync"),
        )
        self.assertIn("this.appendFinalTailSilence()", async_stop)

        helper = source.split("private async flushAdaptiveFinalTailAsync", 1)[1].split(
            "private ", 1
        )[0]
        self.assertIn("appendFinalTailSilence", helper)
        self.assertIn("decodeOneAsync", helper)
        self.assertNotIn("speakerPcmBuffers", helper)
        self.assertNotIn("effectiveSpeechBuffer", helper)
        self.assertNotIn("speakerTurnFinalizer", helper)

        clean_turn = source.split("private async commitCleanSpeakerTurnAsync", 1)[1].split(
            "setTargetSpeaker", 1
        )[0]
        self.assertIn("this.appendFinalTailSilence()", clean_turn)
        self.assertNotIn("flushAdaptiveFinalTail", clean_turn)

    def test_android_adaptive_flush_also_bypasses_speaker_pcm(self) -> None:
        source = ANDROID_SESSION.read_text(encoding="utf-8")
        stop = source.split("fun stop()", 1)[1].split("fun close()", 1)[0]
        self.assertLess(stop.index("agcIngress.flush"), stop.index("flushAdaptiveFinalTail()"))
        self.assertLess(stop.index("if (speakerVadEnabled)"), stop.index("flushAdaptiveFinalTail()"))
        self.assertIn("appendFinalTailSilence(FINAL_TAIL_SILENCE_MS)", stop)

        helper = source.split("private fun flushAdaptiveFinalTail()", 1)[1].split(
            "private fun", 1
        )[0]
        self.assertIn("appendFinalTailSilence", helper)
        self.assertIn("recognizer.decode(stream)", helper)
        self.assertNotIn("speakerPcmBuffers", helper)
        self.assertNotIn("effectiveSpeechBuffer", helper)
        self.assertNotIn("speakerVad", helper)

    def test_single_chunk_async_decode_keeps_native_leases_and_rechecks_ready(self) -> None:
        patch = SHERPA_PATCH.read_text(encoding="utf-8")
        leased_worker = SHERPA_ASYNC_PATCH.read_text(encoding="utf-8") + patch
        self.assertIn("recognizer_handle->Lease()", leased_worker)
        self.assertIn("stream_handle->Lease()", leased_worker)
        self.assertIn("decodeOneOnlineStreamAsync", patch)
        self.assertIn("Online stream is not ready for a single decode", patch)
        self.assertIn("StartDecodeOnlineStreamAsync(info, false)", patch)


if __name__ == "__main__":
    unittest.main()
