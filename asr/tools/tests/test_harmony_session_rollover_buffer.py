import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ROLLOVER = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/SessionRolloverBuffer.ts"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonySessionRolloverBufferTest(unittest.TestCase):
    def run_rollover(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SessionRolloverBuffer }} from {ROLLOVER.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                str(TS_LOADER),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_trigger_and_in_flight_frames_are_replayed_in_order(self) -> None:
        self.run_rollover(
            """
            const rollover = new SessionRolloverBuffer(1000, 4);
            const trigger = new ArrayBuffer(640);
            const duringFinish = new ArrayBuffer(640);

            assert.equal(rollover.route(trigger, true, 1000, 'old'), 'finish');
            assert.equal(rollover.isRotating(), true);
            assert.equal(rollover.route(duringFinish, true, 0, ''), 'buffer');
            assert.deepEqual(rollover.complete(), [trigger, duringFinish]);
            assert.equal(rollover.isRotating(), false);
            """
        )

    def test_non_rotation_and_reset_preserve_adjacent_contracts(self) -> None:
        self.run_rollover(
            """
            const rollover = new SessionRolloverBuffer(1000, 2);
            const frame = new ArrayBuffer(640);

            assert.equal(rollover.route(frame, false, 2000, 'session'), 'write');
            assert.equal(rollover.route(frame, true, 999, 'session'), 'write');
            assert.equal(rollover.pendingCount(), 0);

            assert.equal(rollover.route(frame, true, 1000, 'session'), 'finish');
            rollover.reset();
            assert.equal(rollover.isRotating(), false);
            assert.equal(rollover.pendingCount(), 0);
            """
        )


if __name__ == "__main__":
    unittest.main()
