import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/AsrSchedulingConfig.ts'
PATCH = ROOT / 'third_party/patches/sherpa-amphion/0027-feat-harmony-asr-thread-scheduling.patch'
IDLE_PATCH = ROOT / 'third_party/patches/sherpa-amphion/0029-perf-harmony-stop-idle-asr-spinning.patch'
FIXTURES = Path(__file__).with_name('harmony_scheduling')


class HarmonySchedulingTest(unittest.TestCase):
    def test_configuration_defaults_validation_and_snapshot(self):
        script = f"""
import assert from 'node:assert/strict';
import {{ AsrSchedulingConfig, snapshotAsrScheduling, asrCpuProvider, resolveDiarizationQos }} from {POLICY.as_uri()!r};
const c = new AsrSchedulingConfig();
assert.equal(asrCpuProvider(true), 'cpu;DisablePrepacking=1');
assert.deepEqual(snapshotAsrScheduling(undefined), c);
assert.equal(asrCpuProvider(true, c), 'cpu;DisablePrepacking=1');
assert.equal(asrCpuProvider(false, c), 'cpu');
c.qos = 'user-initiated'; c.cpuIds = [6, 4]; c.allowSpinning = false;
const copy = snapshotAsrScheduling(c);
c.cpuIds[0] = 2; c.qos = 'default';
assert.deepEqual(copy.cpuIds, [4, 6]);
assert.equal(asrCpuProvider(false, copy),
  'cpu;AmphionQos=user-initiated;AmphionCpuIds=4,6;AmphionAllowSpinning=0');
for (const ids of [[NaN], [Infinity], [-1], [128], [1.5], [2, 2], ['2']]) {{
  assert.throws(() => snapshotAsrScheduling({{ ...copy, cpuIds: ids }}));
}}
assert.throws(() => snapshotAsrScheduling({{ ...copy, qos: 'cpu;other=1' }}));
assert.throws(() => snapshotAsrScheduling({{ ...copy, allowSpinning: 'false' }}));
// The window cadence defaults to one second, survives a snapshot, and never
// reaches the recognizer provider string: it only drives role separation.
assert.equal(c.diarizationHopMs, 2000);
assert.equal(snapshotAsrScheduling({{ ...copy, diarizationHopMs: 2000 }}).diarizationHopMs, 2000);
assert.equal(snapshotAsrScheduling({{ ...copy, diarizationHopMs: undefined }}).diarizationHopMs, 2000);
assert.equal(asrCpuProvider(false, {{ ...copy, diarizationHopMs: 2000 }}),
  'cpu;AmphionQos=user-initiated;AmphionCpuIds=4,6;AmphionAllowSpinning=0');
for (const hop of [249, 10001, 0, -1000, 1000.5, NaN, Infinity, '2000']) {{
  assert.throws(() => snapshotAsrScheduling({{ ...copy, diarizationHopMs: hop }}));
}}
for (const hop of [250, 1000, 2000, 10000]) {{
  assert.equal(snapshotAsrScheduling({{ ...copy, diarizationHopMs: hop }}).diarizationHopMs, hop);
}}
// Both levers ship on: the field says 'auto' and, at the default 2000 ms
// cadence, that resolves to 'background'. The snapshot carries the request
// verbatim, so lowering the cadence later stays legal.
assert.equal(c.diarizationQos, 'auto');
assert.equal(resolveDiarizationQos(c.diarizationQos, c.diarizationHopMs), 'background');
assert.equal(resolveDiarizationQos('auto', 1999), 'inherit');
assert.equal(resolveDiarizationQos('inherit', 4000), 'inherit');
assert.equal(resolveDiarizationQos('utility', 250), 'utility');
// null and undefined both mean "not set", matching the other two knobs.
assert.equal(snapshotAsrScheduling({{ ...copy, diarizationQos: undefined }}).diarizationQos, 'auto');
assert.equal(snapshotAsrScheduling({{ ...copy, diarizationQos: null }}).diarizationQos, 'auto');
const faster = snapshotAsrScheduling({{ ...copy, diarizationQos: 'auto', diarizationHopMs: 1000 }});
assert.equal(resolveDiarizationQos(faster.diarizationQos, faster.diarizationHopMs), 'inherit');
for (const q of ['auto', 'utility', 'default', 'inherit']) {{
  assert.equal(snapshotAsrScheduling({{ ...copy, diarizationQos: q }}).diarizationQos, q);
}}
for (const q of ['Background', 'low', '', 0]) {{
  assert.throws(() => snapshotAsrScheduling({{ ...copy, diarizationQos: q }}));
}}
// 'background' stretches a window to 1421 ms of its 1500 ms budget at the
// default hop, so the pair is rejected rather than merely discouraged.
assert.throws(
  () => snapshotAsrScheduling({{ ...copy, diarizationQos: 'background', diarizationHopMs: 1000 }}),
  /diarizationHopMs >= 2000/);
assert.throws(
  () => snapshotAsrScheduling({{ ...copy, diarizationQos: 'background', diarizationHopMs: 1999 }}),
  /diarizationHopMs >= 2000/);
for (const hop of [2000, 4000, 10000]) {{
  const ok = snapshotAsrScheduling({{ ...copy, diarizationQos: 'background', diarizationHopMs: hop }});
  assert.equal(ok.diarizationQos, 'background');
  assert.equal(ok.diarizationHopMs, hop);
}}
// Neither knob reaches the recognizer provider string.
assert.equal(asrCpuProvider(false, {{ ...copy, diarizationQos: 'background', diarizationHopMs: 2000 }}),
  'cpu;AmphionQos=user-initiated;AmphionCpuIds=4,6;AmphionAllowSpinning=0');
"""
        subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', script], check=True)

    def test_native_policy_ownership_restoration_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            subprocess.run(['git', 'apply', '--include=sherpa-onnx/csrc/harmony-scheduling.*',
                            str(PATCH)], cwd=destination, check=True)
            subprocess.run(['git', 'apply', str(IDLE_PATCH)], cwd=destination, check=True)
            binary = destination / 'scheduling-test'
            subprocess.run(['c++', '-std=c++17', '-pthread', '-D__OHOS__',
                            '-I' + str(FIXTURES), '-I' + str(destination),
                            str(destination / 'sherpa-onnx/csrc/harmony-scheduling.cc'),
                            str(FIXTURES / 'scheduling_test.cc'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=15)


if __name__ == '__main__':
    unittest.main()
