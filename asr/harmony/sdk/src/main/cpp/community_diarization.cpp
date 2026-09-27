#include "community_cluster.h"
#include "community_fbank.h"
#include "onnxruntime_cxx_api.h"
#ifndef __ANDROID__
#include <node_api.h>
#endif
#include <array>
#include <fstream>
#include <malloc.h>
#include <unistd.h>
#ifndef __ANDROID__
#include <hilog/log.h>
#endif
#include <chrono>
#include <cstring>
#include <iomanip>
#include <memory>
#include <limits>
#ifndef __ANDROID__
#include <rawfile/raw_file_manager.h>
#endif
#include <mutex>
#include <sstream>
#include <unordered_map>

namespace {
using Clock = std::chrono::steady_clock;
// Temporary allocation ownership probe; removed before product validation.
void TraceCommunityMemory(const char* stage) {
#ifndef __ANDROID__
  long size = 0, resident = 0;
  std::ifstream statm("/proc/self/statm");
  statm >> size >> resident;
  auto m = mallinfo2();
  OH_LOG_Print(LOG_APP, LOG_INFO, 0x0000, "CommunityMemory",
    "stage=%{public}s rss=%{public}ld allocated=%{public}zu free=%{public}zu arena=%{public}zu mmap=%{public}zu",
    stage, resident * sysconf(_SC_PAGESIZE), m.uordblks, m.fordblks, m.arena, m.hblkhd);
#endif
}

double Milliseconds(Clock::time_point start) {
  return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

#ifndef __ANDROID__
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

#endif

struct Window {
  std::vector<float> segments, embeddings;
  // [window, channel, begin frame, end frame) for each contiguous clean run.
  std::vector<float> run_embeddings;
  std::vector<float> run_ranges;
  std::vector<float> run_rms;
  double segmentation_ms = 0, feature_ms = 0, embedding_ms = 0;
};

#ifndef __ANDROID__
std::vector<uint8_t> ReadCommunityAsset(NativeResourceManager* manager, const char* name) {
  std::unique_ptr<RawFile, decltype(&OH_ResourceManager_CloseRawFile)> file(
    OH_ResourceManager_OpenRawFile(manager, name), OH_ResourceManager_CloseRawFile);
  if (!file) throw std::runtime_error(std::string("Community model asset unavailable: ") + name);
  const long size = OH_ResourceManager_GetRawFileSize(file.get());
  if (size <= 0) throw std::runtime_error("Community model asset is empty");
  std::vector<uint8_t> bytes(static_cast<size_t>(size));
  size_t offset = 0;
  while (offset < bytes.size()) {
    const size_t remaining = bytes.size() - offset;
    const int read = OH_ResourceManager_ReadRawFile(file.get(), bytes.data() + offset,
      std::min(remaining, static_cast<size_t>(std::numeric_limits<int>::max())));
    if (read <= 0 || static_cast<size_t>(read) > remaining) {
      throw std::runtime_error("Community model asset read failed");
    }
    offset += static_cast<size_t>(read);
  }
  return bytes;
}

#endif

class Model {
 public:
  Model(const std::vector<uint8_t>& segmentation, const std::vector<uint8_t>& encoder,
        const std::vector<uint8_t>& pooling,
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
    pooling_ = Ort::Session(env_, pooling.data(), pooling.size(), options);
    // XNNPACK owns the four compute workers. Keep the ORT fallback serial so
    // a second pool cannot compete with them between convolution operators.
    options.AppendExecutionProvider("XNNPACK", {{"intra_op_num_threads", "4"}});
    encoder_ = Ort::Session(env_, encoder.data(), encoder.size(), options);
    Ort::AllocatorWithDefaultOptions allocator;
    input_name_ = segmentation_.GetInputNameAllocated(0, allocator).get();
    output_name_ = segmentation_.GetOutputNameAllocated(0, allocator).get();
  }

  Window Process(std::vector<float>& pcm) {
    if (pcm.size() != 160000) throw std::runtime_error("Community requires a 10 second window");
    std::lock_guard<std::mutex> lock(inference_mutex_);
    TraceCommunityMemory("window-start");
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
    TraceCommunityMemory("segmentation");
    result.segmentation_ms = Milliseconds(start);
    start = Clock::now();
    auto features = community::Fbank(pcm, constants_);
    TraceCommunityMemory("features");
    result.feature_ms = Milliseconds(start);
    std::array<int64_t, 3> feature_shape{1, 998, 80}, mask_shape{1, 3, 589};
    std::array<int64_t, 3> encoded_shape{1, 2560, 125};
    auto feature_tensor = Ort::Value::CreateTensor<float>(memory, features.data(), features.size(), feature_shape.data(), 3);
    const char* encoder_inputs[] = {"fbank"};
    const char* encoder_outputs[] = {"/resnet/pool/Reshape_output_0"};
    start = Clock::now();
    // The split graphs retain the pinned model's weights. Encoded features
    // belong to this Process call and outlive all of its synchronous pooling
    // calls; they are never retained across windows, generations or sessions.
    Ort::RunOptions encoder_run;
    encoder_run.AddConfigEntry("memory.enable_memory_arena_shrinkage", "cpu:0");
    auto encoded = encoder_.Run(encoder_run, encoder_inputs, &feature_tensor, 1, encoder_outputs, 1);
    if (encoded[0].GetTensorTypeAndShapeInfo().GetElementCount() != 2560 * 125) {
      throw std::runtime_error("invalid Community encoder output");
    }
    TraceCommunityMemory("encoder");
    auto* encoded_values = encoded[0].GetTensorMutableData<float>();
    std::vector<Ort::Value> tensors;
    tensors.push_back(Ort::Value::CreateTensor<float>(memory, encoded_values, 2560 * 125, encoded_shape.data(), 3));
    tensors.push_back(Ort::Value::CreateTensor<float>(memory, masks.data(), masks.size(), mask_shape.data(), 3));
    const char* names[] = {"/resnet/pool/Reshape_output_0", "masks"};
    const char* outputs[] = {"embeddings"};
    auto embeddings = pooling_.Run(Ort::RunOptions{nullptr}, names, tensors.data(), 2, outputs, 1);
    if (embeddings[0].GetTensorTypeAndShapeInfo().GetElementCount() != 3 * 256) {
      throw std::runtime_error("invalid Community embedding output");
    }
    const auto* values = embeddings[0].GetTensorData<float>();
    result.embeddings.assign(values, values + 3 * 256);
    TraceCommunityMemory("pooling");
    // Keep the full-window vectors above for compatibility, and also export
    // one embedding per disconnected clean run. Overlap runs are exported as
    // non-trainable sentinels so they cannot fall back to a mixed identity.
    for (int channel = 0; channel < 3; ++channel) {
      const int base = channel * 589;
      int begin = -1;
      int kind = -1; // 1 = clean, 0 = overlap/blocked, -1 = inactive.
      for (int frame = 0; frame <= 589; ++frame) {
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
              auto run_output = pooling_.Run(Ort::RunOptions{nullptr}, names, run_tensors.data(), 2, outputs, 1);
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
    TraceCommunityMemory("run-pooling");
    result.embedding_ms = Milliseconds(start);
    return result;
  }

  std::string Cluster(const std::vector<float>& segments, const std::vector<float>& embeddings,
                      const std::vector<float>& run_embeddings, const std::vector<float>& run_ranges,
                      int max_speakers, const std::vector<double>& starts, double begin_sample,
                      const std::vector<float>& run_rms = {}) const {
    if (segments.empty() || segments.size() % (589 * 3) || max_speakers < 1 || max_speakers > 4) {
      throw std::runtime_error("invalid Community clustering input");
    }
    int windows = segments.size() / (589 * 3);
    std::vector<int32_t> native_ranges;
    native_ranges.reserve(run_ranges.size());
    for (float value : run_ranges) {
      if (!std::isfinite(value) || value != std::floor(value)) {
        throw std::runtime_error("invalid Community run range");
      }
      native_ranges.push_back(static_cast<int32_t>(value));
    }
    auto result = community::Cluster(segments, embeddings, windows, plda_, max_speakers,
                                     run_embeddings, native_ranges, run_rms);
    auto turns = community::Reconstruct(segments, result.hard, starts, begin_sample, max_speakers,
                                        result.frame_hard);
    std::ostringstream json;
    json << std::setprecision(17) << "{\"speakerCount\":" << result.centroids.size();
    auto ints = [&](const char* key, const std::vector<int>& values) {
      json << ",\"" << key << "\":[";
      for (size_t i = 0; i < values.size(); ++i) { if (i) json << ','; json << values[i]; }
      json << ']';
    };
    ints("hard", result.hard);
    ints("frameHard", result.frame_hard);
    ints("trainingIndices", result.trainingIndices);
    ints("trainingRunIndices", result.trainingRunIndices);
    ints("ahc", result.ahc);
    ints("retainedClusters", result.retainedClusters);
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
    json << ",\"capacityRms\":[";
    for (size_t i = 0; i < result.capacityRms.size(); ++i) { if (i) json << ','; json << result.capacityRms[i]; }
    json << ']';
    json << ",\"usedKMeans\":" << (result.usedKMeans ? "true" : "false")
         << ",\"usedAhcFallback\":" << (result.usedAhcFallback ? "true" : "false")
         << ",\"shortRunTrainingCount\":" << result.shortRunTrainingCount;
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
  Ort::Session segmentation_{nullptr}, encoder_{nullptr}, pooling_{nullptr};
  std::string input_name_, output_name_;
  std::vector<float> constants_;
  community::Plda plda_;
  std::mutex inference_mutex_;
};

#ifndef __ANDROID__
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
  // Keep the resource provider alive across the native worker. Unlike ArkTS
  // model arrays, these bytes are released with Work rather than by later GC.
  napi_env resource_env = nullptr;
  napi_ref resource_ref = nullptr;
  std::unique_ptr<NativeResourceManager, decltype(&OH_ResourceManager_ReleaseNativeResourceManager)>
    resource_manager{nullptr, OH_ResourceManager_ReleaseNativeResourceManager};
  std::array<std::vector<uint8_t>, 5> assets;
  std::vector<float> pcm, segments, embeddings, run_embeddings;
  std::vector<float> run_ranges, run_rms;
  std::vector<double> window_starts;
  double begin_sample = 0;
  Window window;
  int max_speakers = 4;
  std::string result, error;
  ~Work() {
    resource_manager.reset();
    if (resource_ref) napi_delete_reference(resource_env, resource_ref);
  }
};
void Execute(napi_env, void* data) {
  auto& task = *static_cast<Work*>(data);
  try {
    if (task.operation == Operation::Load) {
      if (task.resource_manager) {
        constexpr const char* names[] = {
          "amphion-dingqiao/pyannote-segmentation-3.0.onnx",
          "amphion-dingqiao/community-wespeaker-encoder.fp32.onnx",
          "amphion-dingqiao/community-wespeaker-pool.fp32.onnx",
          "amphion-dingqiao/community-feature.f32", "amphion-dingqiao/community-plda.f64"
        };
        for (size_t i = 0; i < task.assets.size(); ++i) {
          task.assets[i] = ReadCommunityAsset(task.resource_manager.get(), names[i]);
        }
      }
      task.model = std::make_shared<Model>(task.assets[0], task.assets[1], task.assets[2], task.assets[3], task.assets[4]);
    } else if (task.operation == Operation::Process) task.window = task.model->Process(task.pcm);
    else task.result = task.model->Cluster(task.segments, task.embeddings, task.run_embeddings,
                                           task.run_ranges, task.max_speakers, task.window_starts,
                                           task.begin_sample, task.run_rms);
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
      FloatProperty(env, value, "runEmbeddings", task->window.run_embeddings);
      FloatProperty(env, value, "runRanges", task->window.run_ranges);
      FloatProperty(env, value, "runRms", task->window.run_rms);
      NumberProperty(env, value, "segmentationMs", task->window.segmentation_ms);
      NumberProperty(env, value, "featureMs", task->window.feature_ms);
      NumberProperty(env, value, "embeddingMs", task->window.embedding_ms);
    } else napi_create_string_utf8(env, task->result.c_str(), task->result.size(), &value);
    napi_resolve_deferred(env, task->deferred, value);
  }
  napi_delete_async_work(env, task->work);
  task.reset();
  TraceCommunityMemory("async-work-freed");
}
napi_value Queue(napi_env env, napi_callback_info info, Operation operation, bool from_resources = false) {
  size_t count = 9;
  napi_value args[9] = {};
  napi_get_cb_info(env, info, &count, args, nullptr, nullptr);
  try {
    const bool legacyCluster = operation == Operation::Cluster && count == 6;
    const bool clusterLevels = operation == Operation::Cluster && count == 9;
    if (count != (from_resources ? 1u : operation == Operation::Process ? 2u : operation == Operation::Cluster ? (legacyCluster ? 6u : clusterLevels ? 9u : 8u) : 5u)) {
      throw std::runtime_error("invalid Community arguments");
    }
    auto task = std::make_unique<Work>();
    task->operation = operation;
    if (operation == Operation::Load) {
      if (from_resources) {
        task->resource_manager.reset(OH_ResourceManager_InitNativeResourceManager(env, args[0]));
        if (!task->resource_manager) throw std::runtime_error("invalid Community resource manager");
        task->resource_env = env;
        if (napi_create_reference(env, args[0], 1, &task->resource_ref) != napi_ok) {
          throw std::runtime_error("Community resource reference failed");
        }
      } else {
        for (size_t i = 0; i < task->assets.size(); ++i) task->assets[i] = CopyArray<uint8_t>(env, args[i], napi_uint8_array);
      }
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
        size_t offset = 0;
        if (!legacyCluster) {
          task->run_embeddings = CopyArray<float>(env, args[3], napi_float32_array);
          task->run_ranges = CopyArray<float>(env, args[4], napi_float32_array);
          offset = 2;
          if (clusterLevels) task->run_rms = CopyArray<float>(env, args[8], napi_float32_array);
        }
        if (napi_get_value_int32(env, args[3 + offset], &task->max_speakers) != napi_ok) throw std::runtime_error("invalid speaker cap");
        task->window_starts = CopyArray<double>(env, args[4 + offset], napi_float64_array);
        if (napi_get_value_double(env, args[5 + offset], &task->begin_sample) != napi_ok) throw std::runtime_error("invalid reconstruction boundary");
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
napi_value LoadResources(napi_env env, napi_callback_info info) { return Queue(env, info, Operation::Load, true); }
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
    {"loadCommunityDiarizationResources", nullptr, LoadResources, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"processCommunityDiarization", nullptr, Process, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"clusterCommunityDiarization", nullptr, Cluster, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"closeCommunityDiarization", nullptr, Close, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(methods) / sizeof(methods[0]), methods);
}

#else
} // namespace
#include "community_diarization_jni.inc"
#endif
