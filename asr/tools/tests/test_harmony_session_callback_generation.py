import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SDK = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)


class HarmonySessionCallbackGenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SDK.read_text(encoding="utf-8")
        cls.callback_source = cls.source.split("class DingqiaoAsrCallback", 1)[1]

    def test_every_native_callback_forwards_its_session_generation(self) -> None:
        expected_calls = (
            "handleSpeechBegin(this.startGeneration)",
            "handleInitialSilenceTimeout(this.startGeneration)",
            "handlePartial(this.startGeneration, text)",
            "handleEndpoint(this.startGeneration)",
            "handleFinalResult(this.startGeneration, result)",
            "handleFinalRejected(this.startGeneration, result)",
            "handleAsrError(this.startGeneration, error)",
            "handleSessionStarted(this.startGeneration)",
            "handleSessionStopped(this.startGeneration)",
        )
        for call in expected_calls:
            with self.subTest(call=call):
                self.assertIn(call, self.callback_source)

    def test_all_native_handlers_reject_a_stale_generation(self) -> None:
        handlers = (
            "handleSpeechBegin",
            "handleInitialSilenceTimeout",
            "handlePartial",
            "handleEndpoint",
            "handleFinalResult",
            "handleFinalRejected",
            "handleAsrError",
            "handleSessionStarted",
            "handleSessionStopped",
        )
        for name in handlers:
            with self.subTest(handler=name):
                match = re.search(
                    rf"(?:private )?{name}\([^)]*generation: number[^)]*\): void \{{(.{{0,280}})",
                    self.source,
                    re.DOTALL,
                )
                self.assertIsNotNone(match, f"{name} must accept a generation")
                self.assertIn("isCurrent(generation)", match.group(1))

    def test_write_audio_rechecks_ownership_after_native_reentry(self) -> None:
        match = re.search(
            r"writeAudio\(sessionId: string, audio: ArrayBuffer\): void \{(.*?)\n  \}\n\n  setSpeakerVadEnabled",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        accept_index = body.index("acceptPcmBytes(audio)")
        self.assertIn("currentGeneration()", body[:accept_index])
        self.assertLess(body.index("this.audioBytesWritten += audio.byteLength"), accept_index)
        self.assertIn("isCurrent(generation)", body[accept_index:])
        self.assertIn("this.session !== session", body[accept_index:])

    def test_terminal_handlers_recheck_generation_after_customer_listener(self) -> None:
        method_ranges = (
            ("private deliverFinal", "private completeCurrentSession"),
            ("handleFinalRejected", "handleAsrError"),
            ("handleSessionStopped", "private ensureAlive"),
        )
        for start, end in method_ranges:
            with self.subTest(handler=start):
                body = self.source.split(start, 1)[1].split(end, 1)[0]
                listener_index = body.rindex("this.listener?.onResult?")
                guard_index = body.index("isCurrent(generation)", listener_index)
                complete_index = body.index("completeCurrentSession(generation)", listener_index)
                self.assertLess(listener_index, guard_index)
                self.assertLess(guard_index, complete_index)

    def test_old_start_cleanup_cannot_reset_a_reentrant_replacement(self) -> None:
        body = self.source.split("startListening(params: StartParams): void", 1)[1].split(
            "writeAudio(sessionId: string", 1
        )[0]
        stale_cleanup = body.split("createdSession.close()", 1)[0].rsplit("if (", 1)[-1]
        self.assertIn("isCurrent(startGeneration)", stale_cleanup)

        catch_body = body.split("} catch (e) {", 1)[1]
        tear_down_index = catch_body.index("tearDownSession()")
        self.assertIn("isCurrent(startGeneration)", catch_body[:tear_down_index])
        error_index = catch_body.index("this.listener?.onError?")
        self.assertIn("if (!ownsFailedStart) return", catch_body[:error_index])


if __name__ == "__main__":
    unittest.main()
