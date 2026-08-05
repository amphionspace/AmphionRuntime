import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerVadScoreScheduler.ts"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


class HarmonySpeakerVadScoreSchedulerTest(unittest.TestCase):
    def run_scheduler(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerVadScoreScheduler }} from {SCHEDULER.as_uri()!r};
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

    def test_score_deadlines_do_not_depend_on_caller_pcm_partitioning(self) -> None:
        self.run_scheduler(
            """
            function scoreDeadlines(partitions) {
              const scheduler = new SpeakerVadScoreScheduler(16_000, 4_800);
              const deadlines = [];
              for (const partition of partitions) {
                let remaining = partition;
                while (remaining > 0) {
                  const accepted = Math.min(remaining, scheduler.samplesUntilNextScore());
                  if (scheduler.observe(accepted)) deadlines.push(scheduler.totalSamples());
                  remaining -= accepted;
                }
              }
              return deadlines;
            }

            const total = 32_000;
            const realtime = Array(total / 320).fill(320);
            const pattern = [160, 1_120, 640, 2_400, 320, 3_040];
            const irregular = [];
            let remaining = total;
            let index = 0;
            while (remaining > 0) {
              const size = Math.min(remaining, pattern[index % pattern.length]);
              irregular.push(size);
              remaining -= size;
              index += 1;
            }

            const expected = [16_000, 19_200, 24_000, 28_800];
            assert.deepEqual(scoreDeadlines(realtime), expected);
            assert.deepEqual(scoreDeadlines(irregular), expected);
            assert.deepEqual(scoreDeadlines([total]), expected);
            """
        )

    def test_reset_reanchors_deadlines_to_the_next_native_segment(self) -> None:
        self.run_scheduler(
            """
            const scheduler = new SpeakerVadScoreScheduler(16_000, 4_800);
            assert.equal(scheduler.samplesUntilNextScore(), 16_000);
            assert.equal(scheduler.observe(16_000), true);
            assert.equal(scheduler.samplesUntilNextScore(), 3_200);

            scheduler.reset();

            assert.equal(scheduler.samplesUntilNextScore(), 16_000);
            assert.equal(scheduler.observe(8_000), false);
            assert.equal(scheduler.samplesUntilNextScore(), 8_000);
            """
        )

    def test_window_shorter_than_hop_does_not_score_before_the_first_hop(self) -> None:
        self.run_scheduler(
            """
            const scheduler = new SpeakerVadScoreScheduler(8_000, 16_000);
            assert.equal(scheduler.samplesUntilNextScore(), 16_000);
            assert.equal(scheduler.observe(16_000), true);
            assert.equal(scheduler.samplesUntilNextScore(), 16_000);
            """
        )


if __name__ == "__main__":
    unittest.main()
