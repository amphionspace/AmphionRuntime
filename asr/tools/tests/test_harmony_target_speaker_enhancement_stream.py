import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STREAM = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementStream.ts"
)


class HarmonyTargetSpeakerEnhancementStreamTest(unittest.TestCase):
    def run_stream(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{
              TARGET_SPEAKER_CHUNK_SAMPLES,
              TARGET_SPEAKER_HOP_SAMPLES,
              TargetSpeakerEnhancementInput,
              TargetSpeakerEnhancementStitcher,
            }} from {STREAM.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_input_chunking_is_independent_of_caller_frames(self) -> None:
        self.run_stream(
            """
            const samples = Float32Array.from({ length: 70000 }, (_, i) => i);
            const whole = new TargetSpeakerEnhancementInput();
            const wholeChunks = [...whole.append(samples), ...whole.finish()];

            const framed = new TargetSpeakerEnhancementInput();
            const framedChunks = [];
            for (let start = 0; start < samples.length; start += 320) {
              framedChunks.push(...framed.append(samples.slice(start, start + 320)));
            }
            framedChunks.push(...framed.finish());

            assert.deepEqual(wholeChunks.map(c => c.startSample), [0, 28000, 56000]);
            assert.deepEqual(framedChunks.map(c => c.startSample), [0, 28000, 56000]);
            assert.deepEqual(framedChunks.map(c => c.availableSamples), [32000, 32000, 14000]);
            assert.equal(wholeChunks.at(-1).isFinal, true);
            assert.equal(framedChunks.at(-1).isFinal, true);
            for (let i = 0; i < wholeChunks.length; i++) {
              assert.deepEqual(Array.from(wholeChunks[i].samples), Array.from(framedChunks[i].samples));
            }
            """
        )

    def test_finish_pads_native_input_without_extending_public_audio(self) -> None:
        self.run_stream(
            """
            const input = new TargetSpeakerEnhancementInput();
            assert.equal(input.append(new Float32Array(10000).fill(0.5)).length, 0);
            const chunks = input.finish();
            assert.equal(chunks.length, 1);
            assert.equal(chunks[0].samples.length, TARGET_SPEAKER_CHUNK_SAMPLES);
            assert.equal(chunks[0].availableSamples, 10000);
            assert.equal(chunks[0].samples[9999], 0.5);
            assert.equal(chunks[0].samples[10000], 0);

            const stitcher = new TargetSpeakerEnhancementStitcher();
            const output = stitcher.append(chunks[0], new Float32Array(32000).fill(0.25));
            assert.equal(output.length, 10000);
            assert.equal(output.at(-1), 0.25);
            """
        )

    def test_stitcher_crossfades_adjacent_results_and_preserves_length(self) -> None:
        self.run_stream(
            """
            const input = new TargetSpeakerEnhancementInput();
            const first = input.append(new Float32Array(32000).fill(1))[0];
            const tail = input.finish()[0];
            const stitcher = new TargetSpeakerEnhancementStitcher();
            const headOutput = stitcher.append(first, new Float32Array(32000).fill(1));
            const tailOutput = stitcher.append(tail, new Float32Array(32000).fill(0));
            assert.equal(headOutput.length, TARGET_SPEAKER_HOP_SAMPLES);
            assert.equal(tailOutput.length, 4000);
            assert.equal(headOutput[0], 1);
            assert.ok(tailOutput[0] > 0.9999);
            assert.ok(tailOutput.at(-1) < 0.0001);
            assert.equal(headOutput.length + tailOutput.length, 32000);
            """
        )

    def test_finish_and_append_are_one_way(self) -> None:
        self.run_stream(
            """
            const input = new TargetSpeakerEnhancementInput();
            input.append(new Float32Array(100));
            input.finish();
            assert.deepEqual(input.finish(), []);
            assert.throws(() => input.append(new Float32Array(1)), /finished/);
            """
        )


if __name__ == "__main__":
    unittest.main()
