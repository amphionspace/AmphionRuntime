import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TRACKER = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeSegmentTracker.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
TYPES = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets"


class HarmonyNativeSegmentTrackerTest(unittest.TestCase):
    def run_tracker(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ NativeSegmentTracker }} from {TRACKER.as_uri()!r};
            {body}
            """
        )
        completed = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_suppressed_endpoint_resets_native_duration_but_spans_public_result(self) -> None:
        self.run_tracker(
            """
            const tracker = new NativeSegmentTracker();
            tracker.acceptPcm(32000, 1000);
            tracker.observePartial(1200);
            const hidden = tracker.finish('native-rule3', true, 0, 3, false);
            assert.equal(hidden.segmentIndex, 1);
            assert.equal(hidden.durationMs, 1000);
            assert.equal(hidden.firstPartialLatencyMs, 200);
            assert.equal(hidden.publicSpanSegments, 1);
            assert.equal(hidden.suppressedSincePublic, 1);

            tracker.acceptPcm(64000, 2000);
            tracker.observePartial(2400);
            const visible = tracker.finish('vad-active', true, 8, 8, true);
            assert.equal(visible.segmentIndex, 2);
            assert.equal(visible.durationMs, 2000);
            assert.equal(visible.firstPartialLatencyMs, 400);
            assert.equal(visible.publicSpanSegments, 2);
            assert.equal(visible.suppressedSincePublic, 1);

            tracker.acceptPcm(16000, 3000);
            const next = tracker.finish('finish', false, 0, 0, true);
            assert.equal(next.durationMs, 500);
            assert.equal(next.publicSpanSegments, 1);
            assert.equal(next.suppressedSincePublic, 0);
            """
        )

    def test_framing_does_not_change_native_pcm_duration(self) -> None:
        self.run_tracker(
            """
            const one = new NativeSegmentTracker();
            const many = new NativeSegmentTracker();
            one.acceptPcm(64000, 10);
            for (let i = 0; i < 100; i++) many.acceptPcm(640, 10 + i);
            assert.equal(one.finish('finish', true, 1, 1, true).durationMs, 2000);
            assert.equal(many.finish('finish', true, 1, 1, true).durationMs, 2000);
            """
        )

    def test_runtime_reports_suppressed_native_boundaries_separately(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        types = TYPES.read_text(encoding="utf-8")
        self.assertIn("private nativeSegmentTracker: NativeSegmentTracker", runtime)
        self.assertIn("this.nativeSegmentTracker.acceptPcm", runtime)
        self.assertIn("this.nativeSegmentTracker.observePartial", runtime)
        self.assertIn("this.nativeSegmentTracker.finish", runtime)
        self.assertIn("kind=NATIVE_SEGMENT", runtime)
        self.assertIn("nativeSegmentCount: number = -1", types)
        self.assertIn("suppressedEndpointCount: number = -1", types)


if __name__ == "__main__":
    unittest.main()
