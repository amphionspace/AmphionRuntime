import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SessionCallbackGate.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonySessionCallbackGateTest(unittest.TestCase):
    def run_gate(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionCallbackGate }} from {GATE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_close_inside_endpoint_stops_old_stack_before_final(self) -> None:
        self.run_gate(
            """
            const gate = new SessionCallbackGate();
            const events = [];
            if (gate.invoke(() => { events.push('endpoint'); gate.close(); })) {
              gate.invoke(() => events.push('final'));
            }
            assert.deepEqual(events, ['endpoint']);
            """
        )

    def test_close_inside_legacy_partial_suppresses_structured_partial(self) -> None:
        self.run_gate(
            """
            const gate = new SessionCallbackGate();
            const events = [];
            if (gate.invoke(() => { events.push('partial'); gate.close(); })) {
              gate.invoke(() => events.push('partialResult'));
            }
            assert.deepEqual(events, ['partial']);
            """
        )

    def test_open_session_preserves_callback_order(self) -> None:
        self.run_gate(
            """
            const gate = new SessionCallbackGate();
            const events = [];
            if (gate.invoke(() => events.push('endpoint'))) {
              gate.invoke(() => events.push('final'));
            }
            assert.deepEqual(events, ['endpoint', 'final']);
            assert.equal(gate.isClosed(), false);
            """
        )

    def test_gate_exposes_only_the_active_callback_stack(self) -> None:
        self.run_gate(
            """
            const gate = new SessionCallbackGate();
            assert.equal(gate.isInvoking(), false);
            gate.invoke(() => {
              assert.equal(gate.isInvoking(), true);
              gate.invoke(() => assert.equal(gate.isInvoking(), true));
              assert.equal(gate.isInvoking(), true);
            });
            assert.equal(gate.isInvoking(), false);
            """
        )

    def test_gate_restores_invocation_state_when_callback_throws(self) -> None:
        self.run_gate(
            """
            const gate = new SessionCallbackGate();
            assert.throws(() => gate.invoke(() => { throw new Error('listener failed'); }));
            assert.equal(gate.isInvoking(), false);
            """
        )

    def test_runtime_routes_reentrant_callback_sequences_through_gate(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("from './SessionCallbackGate'", runtime)
        self.assertIn("callbackGate.invoke((): void => { this.callback.onEndpoint?.(); })", runtime)
        self.assertIn("callbackGate.invoke((): void => { this.callback.onPartial?.(result.text); })", runtime)
        self.assertIn("callbackGate.invoke((): void => { this.callback.onPartialResult?.(result); })", runtime)
        self.assertIn("this.callback.onSpeechBegin?.();", runtime)
        self.assertNotIn("this.callback.onEndpoint?.();\n      this.dispatchFinal", runtime)


if __name__ == "__main__":
    unittest.main()
