"""Focused execution tests for Community native cooperative cancellation."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / "asr/harmony/sdk/src/main/cpp"
SOURCE = CPP / "community_diarization.cpp"
INFERENCE = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/CommunityDiarizationInference.ets"
SCHEDULING = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/AsrSchedulingConfig.ts"


class HarmonyCommunityNativeCancellationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        start = source.index("class CommunityCancellation {")
        helper_start = source.index("template <typename Function>", start)
        helper_end = source.index("#ifndef __ANDROID__", helper_start)
        cls.controller = source[start:helper_start]
        cls.run_helper = source[helper_start:helper_end]

    def _compile_and_run(self, program, timeout=30):
        compiler = shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("C++17 compiler unavailable")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cancel.cpp"
            binary = Path(directory) / "cancel"
            source.write_text(program)
            subprocess.run([
                compiler, "-std=c++17", "-O2", "-pthread", "-I", str(CPP),
                str(source), "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True, timeout=timeout)

    def test_controller_terminates_active_run_and_keeps_runoptions_alive(self):
        program = r'''
#include "community_cancel.h"
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <vector>
namespace Ort {
struct RunOptions {
  static std::atomic<int> destroyed;
  std::atomic<bool> terminated{false};
  RunOptions() = default;
  explicit RunOptions(std::nullptr_t) {}
  ~RunOptions() { ++destroyed; }
  RunOptions& SetTerminate() { terminated.store(true, std::memory_order_release); return *this; }
};
std::atomic<int> RunOptions::destroyed{0};
}
''' + self.controller + self.run_helper + r'''
int main() {
  auto cancellation = std::make_shared<CommunityCancellation>();
  std::atomic<bool> entered{false};
  std::atomic<bool> left{false};
  int result = 0;
  std::thread worker([&] {
    result = RunCommunityOrt(cancellation, [&](const Ort::RunOptions& options) {
      entered.store(true, std::memory_order_release);
      while (!options.terminated.load(std::memory_order_acquire)) std::this_thread::yield();
      left.store(true, std::memory_order_release);
      return 17;
    });
  });
  while (!entered.load(std::memory_order_acquire)) std::this_thread::yield();
  cancellation->Cancel();
  worker.join();
  assert(left.load(std::memory_order_acquire));
  assert(result == 17);
  assert(cancellation->IsCancelled());
  assert(Ort::RunOptions::destroyed.load() == 1);
  bool rejected = false;
  try {
    RunCommunityOrt(cancellation, [](const Ort::RunOptions&) { return 1; });
  } catch (const std::runtime_error& error) {
    rejected = std::string(error.what()) == "Community operation cancelled";
  }
  assert(rejected);
}
'''
        self._compile_and_run(program)

    def test_register_cancel_race_marks_every_accepted_run(self):
        program = r'''
#include "community_cancel.h"
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
namespace Ort {
struct RunOptions {
  RunOptions() = default;
  explicit RunOptions(std::nullptr_t) {}
  std::atomic<bool> terminated{false};
  RunOptions& SetTerminate() { terminated.store(true, std::memory_order_release); return *this; }
};
}
''' + self.controller + r'''
int main() {
  for (int iteration = 0; iteration < 2000; ++iteration) {
    auto cancellation = std::make_shared<CommunityCancellation>();
    Ort::RunOptions options;
    std::atomic<bool> go{false};
    bool registered = false;
    std::thread registrar([&] {
      while (!go.load(std::memory_order_acquire)) std::this_thread::yield();
      registered = cancellation->Register(&options);
    });
    std::thread canceller([&] {
      while (!go.load(std::memory_order_acquire)) std::this_thread::yield();
      cancellation->Cancel();
    });
    go.store(true, std::memory_order_release);
    registrar.join();
    canceller.join();
    if (registered) {
      assert(options.terminated.load(std::memory_order_acquire));
      cancellation->Unregister(&options);
    }
    assert(cancellation->IsCancelled());
  }
}
'''
        self._compile_and_run(program)

    def test_cancel_does_not_touch_another_instance(self):
        program = r'''
#include "community_cancel.h"
#include <algorithm>
#include <cassert>
#include <memory>
#include <mutex>
#include <vector>
namespace Ort {
struct RunOptions {
  RunOptions() = default;
  explicit RunOptions(std::nullptr_t) {}
  bool terminated = false;
  RunOptions& SetTerminate() { terminated = true; return *this; }
};
}
''' + self.controller + r'''
int main() {
  auto first = std::make_shared<CommunityCancellation>();
  auto second = std::make_shared<CommunityCancellation>();
  Ort::RunOptions firstRun, secondRun;
  assert(first->Register(&firstRun));
  assert(second->Register(&secondRun));
  first->Cancel();
  assert(first->IsCancelled() && firstRun.terminated);
  assert(!second->IsCancelled() && !secondRun.terminated);
  second->Unregister(&secondRun);
  first->Unregister(&firstRun);
}
'''
        self._compile_and_run(program)

    def test_cpu_cancellation_and_normal_token_are_deterministic(self):
        program = r'''
#include "community_cluster.h"
#include "community_fbank.h"
#include <cassert>
#include <cmath>
#include <string>
int main() {
  std::vector<float> pcm(160000, .1f), constants(400 + 80 * 257, 1.f);
  auto normal = community::Fbank(pcm, constants);
  community::CancellationToken active;
  auto same = community::Fbank(pcm, constants, &active);
  assert(normal.size() == same.size());
  for (size_t i = 0; i < normal.size(); ++i) assert(normal[i] == same[i]);
  active.Cancel();
  bool fbankCancelled = false;
  try { (void)community::Fbank(pcm, constants, &active); }
  catch (const std::runtime_error& error) { fbankCancelled = std::string(error.what()) == "Community operation cancelled"; }
  assert(fbankCancelled);
  std::vector<float> segments(589 * 3), embeddings(768);
  bool clusterCancelled = false;
  try { (void)community::Cluster(segments, embeddings, 1, community::Plda{}, 4, {}, {}, {}, &active); }
  catch (const std::runtime_error& error) { clusterCancelled = std::string(error.what()) == "Community operation cancelled"; }
  assert(clusterCancelled);
  bool reconstructionCancelled = false;
  try { (void)community::Reconstruct(segments, {-2, -2, -2}, {0}, 0, 4, {}, &active); }
  catch (const std::runtime_error& error) { reconstructionCancelled = std::string(error.what()) == "Community operation cancelled"; }
  assert(reconstructionCancelled);
}
'''
        self._compile_and_run(program, timeout=60)

    def test_ets_cancel_handles_late_load_and_rejects_new_work(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js unavailable")
        source = INFERENCE.read_text()
        source = source.split("export class CommunityDiarizationInference", 1)[1]
        source = "export class CommunityDiarizationInference" + source.split("\nexport {", 1)[0]
        script = (
            "import assert from 'node:assert/strict';\n"
            f"import {{ asrSchedulingTokens }} from {SCHEDULING.as_uri()!r};\n"
            + r'''
const loads = [], cancelled = [], closed = [], processed = [], clustered = [];
function loadCommunityDiarizationResources(resources, threads, scheduling) {
  return new Promise((resolve, reject) => loads.push({resources, threads, scheduling, resolve, reject}));
}
function cancelCommunityDiarization(handle) { cancelled.push(handle); }
function closeCommunityDiarization(handle) { closed.push(handle); }
async function processCommunityDiarization(handle, samples) { processed.push(handle); return samples; }
async function clusterCommunityDiarization(handle) { clustered.push(handle); return '{}'; }
''' + source + r'''
const first = new CommunityDiarizationInference();
const pending = first.load({resourceManager: {name: 'late'}});
first.cancel();
await assert.rejects(first.process(new Float32Array(1)), /not loaded/);
loads[0].resolve(41);
await pending;
assert.deepEqual(cancelled, [41]);
assert.deepEqual(closed, [41]);
assert.deepEqual(processed, []);
first.cancel();
assert.deepEqual(cancelled, [41]);

const second = new CommunityDiarizationInference();
const loaded = second.load({resourceManager: {name: 'ready'}});
loads[1].resolve(42);
await loaded;
await second.process(new Float32Array(1));
await second.cluster(new Float32Array(1), new Float32Array(1), new Float32Array(),
  new Float32Array(), 1, new Float64Array([0]), 0, new Float32Array());
second.cancel();
await assert.rejects(second.process(new Float32Array(1)), /not loaded/);
await assert.rejects(second.cluster(new Float32Array(1), new Float32Array(1), new Float32Array(),
  new Float32Array(), 1, new Float64Array([0]), 0, new Float32Array()), /not loaded/);
assert.deepEqual(cancelled, [41, 42]);
second.close();
assert.deepEqual(closed, [41, 42]);
assert.deepEqual(processed, [42]);
assert.deepEqual(clustered, [42]);
'''
        )
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "community-cancel.ts"
            harness.write_text(script)
            subprocess.run([node, "--experimental-strip-types", str(harness)], check=True, cwd=ROOT)


if __name__ == "__main__":
    unittest.main()
