import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LOADER = ROOT / "asr/tools/tests/ts_extension_loader.mjs"
TRANSFORMS = ROOT / "tts/harmony/sdk/src/main/ets/AudioTransforms.ts"
QUEUE = ROOT / "tts/harmony/sdk/src/main/ets/PcmChunkQueue.ts"


def run_node(body: str) -> None:
    script = textwrap.dedent(
        f"""
        import assert from 'node:assert/strict';
        import {{ AudioTransforms, lengthScaleForSpeed }} from {TRANSFORMS.as_uri()!r};
        import {{ PcmChunkQueue }} from {QUEUE.as_uri()!r};
        {body}
        """
    )
    subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--experimental-loader",
            LOADER.as_uri(),
            "--input-type=module",
            "-e",
            script,
        ],
        cwd=ROOT,
        check=True,
    )


class TtsRuntimePrimitivesTest(unittest.TestCase):
    def test_audio_transforms_preserve_identity_and_clamp_volume(self) -> None:
        run_node(
            """
            const source = Int16Array.from([-20000, 1000, 20000]).buffer;
            assert.equal(AudioTransforms.apply(source, { requestId: 'identity' }), source);

            const amplified = new Int16Array(AudioTransforms.apply(
              source, { requestId: 'volume', volume: 2.0 }));
            assert.deepEqual(Array.from(amplified), [-32768, 2000, 32767]);
            """
        )

    def test_audio_transforms_keep_pitch_length_and_apply_speed_length(self) -> None:
        run_node(
            """
            const source = Int16Array.from([0, 1000, 2000, 3000]).buffer;
            const pitched = AudioTransforms.apply(source, { requestId: 'pitch', pitch: 2.0 });
            const faster = AudioTransforms.apply(source, { requestId: 'speed', speed: 2.0 });
            assert.equal(new Int16Array(pitched).length, 4);
            assert.equal(new Int16Array(faster).length, 2);
            assert.equal(lengthScaleForSpeed(Number.NaN), 1.0);
            assert.equal(lengthScaleForSpeed(4.0), 0.5);
            """
        )

    def test_pcm_queue_preserves_fifo_and_releases_backpressure(self) -> None:
        run_node(
            """
            const queue = new PcmChunkQueue(1, 8);
            await queue.put(Uint8Array.from([1]).buffer);
            let secondFinished = false;
            const secondPut = queue.put(Uint8Array.from([2]).buffer).then(() => {
              secondFinished = true;
            });
            await Promise.resolve();
            assert.equal(secondFinished, false);

            const first = await queue.take();
            assert.equal(new Uint8Array(first.chunk)[0], 1);
            await secondPut;
            const second = await queue.take();
            assert.equal(new Uint8Array(second.chunk)[0], 2);
            """
        )

    def test_pcm_queue_close_releases_waiters(self) -> None:
        run_node(
            """
            const queue = new PcmChunkQueue(1, 8);
            const waitingTake = queue.take();
            queue.close();
            assert.deepEqual(await waitingTake, { done: true });
            assert.deepEqual(await queue.take(), { done: true });
            await queue.waitForPrebuffer(1);
            """
        )


if __name__ == "__main__":
    unittest.main()
