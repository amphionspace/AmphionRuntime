import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RejectedFinalLifecycle.ts"
)
ADAPTER = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)


class HarmonyRejectedFinalLifecycleTest(unittest.TestCase):
    def test_only_last_rejected_final_completes_session(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ rejectedFinalCompletesSession }} from {POLICY.as_uri()!r};
            assert.equal(rejectedFinalCompletesSession(false), false);
            assert.equal(rejectedFinalCompletesSession(true), true);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_non_last_rejected_final_publishes_empty_final_without_completing(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        body = source.split("handleFinalRejected", 1)[1].split("handleAsrError", 1)[0]

        self.assertIn("payload.isFinal = true", body)
        self.assertIn("payload.isLast = result.isLast", body)
        self.assertIn("payload.result = ''", body)
        result_index = body.index("this.listener?.onResult?")
        completion_guard_index = body.index("if (rejectedFinalCompletesSession(result.isLast))")
        self.assertLess(result_index, completion_guard_index)


if __name__ == "__main__":
    unittest.main()
