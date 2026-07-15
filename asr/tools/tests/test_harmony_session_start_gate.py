import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionStartGate.ts"
)


class HarmonySessionStartGateTest(unittest.TestCase):
    def run_gate(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionStartGate }} from {GATE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_synchronous_native_start_waits_for_session_publication(self) -> None:
        self.run_gate(
            """
            const gate = new SessionStartGate();
            const generation = gate.begin();
            let sessionPublished = false;
            let sessionConfigured = false;
            const callbacks = [];
            const deliver = () => {
              assert.equal(sessionPublished, true);
              assert.equal(sessionConfigured, true);
              callbacks.push('start');
            };

            if (gate.observeNativeStarted(generation)) deliver();
            assert.deepEqual(callbacks, []);
            sessionPublished = true;
            sessionConfigured = true;
            if (gate.publishSession(generation)) deliver();
            assert.deepEqual(callbacks, ['start']);
            """
        )

    def test_asynchronous_native_start_delivers_after_publication(self) -> None:
        self.run_gate(
            """
            const gate = new SessionStartGate();
            const generation = gate.begin();
            assert.equal(gate.publishSession(generation), false);
            assert.equal(gate.observeNativeStarted(generation), true);
            """
        )

    def test_duplicate_signals_deliver_once(self) -> None:
        self.run_gate(
            """
            const gate = new SessionStartGate();
            const generation = gate.begin();
            assert.equal(gate.observeNativeStarted(generation), false);
            assert.equal(gate.observeNativeStarted(generation), false);
            assert.equal(gate.publishSession(generation), true);
            assert.equal(gate.publishSession(generation), false);
            assert.equal(gate.observeNativeStarted(generation), false);
            """
        )

    def test_reset_discards_a_pending_native_start(self) -> None:
        self.run_gate(
            """
            const gate = new SessionStartGate();
            const oldGeneration = gate.begin();
            assert.equal(gate.observeNativeStarted(oldGeneration), false);
            gate.reset();
            assert.equal(gate.publishSession(oldGeneration), false);
            const generation = gate.begin();
            assert.equal(gate.publishSession(generation), false);
            assert.equal(gate.observeNativeStarted(generation), true);
            """
        )

    def test_late_started_signal_cannot_unlock_the_next_session(self) -> None:
        self.run_gate(
            """
            const gate = new SessionStartGate();
            const oldGeneration = gate.begin();
            assert.equal(gate.publishSession(oldGeneration), false);

            const generation = gate.begin();
            assert.equal(gate.publishSession(generation), false);
            assert.equal(gate.observeNativeStarted(oldGeneration), false);
            assert.equal(gate.observeNativeStarted(generation), true);
            """
        )


if __name__ == "__main__":
    unittest.main()
