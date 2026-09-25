#include "community_cluster.h"
#include "community_fbank.h"
#include "onnxruntime_cxx_api.h"
#include <node_api.h>
#include <array>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <unordered_map>

namespace {
using Clock = std::chrono::steady_clock;
double Milliseconds(Clock::time_point start) {
  return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

template <typename T>
std::vector<T> CopyArray(napi_env env, napi_value value, napi_typedarray_type expected) {
  napi_typedarray_type type;
  size_t length = 0, offset = 0;
  void* data = nullptr;
  napi_value buffer = nullptr, byte_length = nullptr;
  uint32_t bytes = 0;
  if (napi_get_typedarray_info(env, value, &type, &length, &data, &buffer, &offset) != napi_ok ||
      type != expected || napi_get_named_property(env, value, "byteLength", &byte_length) != napi_ok ||
      napi_get_value_uint32(env, byte_length, &bytes) != napi_ok || bytes % sizeof(T)) {
    throw std::runtime_error("invalid Community typed array");
  }
  void* buffer_data = nullptr;
  size_t buffer_bytes = 0;
  if (napi_get_arraybuffer_info(env, buffer, &buffer_data, &buffer_bytes) != napi_ok ||
      offset > buffer_bytes || bytes > buffer_bytes - offset) {
    throw std::runtime_error("Community typed array exceeds its backing buffer");
  }
  const size_t elements = bytes / sizeof(T);
  // Match the existing Harmony bridge: affected releases report bytes here,
  // while standard Node-API reports elements. Keep valid subarray views intact.
  if (length != elements && length != bytes) {
    throw std::runtime_error("inconsistent Community typed array length");
  }
  std::vector<T> result(elements);
  if (bytes) std::memcpy(result.data(), data, bytes);
  return result;
}

struct Window {
  std::vector<float> segments, embeddings;
  double segmentation_ms = 0, feature_ms = 0, embedding_ms = 0;
};

class Model {
 public:
  Model(const std::vector<uint8_t>& segmentation, const std::vector<uint8_t>& embedding,
        const std::vector<uint8_t>& feature, const std::vector<uint8_t>& plda)
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-community") {
    if (feature.size() != (400 + 80 * 257) * sizeof(float)) {
      throw std::runtime_error("invalid Community feature constants");
    }
    constants_.resize(feature.size() / sizeof(float));
    std::memcpy(constants_.data(), feature.data(), feature.size());
    constexpr size_t doubles = 256 + 128 + 256 * 128 + 128 + 128 * 128 + 128;
    if (plda.size() != 16 + doubles * sizeof(double)) throw std::runtime_error("invalid Community PLDA");
    uint32_t header[4];
    std::memcpy(header, plda.data(), sizeof(header));
    if (header[0] != 0x434d504c || header[1] != 1 || header[2] != 256 || header[3] != 128) {
      throw std::runtime_error("unsupported Community PLDA format");
    }
    size_t pos = 16;
    auto vector = [&](size_t n) {
      community::Vec v(n);
      std::memcpy(v.data(), plda.data() + pos, n * sizeof(double));
      pos += n * sizeof(double);
      return v;
    };
    plda_.mean1 = vector(256);
    plda_.mean2 = vector(128);
    for (int row = 0; row < 256; ++row) plda_.lda.push_back(vector(128));
    plda_.mu = vector(128);
    for (int row = 0; row < 128; ++row) plda_.transform.push_back(vector(128));
    plda_.phi = vector(128);
    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetInterOpNumThreads(1);
    options.DisableCpuMemArena();
    options.DisableMemPattern();
    options.SetIntraOpNumThreads(1);
    segmentation_ = Ort::Session(env_, segmentation.data(), segmentation.size(), options);
    options.SetIntraOpNumThreads(4);
    embedding_ = Ort::Session(env_, embedding.data(), embedding.size(), options);
    Ort::AllocatorWithDefaultOptions allocator;
    input_name_ = segmentation_.GetInputNameAllocated(0, allocator).get();
    output_name_ = segmentation_.GetOutputNameAllocated(0, allocator).get();
  }

  Window Process(std::vector<float>& pcm) {
    if (pcm.size() != 160000) throw std::runtime_error("Community requires a 10 second window");
    std::lock_guard<std::mutex> lock(inference_mutex_);
    Window result;
    auto start = Clock::now();
    auto memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    std::array<int64_t, 3> shape{1, 1, 160000};
    auto tensor = Ort::Value::CreateTensor<float>(memory, pcm.data(), pcm.size(), shape.data(), 3);
    const char* input_names[] = {input_name_.c_str()};
    const char* output_names[] = {output_name_.c_str()};
    auto output = segmentation_.Run(Ort::RunOptions{nullptr}, input_names, &tensor, 1, output_names, 1);
    if (output[0].GetTensorTypeAndShapeInfo().GetElementCount() != 589 * 7) {
      throw std::runtime_error("invalid Community segmentation output");
    }
    const auto* logits = output[0].GetTensorData<float>();
    result.segments.resize(589 * 3);
    std::vector<float> masks(3 * 589), clean(3 * 589);
    int clean_count[3] = {};
    constexpr int codes[7] = {0, 1, 2, 4, 3, 5, 6};
    for (int frame = 0; frame < 589; ++frame) {
      int label = std::max_element(logits + frame * 7, logits + (frame + 1) * 7) - (logits + frame * 7);
      int bits = codes[label];
      for (int channel = 0; channel < 3; ++channel) {
        float active = (bits & (1 << channel)) ? 1.f : 0.f;
        result.segments[frame * 3 + channel] = masks[channel * 589 + frame] = active;
        clean[channel * 589 + frame] = (bits & (bits - 1)) == 0 ? active : 0.f;
        clean_count[channel] += clean[channel * 589 + frame];
      }
    }
    for (int channel = 0; channel < 3; ++channel) {
      if (clean_count[channel] > 2) std::copy(clean.begin() + channel * 589,
        clean.begin() + (channel + 1) * 589, masks.begin() + channel * 589);
    }
    result.segmentation_ms = Milliseconds(start);
    start = Clock::now();
    auto features = community::Fbank(pcm, constants_);
    result.feature_ms = Milliseconds(start);
    std::array<int64_t, 3> feature_shape{1, 998, 80}, mask_shape{1, 3, 589};
    std::vector<Ort::Value> tensors;
    tensors.push_back(Ort::Value::CreateTensor<float>(memory, features.data(), features.size(), feature_shape.data(), 3));
    tensors.push_back(Ort::Value::CreateTensor<float>(memory, masks.data(), masks.size(), mask_shape.data(), 3));
    const char* names[] = {"fbank", "masks"};
    const char* outputs[] = {"embeddings"};
    start = Clock::now();
    auto embeddings = embedding_.Run(Ort::RunOptions{nullptr}, names, tensors.data(), 2, outputs, 1);
    if (embeddings[0].GetTensorTypeAndShapeInfo().GetElementCount() != 3 * 256) {
      throw std::runtime_error("invalid Community embedding output");
    }
    const auto* values = embeddings[0].GetTensorData<float>();
    result.embeddings.assign(values, values + 3 * 256);
    result.embedding_ms = Milliseconds(start);
    return result;
  }

  std::string Cluster(const std::vector<float>& segments, const std::vector<float>& embeddings,
                      int max_speakers) const {
    if (segments.empty() || segments.size() % (589 * 3) || max_speakers < 1 || max_speakers > 4) {
      throw std::runtime_error("invalid Community clustering input");
    }
    int windows = segments.size() / (589 * 3);
    auto result = community::Cluster(segments, embeddings, windows, plda_, max_speakers);
    auto turns = community::Reconstruct(segments, result.hard, windows);
    std::ostringstream json;
    json << std::setprecision(17) << "{\"speakerCount\":" << result.centroids.size();
    auto ints = [&](const char* key, const std::vector<int>& values) {
      json << ",\"" << key << "\":[";
      for (size_t i = 0; i < values.size(); ++i) { if (i) json << ','; json << values[i]; }
      json << ']';
    };
    ints("hard", result.hard);
    ints("trainingIndices", result.trainingIndices);
    ints("ahc", result.ahc);
    auto matrix = [&](const char* key, const community::Matrix& rows) {
      json << ",\"" << key << "\":[";
      for (size_t i = 0; i < rows.size(); ++i) {
        if (i) json << ',';
        json << '[';
        for (size_t j = 0; j < rows[i].size(); ++j) {
          if (j) json << ',';
          if (std::isfinite(rows[i][j])) json << rows[i][j];
          else json << "null";
        }
        json << ']';
      }
      json << ']';
    };
    matrix("scores", result.scores);
    matrix("centroids", result.centroids);
    matrix("posteriors", result.vbx.q);
    json << ",\"usedKMeans\":" << (result.usedKMeans ? "true" : "false");
    json << ",\"priors\":[";
    for (size_t i = 0; i < result.vbx.priors.size(); ++i) { if (i) json << ','; json << result.vbx.priors[i]; }
    json << "],\"turns\":[";
    for (size_t i = 0; i < turns.size(); ++i) {
      if (i) json << ',';
      json << '[' << turns[i].begin * 1000 << ',' << turns[i].end * 1000 << ',' << turns[i].speaker << ']';
    }
    json << "]}";
    return json.str();
  }

 private:
  Ort::Env env_;
  Ort::Session segmentation_{nullptr}, embedding_{nullptr};
  std::string input_name_, output_name_;
  std::vector<float> constants_;
  community::Plda plda_;
  std::mutex inference_mutex_;
};

// Each session owns its handle. Async calls keep a shared reference after close;
// the ArkTS client also keeps its Runtime lease until all calls have settled.
std::mutex model_mutex;
std::unordered_map<uint32_t, std::shared_ptr<Model>> models;
uint32_t next_handle = 1;
enum class Operation { Load, Process, Cluster };
struct Work {
  Operation operation;
  napi_async_work work = nullptr;
  napi_deferred deferred = nullptr;
  std::shared_ptr<Model> model;
  std::array<std::vector<uint8_t>, 4> assets;
  std::vector<float> pcm, segments, embeddings;
  Window window;
  int max_speakers = 4;
  std::string result, error;
};
void Execute(napi_env, void* data) {
  auto& task = *static_cast<Work*>(data);
  try {
    if (task.operation == Operation::Load) {
      task.model = std::make_shared<Model>(task.assets[0], task.assets[1], task.assets[2], task.assets[3]);
    } else if (task.operation == Operation::Process) task.window = task.model->Process(task.pcm);
    else task.result = task.model->Cluster(task.segments, task.embeddings, task.max_speakers);
  } catch (const std::exception& error) { task.error = error.what(); }
}
void FloatProperty(napi_env env, napi_value object, const char* name, const std::vector<float>& values) {
  napi_value buffer, array;
  void* bytes = nullptr;
  napi_create_arraybuffer(env, values.size() * sizeof(float), &bytes, &buffer);
  if (!values.empty()) std::memcpy(bytes, values.data(), values.size() * sizeof(float));
  napi_create_typedarray(env, napi_float32_array, values.size(), buffer, 0, &array);
  napi_set_named_property(env, object, name, array);
}
void NumberProperty(napi_env env, napi_value object, const char* name, double value) {
  napi_value number;
  napi_create_double(env, value, &number);
  napi_set_named_property(env, object, name, number);
}
void Complete(napi_env env, napi_status status, void* data) {
  std::unique_ptr<Work> task(static_cast<Work*>(data));
  if (status != napi_ok && task->error.empty()) task->error = "Community operation cancelled";
  napi_value value = nullptr;
  if (!task->error.empty()) {
    napi_value message;
    napi_create_string_utf8(env, task->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_create_error(env, nullptr, message, &value);
    napi_reject_deferred(env, task->deferred, value);
  } else {
    if (task->operation == Operation::Load) {
      std::lock_guard<std::mutex> lock(model_mutex);
      uint32_t handle = next_handle++;
      models.emplace(handle, std::move(task->model));
      napi_create_uint32(env, handle, &value);
    } else if (task->operation == Operation::Process) {
      napi_create_object(env, &value);
      FloatProperty(env, value, "segments", task->window.segments);
      FloatProperty(env, value, "embeddings", task->window.embeddings);
      NumberProperty(env, value, "segmentationMs", task->window.segmentation_ms);
      NumberProperty(env, value, "featureMs", task->window.feature_ms);
      NumberProperty(env, value, "embeddingMs", task->window.embedding_ms);
    } else napi_create_string_utf8(env, task->result.c_str(), task->result.size(), &value);
    napi_resolve_deferred(env, task->deferred, value);
  }
  napi_delete_async_work(env, task->work);
}
napi_value Queue(napi_env env, napi_callback_info info, Operation operation) {
  size_t count = 4;
  napi_value args[4] = {};
  napi_get_cb_info(env, info, &count, args, nullptr, nullptr);
  try {
    if (count != (operation == Operation::Process ? 2u : 4u)) throw std::runtime_error("invalid Community arguments");
    auto task = std::make_unique<Work>();
    task->operation = operation;
    if (operation == Operation::Load) {
      for (size_t i = 0; i < 4; ++i) task->assets[i] = CopyArray<uint8_t>(env, args[i], napi_uint8_array);
    } else {
      uint32_t handle = 0;
      if (napi_get_value_uint32(env, args[0], &handle) != napi_ok) throw std::runtime_error("invalid Community handle");
      {
        std::lock_guard<std::mutex> lock(model_mutex);
        auto found = models.find(handle);
        if (found == models.end()) throw std::runtime_error("Community model is closed");
        task->model = found->second;
      }
      if (operation == Operation::Process) task->pcm = CopyArray<float>(env, args[1], napi_float32_array);
      else {
        task->segments = CopyArray<float>(env, args[1], napi_float32_array);
        task->embeddings = CopyArray<float>(env, args[2], napi_float32_array);
        if (napi_get_value_int32(env, args[3], &task->max_speakers) != napi_ok) throw std::runtime_error("invalid speaker cap");
      }
    }
    napi_value promise, name;
    if (napi_create_promise(env, &task->deferred, &promise) != napi_ok) throw std::runtime_error("Community promise failed");
    napi_create_string_utf8(env, "AmphionCommunityDiarization", NAPI_AUTO_LENGTH, &name);
    auto status = napi_create_async_work(env, nullptr, name, Execute, Complete, task.get(), &task->work);
    if (status == napi_ok) status = napi_queue_async_work(env, task->work);
    if (status != napi_ok) {
      if (task->work) napi_delete_async_work(env, task->work);
      napi_value message;
      napi_create_string_utf8(env, "Community work queue failed", NAPI_AUTO_LENGTH, &message);
      napi_reject_deferred(env, task->deferred, message);
    } else task.release();
    return promise;
  } catch (const std::exception& error) { napi_throw_error(env, nullptr, error.what()); return nullptr; }
}
napi_value Load(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Load); }
napi_value Process(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Process); }
napi_value Cluster(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Cluster); }
napi_value Close(napi_env env, napi_callback_info info) {
  size_t count = 1;
  napi_value arg = nullptr, result = nullptr;
  napi_get_cb_info(env, info, &count, &arg, nullptr, nullptr);
  uint32_t handle = 0;
  if (count == 1 && napi_get_value_uint32(env, arg, &handle) == napi_ok) {
    std::lock_guard<std::mutex> lock(model_mutex);
    models.erase(handle);
  }
  napi_get_undefined(env, &result);
  return result;
}
}  // namespace

void RegisterCommunityDiarization(napi_env env, napi_value exports) {
  napi_property_descriptor methods[] = {
    {"loadCommunityDiarization", nullptr, Load, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"processCommunityDiarization", nullptr, Process, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"clusterCommunityDiarization", nullptr, Cluster, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"closeCommunityDiarization", nullptr, Close, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(methods) / sizeof(methods[0]), methods);
}
