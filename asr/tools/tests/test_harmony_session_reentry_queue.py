import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
QUEUE = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SessionReentryQueue.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"


class HarmonySessionReentryQueueTest(unittest.TestCase):
    def run_queue(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionReentryQueue }} from {QUEUE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_audio_is_snapshotted_before_callback_returns(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const frame = new Float32Array([0.25, -0.5]);
            const accepted = [];
            queue.enqueueAudio(frame);
            frame.fill(0);
            queue.drain(() => false, samples => accepted.push(Array.from(samples)), () => {});
            assert.deepEqual(accepted, [[0.25, -0.5]]);
            """
        )

    def test_operations_before_stop_keep_order_and_later_audio_is_dropped(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueAudio(new Float32Array([1]));
            queue.enqueueAudio(new Float32Array([2]));
            queue.enqueueStop();
            queue.enqueueAudio(new Float32Array([3]));
            queue.enqueueStop();
            queue.drain(() => false,
              samples => events.push(`audio-${samples[0]}`),
              () => events.push('stop'));
            assert.deepEqual(events, ['audio-1', 'audio-2', 'stop']);
            """
        )

    def test_callback_reentry_appends_work_without_recursive_drain(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueAudio(new Float32Array([1]));
            queue.drain(() => false, samples => {
              events.push(samples[0]);
              if (samples[0] === 1) queue.enqueueAudio(new Float32Array([2]));
            }, () => {});
            assert.deepEqual(events, [1, 2]);
            """
        )

    def test_endpoint_consumes_a_synchronous_stop_without_creating_an_empty_stream(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueStop();
            assert.equal(queue.consumeStopAtEndpoint(), true);
            queue.drain(() => false,
              samples => events.push(`audio-${samples[0]}`),
              () => events.push('stop'));
            assert.deepEqual(events, []);
            """
        )

    def test_endpoint_does_not_skip_audio_queued_before_stop(self) -> None:
        self.run_queue(
            """
            const queue = new SessionReentryQueue();
            const events = [];
            queue.enqueueAudio(new Float32Array([1]));
            queue.enqueueStop();
            assert.equal(queue.consumeStopAtEndpoint(), false);
            queue.drain(() => false,
              samples => events.push(`audio-${samples[0]}`),
              () => events.push('stop'));
            assert.deepEqual(events, ['audio-1', 'stop']);
            """
        )

    def test_runtime_defers_stream_calls_made_inside_callbacks(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("from './SessionReentryQueue'", runtime)
        self.assertIn("this.callbackGate.isInvoking()", runtime)
        self.assertIn("this.reentryQueue.enqueueAudio(samples)", runtime)
        self.assertIn("this.reentryQueue.enqueueStop()", runtime)

    def test_runtime_promotes_the_current_endpoint_when_its_callback_requests_stop(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn(
            "const stopAtEndpoint = this.reentryQueue.consumeStopAtEndpoint();",
            runtime,
        )
        self.assertIn(
            "this.dispatchFinal(true, decodeDurationMs, isLastFinal || stopAtEndpoint);",
            runtime,
        )
        self.assertIn("if (stopAtEndpoint)", runtime)


if __name__ == "__main__":
    unittest.main()
