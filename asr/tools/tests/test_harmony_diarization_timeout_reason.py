"""Exercise the production executor's timeout and late-result paths."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization/SortformerLocalClient.ets"


class HarmonyDiarizationTimeoutReasonTest(unittest.TestCase):
    def run_executor(self, checks):
        source = CLIENT.read_text()
        method = "private async execute(" + source.split("private async execute(", 1)[1].split("\n  private deliver(", 1)[0]
        fail = "private fail(" + source.split("private fail(", 1)[1].split("\n  private maybeNotifyDrained", 1)[0]
        script = f"""
import assert from 'node:assert/strict';
const INFERENCE_TIMEOUT_MS = 10000;
const SpeakerDiarizationDegradedReason = {{ INFERENCE_UNAVAILABLE: 1, MODEL_UNAVAILABLE: 2,
  INFERENCE_TIMEOUT: 3, STORAGE_UNAVAILABLE: 5 }};
const timers = [];
globalThis.setTimeout = cb => {{ timers.push(cb); return timers.length - 1; }};
globalThis.clearTimeout = () => {{}};
let resolveInference;
const inferencePromise = new Promise(resolve => {{ resolveInference = resolve; }});
class Client {{
  inference = {{ feed: () => inferencePromise }};
  closed = false; degraded = false; stopped = false; finishing = false; flushed = false;
  pending = []; pendingSamples = 0; fedSamples = 0;
  activeJobId = 'f1'; activeJobStartedMs = Date.now();
  results = []; failures = []; diagnostics = []; quiescent = 0;
  observer = {{ onFeedResult: value => this.results.push(value),
    onDegraded: (reason, message) => this.failures.push({{reason, message}}),
    onDrained: () => {{}} }};
  diagnostic = (event, fields) => this.diagnostics.push({{event, fields}});
  async settle(promise) {{ try {{ await promise; }} catch (_) {{}} }}
  deliver(jobId, result, wallMs, flush) {{ this.results.push({{jobId, result, wallMs, flush}}); }}
  {fail}
  closeWhenQuiescent() {{ this.quiescent++; }}
  pump() {{}}
  maybeNotifyDrained() {{}}
  {method}
}}
const client = new Client();
const task = client.execute('f1', new Float32Array(16000), false);
const flush = async () => {{ for (let i = 0; i < 10; i++) await Promise.resolve(); }};
await flush();
{checks}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeout.mts"
            path.write_text(script)
            subprocess.run(["node", "--experimental-strip-types", str(path)], check=True)

    def test_timeout_does_not_abandon_throttled_background_chunks(self):
        # Timing out cannot stop native work, it only discards every later
        # speaker result, so the bound sits far above a throttled chunk pass.
        source = CLIENT.read_text()
        value = int(source.split("const INFERENCE_TIMEOUT_MS: number = ", 1)[1].split(";", 1)[0])
        self.assertGreaterEqual(value, 60000)

    def test_timeout_reports_timeout_and_waits_for_late_native_work(self):
        self.run_executor("""
timers[0]();
await flush();
assert.equal(client.failures.length, 1);
assert.equal(client.failures[0].reason, SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.equal(client.activeJobId, 'f1', 'the in-flight call stays owned until native work settles');
resolveInference({ events: [], melFrames: 0, samples: 16000 });
await task;
assert.deepEqual(client.results, []);
assert.equal(client.activeJobId, '');
assert.equal(client.failures.length, 1);
""")

    def test_stopped_inference_does_not_publish_timeout_or_late_result(self):
        self.run_executor("""
client.stopped = true;
timers[0]();
await flush();
assert.deepEqual(client.failures, []);
resolveInference({ events: [], melFrames: 0, samples: 16000 });
await task;
assert.deepEqual(client.results, []);
assert.deepEqual(client.failures, []);
""")

    def test_cancel_during_inference_does_not_publish_timeout_or_late_result(self):
        self.run_executor("""
client.closed = true;
timers[0]();
await flush();
assert.deepEqual(client.failures, []);
assert.equal(client.quiescent, 0);
resolveInference({ events: [], melFrames: 0, samples: 16000 });
await task;
assert.deepEqual(client.results, []);
assert.equal(client.activeJobId, '');
assert.equal(client.quiescent, 1);
""")

    def test_failure_records_the_job_and_pending_audio_before_discard(self):
        self.run_executor("""
client.pending.push(new Int16Array(320)); client.pendingSamples = 320;
timers[0]();
await flush();
assert.equal(client.diagnostics.length, 1);
const diagnostic = client.diagnostics[0];
assert.equal(diagnostic.event, 'DIARIZATION_LOCAL_FAILURE');
assert.equal(diagnostic.fields.jobId, 'f1');
assert.equal(diagnostic.fields.pendingSamples, 320);
assert.equal(diagnostic.fields.reason, SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.ok(diagnostic.fields.elapsedMs >= 0);
assert.equal(client.pending.length, 0);
assert.equal(client.pendingSamples, 0);
resolveInference({ events: [], melFrames: 0, samples: 16000 });
await task;
assert.deepEqual(client.results, []);
""")

    def test_diagnostic_failure_cannot_change_timeout_or_quiescence(self):
        self.run_executor("""
client.diagnostic = () => { throw new Error('diagnostic storage unavailable'); };
timers[0]();
await flush();
assert.equal(client.failures.length, 1);
assert.equal(client.failures[0].reason, SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.equal(client.activeJobId, 'f1');
resolveInference({ events: [], melFrames: 0, samples: 16000 });
await task;
assert.equal(client.activeJobId, '');
assert.deepEqual(client.results, []);
""")

    def test_model_errors_degrade_as_model_unavailable(self):
        self.run_executor("""
resolveInference(Promise.reject(new Error('Sortformer model asset unavailable: x')));
await task;
assert.equal(client.failures.length, 1);
assert.equal(client.failures[0].reason, SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE);
""")


if __name__ == "__main__":
    unittest.main()
