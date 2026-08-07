#include "target_speaker_enhancer.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <future>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

#include <rawfile/raw_file_manager.h>

#include "onnxruntime_cxx_api.h"
#include "sherpa-onnx/c-api/c-api.h"

namespace {

constexpr int32_t kSampleRate = 16000;
constexpr int64_t kChunkSamples = 32000;
constexpr int64_t kOutputStreams = 2;
constexpr float kDefaultThreshold = 0.25F;
constexpr int32_t kSeparatorThreads = 4;
constexpr size_t kMaxCachedExtractorPairs = 1;

void ThrowJsError(napi_env env, const std::string& message) {
  napi_throw_error(env, nullptr, message.c_str());
}

std::string GetString(napi_env env, napi_value value, const char* name) {
  size_t length = 0;
  if (napi_get_value_string_utf8(env, value, nullptr, 0, &length) != napi_ok) {
    throw std::runtime_error(std::string(name) + " must be a string");
  }
  std::string result(length, '\0');
  size_t written = 0;
  if (napi_get_value_string_utf8(env, value, result.data(), length + 1, &written) != napi_ok) {
    throw std::runtime_error(std::string("failed to read ") + name);
  }
  result.resize(written);
  return result;
}

template <typename T>
std::vector<T> CopyTypedArray(napi_env env, napi_value value, napi_typedarray_type expected,
                              const char* name) {
  napi_typedarray_type actual;
  size_t length = 0;
  void* data = nullptr;
  napi_value array_buffer = nullptr;
  size_t byte_offset = 0;
  if (napi_get_typedarray_info(env, value, &actual, &length, &data, &array_buffer,
                               &byte_offset) != napi_ok || actual != expected) {
    throw std::runtime_error(std::string(name) + " has an invalid typed-array type");
  }
  napi_value byte_length_value = nullptr;
  uint32_t view_bytes = 0;
  if (napi_get_named_property(env, value, "byteLength", &byte_length_value) != napi_ok ||
      napi_get_value_uint32(env, byte_length_value, &view_bytes) != napi_ok ||
      view_bytes % sizeof(T) != 0) {
    throw std::runtime_error(std::string(name) + " has an invalid byteLength");
  }
  void* buffer_data = nullptr;
  size_t buffer_bytes = 0;
  if (napi_get_arraybuffer_info(env, array_buffer, &buffer_data, &buffer_bytes) != napi_ok ||
      byte_offset > buffer_bytes || view_bytes > buffer_bytes - byte_offset) {
    throw std::runtime_error(std::string(name) + " exceeds its backing buffer");
  }
  const size_t element_count = view_bytes / sizeof(T);
  // Standard Node-API reports elements, while affected Harmony releases report bytes. The JS
  // view's own byteLength remains authoritative, including for a subarray of a larger buffer.
  if (length != element_count && length != view_bytes) {
    throw std::runtime_error(std::string(name) + " has an inconsistent native length");
  }
  const T* begin = static_cast<const T*>(data);
  return std::vector<T>(begin, begin + element_count);
}

float RootMeanSquare(const std::vector<float>& samples) {
  double energy = 0.0;
  for (float sample : samples) energy += static_cast<double>(sample) * sample;
  return samples.empty() ? 0.0F : static_cast<float>(std::sqrt(energy / samples.size()));
}

float CosineSimilarity(const float* embedding, const std::vector<float>& target) {
  double dot = 0.0;
  double left = 0.0;
  double right = 0.0;
  for (size_t i = 0; i < target.size(); ++i) {
    dot += static_cast<double>(embedding[i]) * target[i];
    left += static_cast<double>(embedding[i]) * embedding[i];
    right += static_cast<double>(target[i]) * target[i];
  }
  if (left <= 0.0 || right <= 0.0) return -1.0F;
  return static_cast<float>(dot / std::sqrt(left * right));
}

struct EnhancementResult {
  std::vector<float> samples;
  std::vector<float> similarities;
  int32_t selected_stream = -1;
  int64_t duration_ms = 0;
};

class TargetSpeakerSeparator {
 public:
  explicit TargetSpeakerSeparator(std::vector<uint8_t> model_bytes)
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-target-speaker"),
        model_bytes_(std::move(model_bytes)) {
    if (model_bytes_.empty()) throw std::runtime_error("separator model is empty");

    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetIntraOpNumThreads(kSeparatorThreads);
    options.SetInterOpNumThreads(1);
    options.DisableCpuMemArena();
    options.DisableMemPattern();
    // The graph was fully optimized for ARM when converted to ORT format. Keeping the rawfile
    // bytes alive lets ORT use FlatBuffer initializers directly and avoids both graph optimization
    // and a second ~20 MB model copy during cold load.
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_DISABLE_ALL);
    options.AddConfigEntry("session.load_model_format", "ORT");
    options.AddConfigEntry("session.use_ort_model_bytes_directly", "1");
    options.AddConfigEntry("session.use_ort_model_bytes_for_initializers", "1");
    session_ = Ort::Session(env_, model_bytes_.data(), model_bytes_.size(), options);
    if (session_.GetInputCount() != 1 || session_.GetOutputCount() != 1) {
      throw std::runtime_error("separator model must have exactly one input and one output");
    }
    Ort::AllocatorWithDefaultOptions allocator;
    input_name_ = session_.GetInputNameAllocated(0, allocator).get();
    output_name_ = session_.GetOutputNameAllocated(0, allocator).get();
  }

  std::vector<float> Separate(const std::vector<float>& input) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (input.size() != kChunkSamples) {
      throw std::runtime_error("enhancement input must contain 32000 samples");
    }
    std::array<int64_t, 2> input_shape{1, kChunkSamples};
    Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory, const_cast<float*>(input.data()), input.size(), input_shape.data(), input_shape.size());
    const char* input_names[] = {input_name_.c_str()};
    const char* output_names[] = {output_name_.c_str()};
    std::vector<Ort::Value> outputs = session_.Run(
        Ort::RunOptions{nullptr}, input_names, &input_tensor, 1, output_names, 1);
    if (outputs.size() != 1 || !outputs[0].IsTensor()) {
      throw std::runtime_error("separator returned an invalid output");
    }
    const size_t output_samples = outputs[0].GetTensorTypeAndShapeInfo().GetElementCount();
    if (output_samples != static_cast<size_t>(kOutputStreams * kChunkSamples)) {
      throw std::runtime_error("separator output must contain two 32000-sample streams");
    }
    const float* separated = outputs[0].GetTensorData<float>();
    return std::vector<float>(separated, separated + output_samples);
  }

 private:
  Ort::Env env_;
  std::vector<uint8_t> model_bytes_;
  Ort::Session session_{nullptr};
  std::string input_name_;
  std::string output_name_;
  std::mutex mutex_;
};

class SpeakerExtractorPair {
 public:
  SpeakerExtractorPair(const std::string& speaker_model,
                       NativeResourceManager* resource_manager,
                       size_t target_dimension)
      : speaker_model_(speaker_model), target_dimension_(target_dimension) {
    SherpaOnnxSpeakerEmbeddingExtractorConfig config{};
    config.model = speaker_model_.c_str();
    config.num_threads = 1;
    config.debug = 0;
    config.provider = "cpu";
    for (auto& extractor : extractors_) {
      extractor = SherpaOnnxCreateSpeakerEmbeddingExtractorOHOS(&config, resource_manager);
      if (extractor == nullptr) {
        Destroy();
        throw std::runtime_error("failed to create speaker embedding extractor");
      }
      const int32_t dimension = SherpaOnnxSpeakerEmbeddingExtractorDim(extractor);
      if (dimension <= 0 || static_cast<size_t>(dimension) != target_dimension_) {
        Destroy();
        throw std::runtime_error(
            "target embedding dimension=" + std::to_string(target_dimension_) +
            " does not match speaker model dimension=" + std::to_string(dimension));
      }
    }
  }

  ~SpeakerExtractorPair() { Destroy(); }

  const SherpaOnnxSpeakerEmbeddingExtractor* operator[](size_t index) const {
    return extractors_[index];
  }

  bool Matches(const std::string& speaker_model, size_t target_dimension) const {
    return speaker_model_ == speaker_model && target_dimension_ == target_dimension;
  }

 private:
  void Destroy() {
    for (const auto* extractor : extractors_) {
      if (extractor != nullptr) SherpaOnnxDestroySpeakerEmbeddingExtractor(extractor);
    }
    extractors_.fill(nullptr);
  }

  std::string speaker_model_;
  size_t target_dimension_;
  std::array<const SherpaOnnxSpeakerEmbeddingExtractor*, kOutputStreams> extractors_{};
};

// Owns every heavyweight object in the enhancement L2 lifecycle. A completed session returns its
// scorer pair here, so the next session does not synchronously reload two copies of ERes2Net before
// onStart. Active/cancelled async work retains the model and its checked-out pair until it exits.
class TargetSpeakerEnhancementModel {
 public:
  explicit TargetSpeakerEnhancementModel(std::vector<uint8_t> separator_model)
      : separator_(std::move(separator_model)) {}

  std::vector<float> Separate(const std::vector<float>& input) {
    return separator_.Separate(input);
  }

  std::unique_ptr<SpeakerExtractorPair> AcquireExtractors(
      const std::string& speaker_model,
      NativeResourceManager* resource_manager,
      size_t target_dimension) {
    {
      std::lock_guard<std::mutex> lock(extractor_pool_mutex_);
      for (auto it = available_extractors_.begin(); it != available_extractors_.end(); ++it) {
        if ((*it)->Matches(speaker_model, target_dimension)) {
          auto pair = std::move(*it);
          available_extractors_.erase(it);
          return pair;
        }
      }
    }
    // Model construction is intentionally outside the pool lock. Overlapping sessions may each
    // create a pair instead of blocking one another; only one returned pair is retained for reuse.
    return std::make_unique<SpeakerExtractorPair>(
        speaker_model, resource_manager, target_dimension);
  }

  void ReleaseExtractors(std::unique_ptr<SpeakerExtractorPair> extractors) {
    if (extractors == nullptr) return;
    std::lock_guard<std::mutex> lock(extractor_pool_mutex_);
    if (available_extractors_.size() < kMaxCachedExtractorPairs) {
      available_extractors_.push_back(std::move(extractors));
    }
  }

 private:
  TargetSpeakerSeparator separator_;
  std::mutex extractor_pool_mutex_;
  std::vector<std::unique_ptr<SpeakerExtractorPair>> available_extractors_;
};

std::mutex g_enhancement_model_mutex;
std::shared_ptr<TargetSpeakerEnhancementModel> g_enhancement_model;
uint64_t g_enhancement_model_generation = 0;

std::shared_ptr<TargetSpeakerEnhancementModel> GetLoadedEnhancementModel() {
  std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
  if (g_enhancement_model == nullptr) {
    throw std::runtime_error("target speaker enhancement model is not loaded");
  }
  return g_enhancement_model;
}

class TargetSpeakerEnhancer {
 public:
  TargetSpeakerEnhancer(std::shared_ptr<TargetSpeakerEnhancementModel> model,
                        const std::string& speaker_model,
                        NativeResourceManager* resource_manager,
                        std::vector<float> target_embedding,
                        float threshold)
      : model_(std::move(model)),
        target_embedding_(std::move(target_embedding)),
        threshold_(threshold) {
    if (model_ == nullptr) throw std::runtime_error("enhancement model is not loaded");
    if (target_embedding_.empty()) throw std::runtime_error("target embedding is empty");
    extractors_ = model_->AcquireExtractors(
        speaker_model, resource_manager, target_embedding_.size());
  }

  ~TargetSpeakerEnhancer() { model_->ReleaseExtractors(std::move(extractors_)); }

  EnhancementResult Process(const std::vector<float>& input) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto started = std::chrono::steady_clock::now();
    std::vector<float> separated = model_->Separate(input);
    const float input_rms = RootMeanSquare(input);

    EnhancementResult result;
    result.samples.assign(kChunkSamples, 0.0F);
    result.similarities.resize(kOutputStreams, -1.0F);
    std::vector<std::vector<float>> candidates(kOutputStreams);
    for (int32_t stream_index = 0; stream_index < kOutputStreams; ++stream_index) {
      const float* source = separated.data() + stream_index * kChunkSamples;
      candidates[stream_index].assign(source, source + kChunkSamples);
      const float candidate_rms = RootMeanSquare(candidates[stream_index]);
      const float scale = candidate_rms > 1.0e-6F ? input_rms / candidate_rms : 0.0F;
      for (float& sample : candidates[stream_index]) {
        sample = std::clamp(sample * scale, -1.0F, 1.0F);
      }
    }
    auto first_score = std::async(std::launch::async, [this, &candidates]() {
      return Score(candidates[0], (*extractors_)[0]);
    });
    result.similarities[1] = Score(candidates[1], (*extractors_)[1]);
    result.similarities[0] = first_score.get();
    const int32_t best = result.similarities[1] > result.similarities[0] ? 1 : 0;
    if (result.similarities[best] >= threshold_) {
      result.selected_stream = best;
      result.samples = std::move(candidates[best]);
    }
    result.duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started).count();
    return result;
  }

 private:
  float Score(const std::vector<float>& samples,
              const SherpaOnnxSpeakerEmbeddingExtractor* extractor) const {
    const SherpaOnnxOnlineStream* stream =
        SherpaOnnxSpeakerEmbeddingExtractorCreateStream(extractor);
    if (stream == nullptr) throw std::runtime_error("failed to create speaker embedding stream");
    struct StreamGuard {
      const SherpaOnnxOnlineStream* value;
      ~StreamGuard() { SherpaOnnxDestroyOnlineStream(value); }
    } stream_guard{stream};
    SherpaOnnxOnlineStreamAcceptWaveform(stream, kSampleRate, samples.data(), samples.size());
    SherpaOnnxOnlineStreamInputFinished(stream);
    if (!SherpaOnnxSpeakerEmbeddingExtractorIsReady(extractor, stream)) return -1.0F;
    const float* embedding =
        SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding(extractor, stream);
    if (embedding == nullptr) throw std::runtime_error("speaker embedding computation failed");
    struct EmbeddingGuard {
      const float* value;
      ~EmbeddingGuard() { SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding(value); }
    } embedding_guard{embedding};
    return CosineSimilarity(embedding, target_embedding_);
  }

  std::shared_ptr<TargetSpeakerEnhancementModel> model_;
  std::unique_ptr<SpeakerExtractorPair> extractors_;
  std::vector<float> target_embedding_;
  float threshold_;
  std::mutex mutex_;
};

struct EnhancerHolder {
  std::shared_ptr<TargetSpeakerEnhancer> enhancer;
};

void FinalizeEnhancer(napi_env, void* data, void*) {
  delete static_cast<EnhancerHolder*>(data);
}

EnhancerHolder* GetHolder(napi_env env, napi_value value) {
  void* data = nullptr;
  if (napi_get_value_external(env, value, &data) != napi_ok || data == nullptr) {
    throw std::runtime_error("invalid target speaker enhancer handle");
  }
  return static_cast<EnhancerHolder*>(data);
}

napi_value LoadTargetSpeakerEnhancementModel(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 1;
    napi_value args[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    if (argc < 1) {
      throw std::runtime_error("loadTargetSpeakerEnhancementModel expects model bytes");
    }
    std::vector<uint8_t> model =
        CopyTypedArray<uint8_t>(env, args[0], napi_uint8_array, "separatorModel");
    std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
    if (g_enhancement_model == nullptr) {
      g_enhancement_model =
          std::make_shared<TargetSpeakerEnhancementModel>(std::move(model));
    }
    napi_value value = nullptr;
    napi_get_undefined(env, &value);
    return value;
  } catch (const std::exception& error) {
    ThrowJsError(env, error.what());
    return nullptr;
  }
}

napi_value IsTargetSpeakerEnhancementModelLoaded(napi_env env, napi_callback_info) {
  std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
  napi_value value = nullptr;
  napi_get_boolean(env, g_enhancement_model != nullptr, &value);
  return value;
}

struct PreloadContext {
  ~PreloadContext() {
    if (resource_manager != nullptr) {
      OH_ResourceManager_ReleaseNativeResourceManager(resource_manager);
    }
    if (resource_manager_ref != nullptr && env != nullptr) {
      napi_delete_reference(env, resource_manager_ref);
    }
    if (work != nullptr && env != nullptr) napi_delete_async_work(env, work);
  }

  napi_env env = nullptr;
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
  napi_ref resource_manager_ref = nullptr;
  NativeResourceManager* resource_manager = nullptr;
  std::vector<uint8_t> separator_model;
  std::string speaker_model;
  size_t target_dimension = 0;
  uint64_t generation = 0;
  std::string error;
};

void ExecutePreload(napi_env, void* data) {
  auto* context = static_cast<PreloadContext*>(data);
  try {
    std::shared_ptr<TargetSpeakerEnhancementModel> model;
    {
      std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
      if (context->generation != g_enhancement_model_generation) {
        throw std::runtime_error("target speaker enhancement preload was invalidated");
      }
      model = g_enhancement_model;
    }
    if (model == nullptr) {
      auto candidate = std::make_shared<TargetSpeakerEnhancementModel>(
          std::move(context->separator_model));
      std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
      if (context->generation != g_enhancement_model_generation) {
        throw std::runtime_error("target speaker enhancement preload was invalidated");
      }
      if (g_enhancement_model == nullptr) g_enhancement_model = std::move(candidate);
      model = g_enhancement_model;
    }
    auto extractors = model->AcquireExtractors(
        context->speaker_model, context->resource_manager, context->target_dimension);
    model->ReleaseExtractors(std::move(extractors));
    std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
    if (context->generation != g_enhancement_model_generation) {
      throw std::runtime_error("target speaker enhancement preload was invalidated");
    }
  } catch (const std::exception& error) {
    context->error = error.what();
  }
}

void CompletePreload(napi_env env, napi_status, void* data) {
  std::unique_ptr<PreloadContext> context(static_cast<PreloadContext*>(data));
  bool generation_current = false;
  {
    std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
    generation_current = context->generation == g_enhancement_model_generation;
  }
  if (context->resource_manager != nullptr) {
    OH_ResourceManager_ReleaseNativeResourceManager(context->resource_manager);
    context->resource_manager = nullptr;
  }
  if (context->resource_manager_ref != nullptr) {
    napi_delete_reference(env, context->resource_manager_ref);
    context->resource_manager_ref = nullptr;
  }
  if (!generation_current && context->error.empty()) {
    context->error = "target speaker enhancement preload was invalidated";
  }
  if (context->error.empty()) {
    napi_value value = nullptr;
    napi_get_undefined(env, &value);
    napi_resolve_deferred(env, context->deferred, value);
  } else {
    napi_value message = nullptr;
    napi_create_string_utf8(env, context->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_reject_deferred(env, context->deferred, message);
  }
  napi_delete_async_work(env, context->work);
  context->work = nullptr;
}

napi_value PreloadTargetSpeakerEnhancementModelAsync(napi_env env,
                                                      napi_callback_info info) {
  try {
    size_t argc = 4;
    napi_value args[4] = {nullptr, nullptr, nullptr, nullptr};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    if (argc < 4) {
      throw std::runtime_error(
          "preloadTargetSpeakerEnhancementModelAsync expects model bytes, speaker model, "
          "resource manager, and target dimension");
    }
    auto context = std::make_unique<PreloadContext>();
    context->env = env;
    context->separator_model =
        CopyTypedArray<uint8_t>(env, args[0], napi_uint8_array, "separatorModel");
    context->speaker_model = GetString(env, args[1], "speakerModel");
    uint32_t target_dimension = 0;
    if (napi_get_value_uint32(env, args[3], &target_dimension) != napi_ok ||
        target_dimension == 0) {
      throw std::runtime_error("targetDimension must be a positive integer");
    }
    context->target_dimension = target_dimension;
    context->resource_manager =
        OH_ResourceManager_InitNativeResourceManager(env, args[2]);
    if (context->resource_manager == nullptr ||
        napi_create_reference(env, args[2], 1, &context->resource_manager_ref) != napi_ok) {
      if (context->resource_manager != nullptr) {
        OH_ResourceManager_ReleaseNativeResourceManager(context->resource_manager);
        context->resource_manager = nullptr;
      }
      throw std::runtime_error("failed to retain resourceManager for enhancement preload");
    }
    {
      std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
      context->generation = g_enhancement_model_generation;
    }
    napi_value promise = nullptr;
    if (napi_create_promise(env, &context->deferred, &promise) != napi_ok) {
      throw std::runtime_error("failed to create enhancement preload promise");
    }
    napi_value resource_name = nullptr;
    napi_create_string_utf8(env, "AmphionTargetSpeakerPreload", NAPI_AUTO_LENGTH,
                            &resource_name);
    if (napi_create_async_work(env, nullptr, resource_name, ExecutePreload, CompletePreload,
                               context.get(), &context->work) != napi_ok ||
        napi_queue_async_work(env, context->work) != napi_ok) {
      throw std::runtime_error("failed to queue enhancement preload");
    }
    context.release();
    return promise;
  } catch (const std::exception& error) {
    ThrowJsError(env, error.what());
    return nullptr;
  }
}

napi_value UnloadTargetSpeakerEnhancementModel(napi_env env, napi_callback_info) {
  {
    std::lock_guard<std::mutex> lock(g_enhancement_model_mutex);
    // Active per-session enhancers retain a shared reference until their normal close/cancel path.
    // New sessions after unload must load the formal asset again, matching the core model pool.
    g_enhancement_model.reset();
    ++g_enhancement_model_generation;
  }
  napi_value value = nullptr;
  napi_get_undefined(env, &value);
  return value;
}

napi_value CreateEnhancer(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 4;
    napi_value args[4] = {nullptr, nullptr, nullptr, nullptr};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    if (argc < 3) {
      throw std::runtime_error(
          "createTargetSpeakerEnhancer expects speakerModel, resourceManager, targetEmbedding");
    }
    const std::string speaker_model = GetString(env, args[0], "speakerModel");
    NativeResourceManager* resource_manager =
        OH_ResourceManager_InitNativeResourceManager(env, args[1]);
    if (resource_manager == nullptr) throw std::runtime_error("invalid resourceManager");
    struct ResourceManagerGuard {
      NativeResourceManager* value;
      ~ResourceManagerGuard() { OH_ResourceManager_ReleaseNativeResourceManager(value); }
    } manager_guard{resource_manager};
    std::vector<float> target =
        CopyTypedArray<float>(env, args[2], napi_float32_array, "targetEmbedding");
    double threshold = kDefaultThreshold;
    if (argc >= 4 && args[3] != nullptr &&
        napi_get_value_double(env, args[3], &threshold) != napi_ok) {
      throw std::runtime_error("threshold must be a number");
    }
    auto holder = std::make_unique<EnhancerHolder>();
    holder->enhancer = std::make_shared<TargetSpeakerEnhancer>(
        GetLoadedEnhancementModel(), speaker_model, resource_manager, std::move(target),
        static_cast<float>(threshold));
    napi_value external = nullptr;
    napi_create_external(env, holder.get(), FinalizeEnhancer, nullptr, &external);
    holder.release();
    return external;
  } catch (const std::exception& error) {
    ThrowJsError(env, error.what());
    return nullptr;
  }
}

struct ProcessContext {
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
  std::shared_ptr<TargetSpeakerEnhancer> enhancer;
  std::vector<float> input;
  EnhancementResult result;
  std::string error;
};

void ExecuteProcess(napi_env, void* data) {
  auto* context = static_cast<ProcessContext*>(data);
  try {
    context->result = context->enhancer->Process(context->input);
  } catch (const std::exception& error) {
    context->error = error.what();
  }
}

void CompleteProcess(napi_env env, napi_status, void* data) {
  std::unique_ptr<ProcessContext> context(static_cast<ProcessContext*>(data));
  if (!context->error.empty()) {
    napi_value message = nullptr;
    napi_create_string_utf8(env, context->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_reject_deferred(env, context->deferred, message);
  } else {
    napi_value output = nullptr;
    napi_create_object(env, &output);
    void* sample_data = nullptr;
    napi_value sample_buffer = nullptr;
    napi_create_arraybuffer(env, context->result.samples.size() * sizeof(float),
                            &sample_data, &sample_buffer);
    std::memcpy(sample_data, context->result.samples.data(),
                context->result.samples.size() * sizeof(float));
    napi_value samples = nullptr;
    napi_create_typedarray(env, napi_float32_array, context->result.samples.size(),
                           sample_buffer, 0, &samples);
    napi_set_named_property(env, output, "samples", samples);

    void* similarity_data = nullptr;
    napi_value similarity_buffer = nullptr;
    napi_create_arraybuffer(env, context->result.similarities.size() * sizeof(float),
                            &similarity_data, &similarity_buffer);
    std::memcpy(similarity_data, context->result.similarities.data(),
                context->result.similarities.size() * sizeof(float));
    napi_value similarities = nullptr;
    napi_create_typedarray(env, napi_float32_array, context->result.similarities.size(),
                           similarity_buffer, 0, &similarities);
    napi_set_named_property(env, output, "speakerSimilarities", similarities);

    napi_value selected = nullptr;
    napi_create_int32(env, context->result.selected_stream, &selected);
    napi_set_named_property(env, output, "selectedStream", selected);
    napi_value duration = nullptr;
    napi_create_int64(env, context->result.duration_ms, &duration);
    napi_set_named_property(env, output, "durationMs", duration);
    napi_resolve_deferred(env, context->deferred, output);
  }
  napi_delete_async_work(env, context->work);
}

napi_value ProcessChunk(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 2;
    napi_value args[2] = {nullptr, nullptr};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    if (argc < 2) {
      throw std::runtime_error("processTargetSpeakerChunk expects handle and Float32Array");
    }
    EnhancerHolder* holder = GetHolder(env, args[0]);
    if (holder->enhancer == nullptr) throw std::runtime_error("target speaker enhancer is closed");
    auto context = std::make_unique<ProcessContext>();
    context->enhancer = holder->enhancer;
    context->input = CopyTypedArray<float>(env, args[1], napi_float32_array, "samples");
    napi_value promise = nullptr;
    napi_create_promise(env, &context->deferred, &promise);
    napi_value resource_name = nullptr;
    napi_create_string_utf8(env, "AmphionTargetSpeakerEnhancement", NAPI_AUTO_LENGTH,
                            &resource_name);
    napi_create_async_work(env, nullptr, resource_name, ExecuteProcess, CompleteProcess,
                           context.get(), &context->work);
    napi_queue_async_work(env, context->work);
    context.release();
    return promise;
  } catch (const std::exception& error) {
    ThrowJsError(env, error.what());
    return nullptr;
  }
}

napi_value CloseEnhancer(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 1;
    napi_value args[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    if (argc < 1) throw std::runtime_error("closeTargetSpeakerEnhancer expects handle");
    GetHolder(env, args[0])->enhancer.reset();
    napi_value value = nullptr;
    napi_get_undefined(env, &value);
    return value;
  } catch (const std::exception& error) {
    ThrowJsError(env, error.what());
    return nullptr;
  }
}

}  // namespace

void RegisterTargetSpeakerEnhancer(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"loadTargetSpeakerEnhancementModel", nullptr, LoadTargetSpeakerEnhancementModel,
       nullptr, nullptr, nullptr, napi_default, nullptr},
      {"isTargetSpeakerEnhancementModelLoaded", nullptr, IsTargetSpeakerEnhancementModelLoaded,
       nullptr, nullptr, nullptr, napi_default, nullptr},
      {"preloadTargetSpeakerEnhancementModelAsync", nullptr,
       PreloadTargetSpeakerEnhancementModelAsync, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"unloadTargetSpeakerEnhancementModel", nullptr, UnloadTargetSpeakerEnhancementModel,
       nullptr, nullptr, nullptr, napi_default, nullptr},
      {"createTargetSpeakerEnhancer", nullptr, CreateEnhancer, nullptr, nullptr, nullptr,
       napi_default, nullptr},
      {"processTargetSpeakerChunk", nullptr, ProcessChunk, nullptr, nullptr, nullptr,
       napi_default, nullptr},
      {"closeTargetSpeakerEnhancer", nullptr, CloseEnhancer, nullptr, nullptr, nullptr,
       napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
}
