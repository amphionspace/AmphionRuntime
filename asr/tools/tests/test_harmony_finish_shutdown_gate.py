import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/FinishShutdownGate.ts"
)
ADAPTER = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)


class HarmonyFinishShutdownGateTest(unittest.TestCase):
    def test_shutdown_during_finish_defers_release_until_session_settles(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ FinishShutdownGate }} from {GATE.as_uri()!r};

            const events = [];
            const gate = new FinishShutdownGate(() => events.push('release'));
            assert.equal(gate.request(true), true);
            assert.deepEqual(events, []);
            gate.settle();
            gate.settle();
            assert.deepEqual(events, ['release']);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_shutdown_without_pending_finish_releases_immediately(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ FinishShutdownGate }} from {GATE.as_uri()!r};

            const events = [];
            const gate = new FinishShutdownGate(() => events.push('release'));
            assert.equal(gate.request(false), false);
            gate.request(false);
            gate.settle();
            assert.deepEqual(events, ['release']);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_adapter_uses_gate_without_publishing_idle_before_complete(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("new FinishShutdownGate", adapter)
        self.assertIn("this.busy && this.finishRequested", adapter)
        self.assertIn("this.finishShutdownGate.settle()", adapter)
        self.assertIn("isBusy(): boolean { return this.busy; }", adapter)


if __name__ == "__main__":
    unittest.main()
