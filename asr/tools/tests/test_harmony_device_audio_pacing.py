"""Run the real carrier feeder with a clock and a caller that consumes time."""
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CARRIER = ROOT / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"


class HarmonyDeviceAudioPacingTest(unittest.TestCase):
    def run_feeder(self, checks):
        source = CARRIER.read_text()
        method = "async function feedPcmFile(" + source.split("async function feedPcmFile(", 1)[1].split("\nfunction readPcmFrames", 1)[0]
        script = f"""
import assert from 'node:assert/strict';
const FRAME_BYTES = 640;
let now = 0, reads = 0, closed = 0;
Date.now = () => now;
const sleep = async ms => {{ now += Math.max(0, ms); }};
const fs = {{
  openSync: () => ({{ fd: 1 }}),
  readSync: (_, buffer) => {{
    if (reads >= 5) return 0;
    new Uint8Array(buffer).fill(++reads);
    return buffer.byteLength;
  }},
  closeSync: () => {{ closed++; }}
}};
const calls = [];
{method}
{checks}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pacing.mts"
            path.write_text(script)
            subprocess.run(["node", "--experimental-strip-types", str(path)], check=True)

    def test_write_cost_does_not_slow_realtime_input(self):
        self.run_feeder("""
const engine = { writeAudio(_, frame) {
  calls.push([now, new Uint8Array(frame)[0]]);
  now += 4;
}};
assert.equal(await feedPcmFile(engine, 's', 'pcm', 0, 20), 5);
assert.deepEqual(calls, [[0,1],[20,2],[40,3],[60,4],[80,5]]);
assert.equal(now, 100);
assert.equal(closed, 1);
""")

    def test_late_input_catches_up_without_dropping_or_reordering_frames(self):
        self.run_feeder("""
const engine = { writeAudio(_, frame) {
  calls.push([now, new Uint8Array(frame)[0]]);
  now += calls.length === 1 ? 55 : 4;
}};
assert.equal(await feedPcmFile(engine, 's', 'pcm', 0, 20), 5);
assert.deepEqual(calls, [[0,1],[55,2],[59,3],[63,4],[80,5]]);
assert.equal(now, 100);
assert.equal(closed, 1);
""")


if __name__ == "__main__":
    unittest.main()
