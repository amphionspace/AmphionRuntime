import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/ColdStartPttGate.ts"
)
DEMO = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets"
)


class HarmonyColdStartPttGateTest(unittest.TestCase):
    def run_gate(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ ColdStartPttGate }} from {GATE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_release_before_engine_ready_starts_then_finishes_after_flush(self) -> None:
        self.run_gate(
            """
            const gate = new ColdStartPttGate();
            const generation = gate.begin();
            assert.equal(gate.release(generation), true);
            assert.equal(gate.captureStopped(generation), false);
            assert.deepEqual(gate.engineReady(generation), {
              accepted: true,
              finishAfterFlush: true,
            });
            """
        )

    def test_engine_ready_first_waits_for_capture_tail_before_finish(self) -> None:
        self.run_gate(
            """
            const gate = new ColdStartPttGate();
            const generation = gate.begin();
            assert.equal(gate.release(generation), true);
            assert.deepEqual(gate.engineReady(generation), {
              accepted: true,
              finishAfterFlush: false,
            });
            assert.equal(gate.captureStopped(generation), true);
            """
        )

    def test_stale_engine_completion_is_rejected(self) -> None:
        self.run_gate(
            """
            const gate = new ColdStartPttGate();
            const stale = gate.begin();
            gate.cancel();
            const current = gate.begin();
            assert.deepEqual(gate.engineReady(stale), {
              accepted: false,
              finishAfterFlush: false,
            });
            assert.deepEqual(gate.engineReady(current), {
              accepted: true,
              finishAfterFlush: false,
            });
            """
        )

    def test_demo_preserves_pre_roll_when_ptt_is_released_during_load(self) -> None:
        demo = DEMO.read_text(encoding="utf-8")
        self.assertIn("this.coldStartPttGate.release(coldStartGeneration)", demo)
        self.assertIn("this.coldStartPttGate.captureStopped(coldStartGeneration)", demo)
        self.assertIn("this.startSessionAndFlush(decision.finishAfterFlush)", demo)
        self.assertNotIn("'已取消（模型未加载完成）'", demo)


if __name__ == "__main__":
    unittest.main()
