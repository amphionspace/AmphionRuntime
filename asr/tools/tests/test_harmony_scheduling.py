import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/AsrSchedulingConfig.ts'
PATCH = ROOT / 'third_party/patches/sherpa-amphion/0027-feat-harmony-asr-thread-scheduling.patch'
FIXTURES = Path(__file__).with_name('harmony_scheduling')


class HarmonySchedulingTest(unittest.TestCase):
    def test_configuration_defaults_validation_and_snapshot(self):
        script = f"""
import assert from 'node:assert/strict';
import {{ AsrSchedulingConfig, snapshotAsrScheduling, asrCpuProvider }} from {POLICY.as_uri()!r};
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
"""
        subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', script], check=True)

    def test_native_policy_ownership_restoration_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            subprocess.run(['git', 'apply', '--include=sherpa-onnx/csrc/harmony-scheduling.*',
                            str(PATCH)], cwd=destination, check=True)
            binary = destination / 'scheduling-test'
            subprocess.run(['c++', '-std=c++17', '-pthread', '-D__OHOS__',
                            '-I' + str(FIXTURES), '-I' + str(destination),
                            str(destination / 'sherpa-onnx/csrc/harmony-scheduling.cc'),
                            str(FIXTURES / 'scheduling_test.cc'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=15)


if __name__ == '__main__':
    unittest.main()
