import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSOR = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/StreamingAgcProcessor.ts"
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonyStreamingAgcProcessorTest(unittest.TestCase):
    def run_processor(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ StreamingAgcProcessor }} from {PROCESSOR.as_uri()!r};
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
            cwd=REPO_ROOT,
        )

    def test_automatic_agc_is_chunk_invariant_and_flushes_remainder(self) -> None:
        self.run_processor(
            """
            const input = new Float32Array(327);
            for (let i = 0; i < input.length; i++) input[i] = (i - 160) / 640;
            const run = (sizes) => {
              const processor = new StreamingAgcProcessor(16000, () => ({
                process(frame) {
                  const output = new Float32Array(frame.length);
                  for (let i = 0; i < frame.length; i++) output[i] = frame[i] * 2;
                  return output;
                },
                close() {}
              }));
              const frames = [];
              let offset = 0;
              for (const size of sizes) {
                frames.push(...processor.process(input.slice(offset, offset + size)));
                offset += size;
              }
              frames.push(...processor.flush());
              processor.close();
              return {
                raw: frames.flatMap(frame => Array.from(frame.raw)),
                processed: frames.flatMap(frame => Array.from(frame.processed))
              };
            };
            const one = run([327]);
            const split = run([1, 73, 86, 160, 7]);
            assert.deepEqual(one, split);
            assert.deepEqual(one.raw, Array.from(input));
            assert.deepEqual(one.processed, Array.from(input, value => value * 2));
            """
        )

    def test_internal_ten_ms_frames_keep_one_decoder_submission_per_caller_chunk(self) -> None:
        self.run_processor(
            """
            let backendCalls = 0;
            const processor = new StreamingAgcProcessor(16000, () => ({
              process(frame) {
                backendCalls += 1;
                return frame.slice();
              },
              close() {}
            }));
            const output = processor.process(new Float32Array(320));
            assert.equal(backendCalls, 2);
            assert.equal(output.length, 1);
            assert.equal(output[0].raw.length, 320);
            assert.equal(output[0].processed.length, 320);
            """
        )

    def test_large_caller_chunk_is_aggregated_without_changing_samples(self) -> None:
        self.run_processor(
            """
            const input = new Float32Array(16000 * 60);
            for (let i = 0; i < input.length; i++) input[i] = (i % 257 - 128) / 512;
            const processor = new StreamingAgcProcessor(16000, () => ({
              process(frame) {
                return Float32Array.from(frame, value => value * 2);
              },
              close() {}
            }));
            const output = processor.process(input);
            assert.equal(output.length, 1);
            assert.deepEqual(output[0].raw, input);
            assert.deepEqual(output[0].processed, Float32Array.from(input, value => value * 2));
            """
        )


if __name__ == "__main__":
    unittest.main()
