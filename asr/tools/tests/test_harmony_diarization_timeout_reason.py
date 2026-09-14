"""Exercise the production executor's timeout and late-result paths."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization/SpeakerDiarizationLocalClient.ets"


class HarmonyDiarizationTimeoutReasonTest(unittest.TestCase):
    def run_executor(self, checks):
        source = CLIENT.read_text()
        method = "private async execute(" + source.split("private async execute(", 1)[1].split("\n  private async settleInference", 1)[0]
        script = f"""
import assert from 'node:assert/strict';
const INFERENCE_TIMEOUT_MS = 10000, WINDOW_SAMPLES = 160000;
const SpeakerDiarizationDegradedReason = {{ INFERENCE_UNAVAILABLE: 1, MODEL_UNAVAILABLE: 2,
  INFERENCE_TIMEOUT: 3, STORAGE_UNAVAILABLE: 5 }};
class SpeakerDiarizationStorageError extends Error {{}}
const timers = [];
globalThis.setTimeout = cb => {{ timers.push(cb); return timers.length - 1; }};
globalThis.clearTimeout = () => {{}};
let resolveInference;
const inferencePromise = new Promise(resolve => {{ resolveInference = resolve; }});
class Client {{
  inferenceLoad = Promise.resolve();
  inference = {{ process: () => inferencePromise }};
  closed = false; degraded = false; queue = [];
  activeJob = {{ jobId: 'w1' }};
  windows = []; failures = []; quiescent = 0;
  observer = {{ onWindow: value => this.windows.push(value) }};
  spool = {{ endOffset: () => 0, discardBefore() {{}} }};
  readWindow() {{ return new Float32Array(0); }}
  async settleInference(promise) {{ try {{ await promise; }} catch (_) {{}} }}
  fail(reason, message) {{ this.degraded = true; this.failures.push({{reason, message}}); }}
  closeWhenQuiescent() {{ this.quiescent++; }}
  pump() {{}}
  maybeNotifyDrained() {{}}
  {method}
}}
const client = new Client();
const job = client.activeJob;
const task = client.execute(job);
const flush = async () => {{ for (let i = 0; i < 10; i++) await Promise.resolve(); }};
await flush();
{checks}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeout.mts"
            path.write_text(script)
            subprocess.run(["node", "--experimental-strip-types", str(path)], check=True)

    def test_timeout_reports_timeout_and_waits_for_late_native_work(self):
        self.run_executor("""
timers[0]();
await flush();
assert.equal(client.failures.length, 1);
assert.equal(client.failures[0].reason, SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.equal(client.activeJob, job);
resolveInference({ segments: [], embeddings: [] });
await task;
assert.deepEqual(client.windows, []);
assert.equal(client.activeJob, undefined);
assert.equal(client.failures.length, 1);
""")

    def test_cancel_during_inference_does_not_publish_timeout_or_late_result(self):
        self.run_executor("""
client.closed = true;
timers[0]();
await flush();
assert.deepEqual(client.failures, []);
assert.equal(client.quiescent, 0);
resolveInference({ segments: [], embeddings: [] });
await task;
assert.deepEqual(client.windows, []);
assert.equal(client.activeJob, undefined);
assert.equal(client.quiescent, 1);
""")


if __name__ == '__main__':
    unittest.main()
