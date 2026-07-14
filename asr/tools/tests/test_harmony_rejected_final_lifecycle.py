import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RejectedFinalLifecycle.ts"
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


if __name__ == "__main__":
    unittest.main()
