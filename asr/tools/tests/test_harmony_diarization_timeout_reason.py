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
        fail = "private fail(" + source.split("private fail(", 1)[1].split("\n  private maybeNotifyDrained", 1)[0]
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
  activeJob = {{ jobId: 'w1', windowStartSample: 16000, realEndSample: 176000 }};
  activeJobStartedMs = Date.now(); finishing = false;
  windows = []; failures = []; diagnostics = []; quiescent = 0;
  observer = {{ onWindow: value => this.windows.push(value),
    onDegraded: (reason, message) => this.failures.push({{reason, message}}) }};
  diagnostic = (event, fields) => this.diagnostics.push({{event, fields}});
  spool = {{ endOffset: () => 0, discardBefore() {{}} }};
  readWindow() {{ return new Float32Array(0); }}
  async settleInference(promise) {{ try {{ await promise; }} catch (_) {{}} }}
  {fail}
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

    def test_failure_records_the_job_and_pending_queue_before_discard(self):
        self.run_executor("""
client.queue.push({jobId: 'w2'});
timers[0]();
await flush();
assert.equal(client.diagnostics.length, 1);
const diagnostic = client.diagnostics[0];
assert.equal(diagnostic.event, 'DIARIZATION_LOCAL_FAILURE');
assert.equal(diagnostic.fields.jobId, 'w1');
assert.deepEqual(diagnostic.fields.realPcmRange, [16000, 176000]);
assert.equal(diagnostic.fields.pendingJobs, 1);
assert.equal(diagnostic.fields.reason, SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.ok(diagnostic.fields.elapsedMs >= 0);
assert.equal(client.queue.length, 0);
resolveInference({ segments: [], embeddings: [] });
await task;
assert.deepEqual(client.windows, []);
""")

    def test_diagnostic_failure_cannot_change_timeout_or_quiescence(self):
        self.run_executor("""
client.diagnostic = () => { throw new Error('diagnostic storage unavailable'); };
timers[0]();
await flush();
assert.equal(client.failures.length, 1);
assert.equal(client.failures[0].reason, SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.equal(client.activeJob, job);
resolveInference({ segments: [], embeddings: [] });
await task;
assert.equal(client.activeJob, undefined);
assert.deepEqual(client.windows, []);
""")


if __name__ == '__main__':
    unittest.main()
