import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INGRESS = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/StreamingAgcIngress.ts"
TS_LOADER = ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonyStreamingAgcIngressTest(unittest.TestCase):
    def run_ingress(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ StreamingAgcIngress }} from {INGRESS.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                TS_LOADER.as_uri(),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=ROOT,
        )

    def test_sync_and_async_lanes_deliver_every_frame_once_and_flush_in_order(self) -> None:
        self.run_ingress(
            """
            let processCalls = 0;
            let flushCalls = 0;
            let closeCalls = 0;
            const processor = {
              process(samples) {
                processCalls += 1;
                return [{ raw: samples.slice(), processed: Float32Array.from(samples, x => x + 10) }];
              },
              flush() {
                flushCalls += 1;
                return [{ raw: new Float32Array([99]), processed: new Float32Array([109]) }];
              },
              close() { closeCalls += 1; }
            };
            const ingress = new StreamingAgcIngress(processor);
            const sync = [];
            ingress.accept(new Float32Array([1, 2]), frame => sync.push(Array.from(frame.processed)));
            ingress.flush(frame => sync.push(Array.from(frame.processed)));
            assert.deepEqual(sync, [[11, 12], [109]]);

            const asyncFrames = [];
            await ingress.acceptAsync(new Float32Array([3]), async frame => {
              await Promise.resolve();
              asyncFrames.push(Array.from(frame.processed));
            });
            await ingress.flushAsync(async frame => {
              await Promise.resolve();
              asyncFrames.push(Array.from(frame.processed));
            });
            assert.deepEqual(asyncFrames, [[13], [109]]);
            assert.equal(processCalls, 2);
            assert.equal(flushCalls, 2);
            ingress.close();
            ingress.close();
            assert.equal(closeCalls, 1);
            """
        )


if __name__ == "__main__":
    unittest.main()
