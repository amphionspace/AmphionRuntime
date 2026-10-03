"""Host bitwise regression for the production extra-run pooling fragment.

The reference loop is frozen from the clean 315181... source.  The production
side is extracted from community_diarization.cpp and compiled into this C++
harness, so the test executes the actual production loop with a deterministic
pooling stub instead of reimplementing packing in Python.
"""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "asr/harmony/sdk/src/main/cpp/community_diarization.cpp"
CLEAN_SOURCE_SHA256 = "315181910cb98eb207eb46e7485d1492fd1524222829b37945fcceb642cbac31"
REFERENCE_LOOP_SHA256 = "9c9695f186fd592546824ecad7bf23acb1a08e0e18eefb0cda561cf6f6113636"

# This is the exact extra-run loop from the clean 315 source.  It is kept in
# the test rather than read from the working tree, so changing production code
# cannot silently change the oracle.
REFERENCE_LOOP = r'''    for (int channel = 0; channel < 3; ++channel) {
      const int base = channel * 589;
      int begin = -1;
      int kind = -1; // 1 = clean, 0 = overlap/blocked, -1 = inactive.
      for (int frame = 0; frame <= 589; ++frame) {
        community::CheckCancellation(cancellation_->token());
        const bool active = frame < 589 && masks[base + frame] > 0;
        const int next_kind = active ? (clean[base + frame] > 0 ? 1 : 0) : -1;
        if (next_kind != kind && begin >= 0) {
          const int end = frame;
          // Match the same frame-center cells used for public reconstruction.
          // Other runs, pauses and overlap must not set this run's level.
          double squared = 0;
          const size_t first = std::min(pcm.size(), static_cast<size_t>(std::llround(495.5 + begin * 270.)));
          const size_t last = std::min(pcm.size(), static_cast<size_t>(std::llround(495.5 + end * 270.)));
          if (kind == 1) for (size_t i = first; i < last; ++i) squared += static_cast<double>(pcm[i]) * pcm[i];
          result.run_rms.push_back(kind == 1 && last > first ? std::sqrt(squared / (last - first)) : 0.f);
          if (kind == 1 && end - begin >= .2 * 589) {
            // The pinned model pools each mask channel independently. When
            // this run is the entire selected channel mask, its vector was
            // already computed from these exact features in this window.
            // A disconnected tail (including a short one) prevents reuse.
            const int selected_frames = std::count(masks.begin() + base,
              masks.begin() + base + 589, 1.f);
            if (selected_frames == end - begin) {
              result.run_embeddings.insert(result.run_embeddings.end(), values + channel * 256,
                                           values + (channel + 1) * 256);
            } else {
              std::vector<float> run_masks(3 * 589, 0.f);
              for (int f = begin; f < end; ++f) run_masks[base + f] = 1.f;
              std::vector<Ort::Value> run_tensors;
              run_tensors.push_back(Ort::Value::CreateTensor<float>(memory, encoded_values, 2560 * 125, encoded_shape.data(), 3));
              run_tensors.push_back(Ort::Value::CreateTensor<float>(memory, run_masks.data(), run_masks.size(), mask_shape.data(), 3));
              auto run_output = RunCommunityOrt(cancellation_, [&](const Ort::RunOptions& options) {
                return pooling_.Run(options, names, run_tensors.data(), 2, outputs, 1);
              });
              community::CheckCancellation(cancellation_->token());
              if (run_output[0].GetTensorTypeAndShapeInfo().GetElementCount() != 3 * 256) {
                throw std::runtime_error("invalid Community run embedding output");
              }
              const auto* run_values = run_output[0].GetTensorData<float>();
              result.run_embeddings.insert(result.run_embeddings.end(), run_values + channel * 256,
                                           run_values + (channel + 1) * 256);
            }
          } else if (kind == 0) {
            // A finite zero vector would become eligible for a long overlap
            // run. NaN is deliberately rejected by the clusterer and keeps
            // the overlap anonymous without inventing a speaker identity.
            result.run_embeddings.insert(result.run_embeddings.end(), 256,
                                         std::numeric_limits<float>::quiet_NaN());
          } else {
            result.run_embeddings.insert(result.run_embeddings.end(), 256, 0.f);
          }
          result.run_ranges.push_back(0);
          result.run_ranges.push_back(channel);
          result.run_ranges.push_back(begin);
          result.run_ranges.push_back(end);
          begin = -1;
        }
        if (next_kind >= 0 && begin < 0) begin = frame;
        kind = next_kind;
      }
    }
'''

COMMON_CPP = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace Ort {
struct RunOptions {};
struct MemoryInfo {};
struct TensorInfo {
  size_t count;
  size_t GetElementCount() const { return count; }
};
struct Value {
  const float* data = nullptr;
  size_t count = 0;
  std::shared_ptr<std::vector<float>> storage;
  template <typename T>
  static Value CreateTensor(MemoryInfo&, T* pointer, size_t element_count,
                            const int64_t*, size_t) {
    Value value;
    value.data = reinterpret_cast<const float*>(pointer);
    value.count = element_count;
    return value;
  }
  static Value Output(std::vector<float> values, size_t element_count) {
    Value value;
    value.storage = std::make_shared<std::vector<float>>(std::move(values));
    value.data = value.storage->data();
    value.count = element_count;
    return value;
  }
  TensorInfo GetTensorTypeAndShapeInfo() const { return {count}; }
  template <typename T>
  const T* GetTensorData() const { return reinterpret_cast<const T*>(data); }
};
}  // namespace Ort

struct CommunityCancellation {
  bool before_run = false;
  bool after_run = false;
  bool cancelled = false;
  CommunityCancellation* token() { return this; }
};

namespace community {
inline void CheckCancellation(CommunityCancellation* cancellation) {
  if (cancellation->cancelled) throw std::runtime_error("cancelled");
}
}  // namespace community

template <typename Function>
auto RunCommunityOrt(const std::shared_ptr<CommunityCancellation>& cancellation,
                     Function&& function) {
  if (cancellation->before_run) throw std::runtime_error("cancelled before Run");
  auto output = function(Ort::RunOptions{});
  if (cancellation->after_run) cancellation->cancelled = true;
  return output;
}

struct Result {
  std::vector<float> run_embeddings;
  std::vector<float> run_rms;
  std::vector<float> run_ranges;
};

struct Input {
  std::vector<float> pcm;
  std::vector<float> masks;
  std::vector<float> clean;
  std::vector<float> base;
  std::vector<float> encoded;
};

struct RunSpec {
  int channel;
  int begin;
  int end;
};

struct PoolCall {
  std::array<float, 3 * 589> masks{};
  const float* encoded = nullptr;
};

struct FakePooling {
  bool bad_shape = false;
  std::vector<PoolCall> calls;

  std::vector<Ort::Value> Run(const Ort::RunOptions&, const char* const*, Ort::Value* inputs,
                              size_t, const char* const*, size_t) {
    PoolCall call;
    call.encoded = inputs[0].data;
    std::copy(inputs[1].data, inputs[1].data + 3 * 589, call.masks.begin());
    calls.push_back(call);
    if (bad_shape) return {Ort::Value::Output({0.f}, 1)};
    std::vector<float> output(3 * 256, 0.f);
    for (int slot = 0; slot < 3; ++slot) {
      float weighted_frames = 0.f;
      for (int frame = 0; frame < 589; ++frame) {
        if (call.masks[slot * 589 + frame] > 0.f) {
          weighted_frames += static_cast<float>((frame + 1) * 0.001);
        }
      }
      for (int dimension = 0; dimension < 256; ++dimension) {
        // Independent of slot: relocating a mask must preserve its vector.
        output[slot * 256 + dimension] =
            weighted_frames + static_cast<float>(dimension) * 0.03125f;
      }
    }
    return {Ort::Value::Output(std::move(output), 3 * 256)};
  }
};

struct RunContext {
  std::shared_ptr<CommunityCancellation> cancellation =
      std::make_shared<CommunityCancellation>();
  FakePooling pooling;
  const float* encoded_address = nullptr;
};

Input EmptyInput() {
  Input input;
  input.pcm.resize(160000);
  input.masks.assign(3 * 589, 0.f);
  input.clean.assign(3 * 589, 0.f);
  input.base.resize(3 * 256);
  input.encoded.resize(2560 * 125);
  for (size_t i = 0; i < input.pcm.size(); ++i) {
    input.pcm[i] = static_cast<float>(static_cast<int>(i % 97) - 48) * 0.013f;
  }
  for (size_t i = 0; i < input.base.size(); ++i) {
    input.base[i] = static_cast<float>(1000 + i) * 0.001f;
  }
  for (size_t i = 0; i < input.encoded.size(); ++i) {
    input.encoded[i] = static_cast<float>(i % 251) * 0.001f;
  }
  return input;
}

void AddRun(Input& input, int channel, int begin, int end, bool clean) {
  assert(channel >= 0 && channel < 3);
  assert(begin >= 0 && begin < end && end <= 589);
  for (int frame = begin; frame < end; ++frame) {
    input.masks[channel * 589 + frame] = 1.f;
    input.clean[channel * 589 + frame] = clean ? 1.f : 0.f;
  }
}

bool SameBits(const std::vector<float>& left, const std::vector<float>& right) {
  return left.size() == right.size() &&
         std::memcmp(left.data(), right.data(), left.size() * sizeof(float)) == 0;
}

void AssertSameResult(const Result& expected, const Result& actual) {
  assert(SameBits(expected.run_embeddings, actual.run_embeddings));
  assert(SameBits(expected.run_rms, actual.run_rms));
  assert(SameBits(expected.run_ranges, actual.run_ranges));
}

void AssertPackedCalls(const RunContext& context, const std::vector<RunSpec>& extras) {
  const size_t expected_calls = (extras.size() + 2) / 3;
  assert(context.pooling.calls.size() == expected_calls);
  const float* encoded_address = expected_calls == 0 ? nullptr : context.pooling.calls[0].encoded;
  assert(expected_calls == 0 || encoded_address == context.encoded_address);
  for (size_t call_index = 0; call_index < context.pooling.calls.size(); ++call_index) {
    const PoolCall& call = context.pooling.calls[call_index];
    assert(call.encoded == encoded_address);
    const size_t first_extra = call_index * 3;
    const size_t slot_count = std::min<size_t>(3, extras.size() - first_extra);
    for (size_t slot = 0; slot < 3; ++slot) {
      for (int frame = 0; frame < 589; ++frame) {
        float expected = 0.f;
        if (slot < slot_count) {
          const RunSpec& run = extras[first_extra + slot];
          expected = (frame >= run.begin && frame < run.end) ? 1.f : 0.f;
        }
        assert(call.masks[slot * 589 + frame] == expected);
      }
    }
  }
}

void AssertReferenceCalls(const RunContext& context, const std::vector<RunSpec>& extras) {
  assert(context.pooling.calls.size() == extras.size());
  for (size_t index = 0; index < extras.size(); ++index) {
    const PoolCall& call = context.pooling.calls[index];
    const RunSpec& run = extras[index];
    for (int slot = 0; slot < 3; ++slot) {
      for (int frame = 0; frame < 589; ++frame) {
        const float expected = slot == run.channel && frame >= run.begin && frame < run.end ? 1.f : 0.f;
        assert(call.masks[slot * 589 + frame] == expected);
      }
    }
  }
}

std::optional<Result> RunReference(const Input& input, RunContext& context) {
  try {
    Result result;
    std::vector<float> pcm = input.pcm;
    std::vector<float> masks = input.masks;
    std::vector<float> clean = input.clean;
    std::vector<float> encoded = input.encoded;
    std::vector<float> base_values = input.base;
    const float* values = base_values.data();
    float* encoded_values = encoded.data();
    context.encoded_address = encoded.data();
    Ort::MemoryInfo memory;
    std::array<int64_t, 3> encoded_shape{1, 2560, 125};
    std::array<int64_t, 3> mask_shape{1, 3, 589};
    const char* names[] = {"encoded", "masks"};
    const char* outputs[] = {"embeddings"};
    auto cancellation_ = context.cancellation;
    auto& pooling_ = context.pooling;
''' + REFERENCE_LOOP + r'''
    return result;
  } catch (...) {
    return std::nullopt;
  }
}

std::optional<Result> RunProduction(const Input& input, RunContext& context) {
  try {
    Result result;
    std::vector<float> pcm = input.pcm;
    std::vector<float> masks = input.masks;
    std::vector<float> clean = input.clean;
    std::vector<float> encoded = input.encoded;
    std::vector<float> base_values = input.base;
    const float* values = base_values.data();
    float* encoded_values = encoded.data();
    context.encoded_address = encoded.data();
    Ort::MemoryInfo memory;
    std::array<int64_t, 3> encoded_shape{1, 2560, 125};
    std::array<int64_t, 3> mask_shape{1, 3, 589};
    const char* names[] = {"encoded", "masks"};
    const char* outputs[] = {"embeddings"};
    auto cancellation_ = context.cancellation;
    auto& pooling_ = context.pooling;
''' + "__PRODUCTION_FRAGMENT__" + r'''
    return result;
  } catch (...) {
    return std::nullopt;
  }
}

int main() {
  auto check_case = [](const char* name, const Input& input,
                       const std::vector<RunSpec>& extras) {
    RunContext reference_context;
    RunContext production_context;
    const auto reference = RunReference(input, reference_context);
    const auto production = RunProduction(input, production_context);
    assert(reference.has_value());
    assert(production.has_value());
    AssertSameResult(*reference, *production);
    AssertReferenceCalls(reference_context, extras);
    AssertPackedCalls(production_context, extras);
    if (std::string(name).empty()) std::abort();
  };

  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 589, true);       // full-channel reuse
    AddRun(input, 1, 10, 127, true);      // short117 -> zero
    AddRun(input, 2, 200, 400, false);    // overlap -> quiet NaN
    check_case("no-extra", input, {});
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);
    AddRun(input, 0, 200, 317, true);     // short tail
    check_case("one-extra", input, {{0, 0, 130}});
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);
    AddRun(input, 0, 180, 310, true);
    check_case("two-extra", input, {{0, 0, 130}, {0, 180, 310}});
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);
    AddRun(input, 0, 180, 310, true);
    AddRun(input, 0, 390, 520, true);
    check_case("three-extra", input,
               {{0, 0, 130}, {0, 180, 310}, {0, 390, 520}});
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);
    AddRun(input, 0, 150, 280, true);
    AddRun(input, 0, 300, 430, true);
    AddRun(input, 0, 471, 589, true);     // exactly threshold118, last frame
    check_case("four-extra-3-plus-1", input,
               {{0, 0, 130}, {0, 150, 280}, {0, 300, 430}, {0, 471, 589}});
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);       // extra channel0
    AddRun(input, 0, 200, 317, true);     // short117 channel0
    AddRun(input, 1, 180, 310, true);     // extra channel1
    AddRun(input, 1, 350, 500, false);    // overlap channel1
    AddRun(input, 2, 300, 400, false);    // overlap before channel2 extra
    AddRun(input, 2, 471, 589, true);     // extra channel2, end boundary
    check_case("mixed-scatter-rms", input,
               {{0, 0, 130}, {1, 180, 310}, {2, 471, 589}});
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);
    AddRun(input, 0, 200, 317, true);
    RunContext context;
    context.cancellation->before_run = true;
    assert(!RunProduction(input, context).has_value());
    assert(context.pooling.calls.empty());
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);
    AddRun(input, 0, 200, 317, true);
    RunContext context;
    context.cancellation->after_run = true;
    assert(!RunProduction(input, context).has_value());
    assert(context.pooling.calls.size() == 1);
  }
  {
    Input input = EmptyInput();
    AddRun(input, 0, 0, 130, true);
    AddRun(input, 0, 200, 317, true);
    RunContext context;
    context.pooling.bad_shape = true;
    assert(!RunProduction(input, context).has_value());
    assert(context.pooling.calls.size() == 1);
  }
  return 0;
}
'''


def _production_fragment():
    source = SOURCE.read_text()
    start = source.index("    // Keep the full-window vectors above for compatibility")
    end = source.index("    result.embedding_ms = Milliseconds(start);", start)
    fragment = source[start:end]
    if "flush_pending_runs" not in fragment or "pending_runs" not in fragment:
        raise AssertionError("production pooling fragment did not contain packing implementation")
    return fragment


class HarmonyCommunityPoolPackingTest(unittest.TestCase):
    def test_production_fragment_matches_frozen_loop_and_batches_masks(self):
        source_bytes = SOURCE.read_bytes()
        self.assertNotEqual(hashlib.sha256(source_bytes).hexdigest(), CLEAN_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(REFERENCE_LOOP.encode()).hexdigest(), REFERENCE_LOOP_SHA256)
        fragment = _production_fragment()
        program = COMMON_CPP.replace("__PRODUCTION_FRAGMENT__", fragment)
        compiler = shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("C++17 compiler unavailable")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pool_packing.cpp"
            binary = Path(directory) / "pool_packing"
            source.write_text(program)
            subprocess.run(
                [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", str(source), "-o", str(binary)],
                check=True,
            )
            subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
