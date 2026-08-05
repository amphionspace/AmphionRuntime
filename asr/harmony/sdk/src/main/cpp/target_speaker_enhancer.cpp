#include "target_speaker_enhancer.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
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

class TargetSpeakerEnhancer {
 public:
  TargetSpeakerEnhancer(const std::vector<uint8_t>& separator_model,
                        const std::string& speaker_model,
                        NativeResourceManager* resource_manager,
                        std::vector<float> target_embedding,
                        float threshold)
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-target-speaker"),
        target_embedding_(std::move(target_embedding)),
        threshold_(threshold) {
    if (separator_model.empty()) throw std::runtime_error("separator model is empty");
    if (target_embedding_.empty()) throw std::runtime_error("target embedding is empty");

    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetIntraOpNumThreads(4);
    options.SetInterOpNumThreads(1);
    options.DisableCpuMemArena();
    options.DisableMemPattern();
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    separator_ = Ort::Session(env_, separator_model.data(), separator_model.size(), options);
    if (separator_.GetInputCount() != 1 || separator_.GetOutputCount() != 1) {
      throw std::runtime_error("separator model must have exactly one input and one output");
    }
    Ort::AllocatorWithDefaultOptions allocator;
    input_name_ = separator_.GetInputNameAllocated(0, allocator).get();
    output_name_ = separator_.GetOutputNameAllocated(0, allocator).get();

    SherpaOnnxSpeakerEmbeddingExtractorConfig config{};
    config.model = speaker_model.c_str();
    config.num_threads = 1;
    config.debug = 0;
    config.provider = "cpu";
    const SherpaOnnxSpeakerEmbeddingExtractor* extractor =
        SherpaOnnxCreateSpeakerEmbeddingExtractorOHOS(&config, resource_manager);
    if (extractor == nullptr) throw std::runtime_error("failed to create speaker embedding extractor");
    const int32_t dimension = SherpaOnnxSpeakerEmbeddingExtractorDim(extractor);
    if (dimension <= 0 || static_cast<size_t>(dimension) != target_embedding_.size()) {
      SherpaOnnxDestroySpeakerEmbeddingExtractor(extractor);
      throw std::runtime_error(
          "target embedding dimension=" + std::to_string(target_embedding_.size()) +
          " does not match speaker model dimension=" + std::to_string(dimension));
    }
    extractor_ = extractor;
  }

  ~TargetSpeakerEnhancer() {
    if (extractor_ != nullptr) SherpaOnnxDestroySpeakerEmbeddingExtractor(extractor_);
  }

  EnhancementResult Process(const std::vector<float>& input) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (input.size() != kChunkSamples) {
      throw std::runtime_error("enhancement input must contain 32000 samples");
    }
    const auto started = std::chrono::steady_clock::now();
    std::array<int64_t, 2> input_shape{1, kChunkSamples};
    Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory, const_cast<float*>(input.data()), input.size(), input_shape.data(), input_shape.size());
    const char* input_names[] = {input_name_.c_str()};
    const char* output_names[] = {output_name_.c_str()};
    std::vector<Ort::Value> outputs = separator_.Run(
        Ort::RunOptions{nullptr}, input_names, &input_tensor, 1, output_names, 1);
    if (outputs.size() != 1 || !outputs[0].IsTensor()) {
      throw std::runtime_error("separator returned an invalid output");
    }
    const size_t output_samples = outputs[0].GetTensorTypeAndShapeInfo().GetElementCount();
    if (output_samples != static_cast<size_t>(kOutputStreams * kChunkSamples)) {
      throw std::runtime_error("separator output must contain two 32000-sample streams");
    }
    const float* separated = outputs[0].GetTensorData<float>();
    const float input_rms = RootMeanSquare(input);

    EnhancementResult result;
    result.samples.assign(kChunkSamples, 0.0F);
    result.similarities.resize(kOutputStreams, -1.0F);
    std::vector<std::vector<float>> candidates(kOutputStreams);
    for (int32_t stream_index = 0; stream_index < kOutputStreams; ++stream_index) {
      const float* source = separated + stream_index * kChunkSamples;
      candidates[stream_index].assign(source, source + kChunkSamples);
      const float candidate_rms = RootMeanSquare(candidates[stream_index]);
      const float scale = candidate_rms > 1.0e-6F ? input_rms / candidate_rms : 0.0F;
      for (float& sample : candidates[stream_index]) {
        sample = std::clamp(sample * scale, -1.0F, 1.0F);
      }
      result.similarities[stream_index] = Score(candidates[stream_index]);
    }
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
  float Score(const std::vector<float>& samples) const {
    const SherpaOnnxOnlineStream* stream =
        SherpaOnnxSpeakerEmbeddingExtractorCreateStream(extractor_);
    if (stream == nullptr) throw std::runtime_error("failed to create speaker embedding stream");
    struct StreamGuard {
      const SherpaOnnxOnlineStream* value;
      ~StreamGuard() { SherpaOnnxDestroyOnlineStream(value); }
    } stream_guard{stream};
    SherpaOnnxOnlineStreamAcceptWaveform(stream, kSampleRate, samples.data(), samples.size());
    SherpaOnnxOnlineStreamInputFinished(stream);
    if (!SherpaOnnxSpeakerEmbeddingExtractorIsReady(extractor_, stream)) return -1.0F;
    const float* embedding =
        SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding(extractor_, stream);
    if (embedding == nullptr) throw std::runtime_error("speaker embedding computation failed");
    struct EmbeddingGuard {
      const float* value;
      ~EmbeddingGuard() { SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding(value); }
    } embedding_guard{embedding};
    return CosineSimilarity(embedding, target_embedding_);
  }

  Ort::Env env_;
  Ort::Session separator_{nullptr};
  const SherpaOnnxSpeakerEmbeddingExtractor* extractor_ = nullptr;
  std::vector<float> target_embedding_;
  float threshold_;
  std::string input_name_;
  std::string output_name_;
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

napi_value CreateEnhancer(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 5;
    napi_value args[5] = {nullptr, nullptr, nullptr, nullptr, nullptr};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    if (argc < 4) {
      throw std::runtime_error(
          "createTargetSpeakerEnhancer expects separatorModel, speakerModel, resourceManager, targetEmbedding");
    }
    std::vector<uint8_t> separator =
        CopyTypedArray<uint8_t>(env, args[0], napi_uint8_array, "separatorModel");
    const std::string speaker_model = GetString(env, args[1], "speakerModel");
    NativeResourceManager* resource_manager =
        OH_ResourceManager_InitNativeResourceManager(env, args[2]);
    if (resource_manager == nullptr) throw std::runtime_error("invalid resourceManager");
    struct ResourceManagerGuard {
      NativeResourceManager* value;
      ~ResourceManagerGuard() { OH_ResourceManager_ReleaseNativeResourceManager(value); }
    } manager_guard{resource_manager};
    std::vector<float> target =
        CopyTypedArray<float>(env, args[3], napi_float32_array, "targetEmbedding");
    double threshold = kDefaultThreshold;
    if (argc >= 5 && args[4] != nullptr &&
        napi_get_value_double(env, args[4], &threshold) != napi_ok) {
      throw std::runtime_error("threshold must be a number");
    }
    auto holder = std::make_unique<EnhancerHolder>();
    holder->enhancer = std::make_shared<TargetSpeakerEnhancer>(
        separator, speaker_model, resource_manager, std::move(target), static_cast<float>(threshold));
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
      {"createTargetSpeakerEnhancer", nullptr, CreateEnhancer, nullptr, nullptr, nullptr,
       napi_default, nullptr},
      {"processTargetSpeakerChunk", nullptr, ProcessChunk, nullptr, nullptr, nullptr,
       napi_default, nullptr},
      {"closeTargetSpeakerEnhancer", nullptr, CloseEnhancer, nullptr, nullptr, nullptr,
       napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
}
