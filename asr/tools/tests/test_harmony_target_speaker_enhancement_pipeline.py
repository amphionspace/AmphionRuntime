import pathlib
import subprocess
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
PIPELINE = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementStream.ts"
)
SDK = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"


class HarmonyTargetSpeakerEnhancementPipelineTest(unittest.TestCase):
    def run_node(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ TargetSpeakerEnhancementPipeline }} from {PIPELINE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_serializes_processing_and_finish_waits_for_all_output(self) -> None:
        self.run_node(
            """
            const calls = [];
            let active = 0;
            let maxActive = 0;
            const outputs = [];
            const metrics = [];
            let finished = 0;
            const pipeline = new TargetSpeakerEnhancementPipeline({
              process: async (chunk) => {
                active += 1;
                maxActive = Math.max(maxActive, active);
                const index = chunk.startSample / 28000;
                calls.push(index);
                await new Promise((resolve) => setTimeout(resolve, index === 0 ? 20 : 1));
                active -= 1;
                return Float32Array.from(chunk.samples, (value) => value + index + 1);
              }
            }, {
              onOutput: (samples) => outputs.push(samples),
              onFinished: () => finished += 1,
              onError: (message) => assert.fail(message),
              onMetrics: (processingMs, queued, maxQueued) =>
                metrics.push({ processingMs, queued, maxQueued })
            });
            pipeline.append(new Float32Array(56000).fill(1));
            const finishing = pipeline.finish();
            assert.equal(finished, 0);
            await finishing;
            assert.deepEqual(calls, [0, 1]);
            assert.equal(maxActive, 1);
            assert.equal(finished, 1);
            assert.equal(outputs.reduce((sum, item) => sum + item.length, 0), 56000);
            assert.equal(metrics.length, 2);
            assert.equal(metrics[0].maxQueued, 2);
            assert.equal(metrics[1].queued, 0);
            assert.equal(outputs[0][0], 2);
            assert.ok(Math.abs(outputs[1][2000] - 2.5) < 0.001);
            await pipeline.finish();
            assert.equal(finished, 1);
            """
        )

    def test_cancel_drops_late_output_and_never_finishes(self) -> None:
        self.run_node(
            """
            let release;
            const blocked = new Promise((resolve) => release = resolve);
            const outputs = [];
            let finished = 0;
            const pipeline = new TargetSpeakerEnhancementPipeline({
              process: async (chunk) => { await blocked; return chunk.samples; }
            }, {
              onOutput: (samples) => outputs.push(samples),
              onFinished: () => finished += 1,
              onError: (message) => assert.fail(message)
            });
            pipeline.append(new Float32Array(32000).fill(1));
            pipeline.cancel();
            release();
            await new Promise((resolve) => setTimeout(resolve, 10));
            assert.equal(outputs.length, 0);
            assert.equal(finished, 0);
            assert.throws(() => pipeline.append(new Float32Array(1)), /not accepting/);
            """
        )

    def test_async_append_applies_backpressure_and_reports_real_queue(self) -> None:
        self.run_node(
            """
            const releases = [];
            const pipeline = new TargetSpeakerEnhancementPipeline({
              process: async (chunk) => {
                await new Promise((resolve) => releases.push(resolve));
                return chunk.samples;
              }
            }, {
              onOutput: async () => { await Promise.resolve(); },
              onFinished: () => {},
              onError: (message) => assert.fail(message)
            }, 64000, 32000);

            for (let i = 0; i < 100; i++) {
              assert.equal(await pipeline.appendAsync(new Float32Array(320)), true);
            }
            let resolved = false;
            const blocked = pipeline.appendAsync(new Float32Array(320)).then((value) => {
              resolved = value;
            });
            await Promise.resolve();
            assert.equal(resolved, false);
            const queued = pipeline.queueStats();
            assert.ok(queued.queuedBytes > queued.highWaterBytes);
            assert.equal(queued.queuedChunks, 1);
            assert.ok(queued.retainedBytes >= 32000 * 4);

            releases.shift()();
            await blocked;
            assert.equal(resolved, true);
            assert.ok(pipeline.queueStats().queuedBytes <= 32000);
            pipeline.cancel();
            """
        )

    def test_continuous_enhancement_backpressure_releases_processed_pcm_slots(self) -> None:
        self.run_node(
            """
            const pipeline = new TargetSpeakerEnhancementPipeline({
              process: async (chunk) => chunk.samples
            }, {
              onOutput: async () => {},
              onFinished: () => {},
              onError: (message) => assert.fail(message)
            }, 64000, 32000);

            let maxArrayLength = 0;
            for (let i = 0; i < 10000; i++) {
              assert.equal(await pipeline.appendAsync(new Float32Array(320)), true);
              maxArrayLength = Math.max(maxArrayLength, pipeline.queue.length);
            }
            await pipeline.finish();
            const stats = pipeline.queueStats();
            assert.ok(maxArrayLength < 128, `queue storage grew to ${maxArrayLength}`);
            assert.equal(pipeline.queue.length, 0);
            assert.equal(stats.queuedChunks, 0);
            assert.equal(stats.queuedBytes, 0);
            assert.equal(stats.retainedBytes, 0);
            """
        )

    def test_sdk_does_not_bypass_enhancement_backpressure_or_stats(self) -> None:
        source = SDK.read_text(encoding="utf-8")
        self.assertIn("await enhancementPipeline.whenWritable()", source)
        self.assertIn("this.targetSpeakerEnhancementPipeline?.queueStats()", source)
        self.assertIn("await this.audioDispatcher?.writeFloatWithBackpressure(samples)", source)
        self.assertNotIn("enhancementPipeline !== undefined || dispatcher === undefined", source)


if __name__ == "__main__":
    unittest.main()
