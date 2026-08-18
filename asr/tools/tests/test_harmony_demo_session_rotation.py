import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BUFFER = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/SessionRotationBuffer.ts"
)
INDEX = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets"
)


class HarmonyDemoSessionRotationTest(unittest.TestCase):
    def test_rotation_buffer_snapshots_preserves_order_and_reports_overflow(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionRotationBuffer }} from {BUFFER.as_uri()!r};

            const buffer = new SessionRotationBuffer(3);
            const first = Uint8Array.from([1]).buffer;
            assert.equal(buffer.append(first), true);
            new Uint8Array(first)[0] = 9;
            assert.equal(buffer.append(Uint8Array.from([2]).buffer), true);
            assert.equal(buffer.append(Uint8Array.from([3]).buffer), true);
            assert.equal(buffer.append(Uint8Array.from([4]).buffer), false);

            const drained = buffer.drain();
            assert.deepEqual(drained.frames.map(frame => new Uint8Array(frame)[0]), [1, 2, 3]);
            assert.equal(drained.droppedFrames, 1);
            assert.equal(buffer.size(), 0);
            assert.equal(buffer.append(Uint8Array.from([5]).buffer), true);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_demo_buffers_the_trigger_frame_and_flushes_after_new_session_start(self) -> None:
        source = INDEX.read_text(encoding="utf-8")
        trigger = source.index("this.rotatingSession = true;")
        buffered = source.index("this.bufferRotationFrame(frame);", trigger)
        finish = source.index("this.engine?.finish(sid);", buffered)
        self.assertLess(buffered, finish)

        completion = source.index("private completeSessionRotation(): void")
        start = source.index("this.startRecognitionSession();", completion)
        replay = source.index("this.feedFrameLive(buffered[index]);", start)
        self.assertLess(start, replay)
        self.assertIn("rotationStopRequested && !this.rotationCaptureStopped", source)
        self.assertIn("droppedFrames=%{public}d", source)


if __name__ == "__main__":
    unittest.main()
