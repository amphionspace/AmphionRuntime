#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <functional>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <random>
#include <signal.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <sys/wait.h>
#include <thread>
#include <utility>
#include <vector>
#include <unistd.h>

#include <hilog/log.h>
#include <node_api.h>

#include "lits_tn_inprocess.hpp"
#include "third_party/onnxruntime/include/onnxruntime_cxx_api.h"

namespace {

constexpr const char* kHandleProperty = "__nativeHandle";
constexpr const char* kHiddenInputNames[] = {"token_ids", "token_lengths", "speaker_id", "length_scale"};
constexpr const char* kHiddenOutputNames[] = {"mu_y", "y_mask", "mel_length", "speaker_embedding"};
constexpr const char* kDecoderInputNames[] = {"mu_y", "y_mask", "speaker_embedding"};
constexpr const char* kDecoderOutputNames[] = {"mel"};
constexpr const char* kConditionInputNames[] = {"mu_y", "y_mask"};
constexpr const char* kConditionOutputNames[] = {"encoded_mu"};
constexpr const char* kStepInputNames[] = {"x", "encoded_mu", "y_mask", "speaker_embedding", "t", "dt"};
constexpr const char* kStepOutputNames[] = {"x_next", "mel"};
constexpr const char* kVocoderInputNames[] = {"mel"};
constexpr const char* kVocoderOutputNames[] = {"waveform"};
constexpr int kSessionIntraOpThreads = 1;
constexpr int kVocoderIntraOpThreads = 2;
constexpr float kMinLengthScale = 0.5f;
constexpr float kMaxLengthScale = 2.0f;
constexpr unsigned int kLogDomain = 0x23000;
constexpr const char* kLogTag = "LitsTn";
constexpr const char* kNativeLogTag = "LitsTtsNative";

std::string PreviewForLog(const std::string& value, size_t max_size = 160) {
  std::string output = value.substr(0, max_size);
  for (char& ch : output) {
    if (ch == '\n' || ch == '\r' || ch == '\t') {
      ch = ' ';
    }
  }
  if (value.size() > max_size) {
    output += "...";
  }
  return output;
}

void TnLogInfo(const std::string& message) {
  OH_LOG_Print(LOG_APP, LOG_INFO, kLogDomain, kLogTag, "%{public}s", message.c_str());
}

void TnLogError(const std::string& message) {
  OH_LOG_Print(LOG_APP, LOG_ERROR, kLogDomain, kLogTag, "%{public}s", message.c_str());
}

void NativeLogInfo(const std::string& message) {
  OH_LOG_Print(LOG_APP, LOG_ERROR, kLogDomain, kNativeLogTag, "%{public}s", message.c_str());
}

void NativeLogError(const std::string& message) {
  OH_LOG_Print(LOG_APP, LOG_ERROR, kLogDomain, kNativeLogTag, "%{public}s", message.c_str());
}

Ort::SessionOptions CreateSessionOptions(int intra_op_threads) {
  Ort::SessionOptions options;
  options.SetIntraOpNumThreads(intra_op_threads);
  options.SetInterOpNumThreads(1);
  options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
  options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_DISABLE_ALL);
  return options;
}

struct HiddenEncoderOutput {
  std::vector<float> mu_y;
  std::vector<int64_t> mu_y_shape;
  std::vector<float> y_mask;
  int64_t mel_length = 0;
  std::vector<float> speaker_embedding;
  std::vector<int64_t> speaker_embedding_shape;
};

struct StreamingChunkSlice {
  int start_idx = 0;
  int chunk_size = 0;
  int previous_chunk_size = 0;
};

struct StreamingMetrics {
  int64_t synthesis_ms = -1;
  int64_t first_chunk_ms = -1;
  int64_t audio_bytes = 0;
  int32_t chunk_count = 0;
};

struct Runtime {
  Ort::Env env;
  Ort::MemoryInfo memory_info;
  std::unique_ptr<Ort::Session> hidden_encoder_session;
  std::unique_ptr<Ort::Session> stream_condition_chunk_session;
  std::unique_ptr<Ort::Session> stream_condition_final_session;
  std::unique_ptr<Ort::Session> stream_decoder_step_session;
  std::unique_ptr<Ort::Session> vocoder_session;
  std::future<void> load_future;
  int streaming_chunk_size;
  int streaming_pre_lookahead_len;
  int streaming_mel_cache_len;
  int hop_length;
  int decoder_timesteps;
  float decoder_temperature;
  std::atomic_bool cancel_requested{false};

  Runtime(
      const std::string& hidden_encoder_path,
      const std::string& stream_condition_chunk_path,
      const std::string& stream_condition_final_path,
      const std::string& stream_decoder_step_path,
      const std::string& vocoder_path,
      int chunk_size,
      int pre_lookahead_len,
      int mel_cache_len,
      int hop,
      int timesteps,
      float temperature)
      : env(ORT_LOGGING_LEVEL_WARNING, "litsttsnative"),
        memory_info(Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault)),
        streaming_chunk_size(std::max(1, chunk_size)),
        streaming_pre_lookahead_len(std::max(0, pre_lookahead_len)),
        streaming_mel_cache_len(std::max(1, mel_cache_len)),
        hop_length(std::max(1, hop)),
        decoder_timesteps(std::max(1, timesteps)),
        decoder_temperature(temperature) {
    load_future = std::async(
        std::launch::async,
        [this, hidden_encoder_path, stream_condition_chunk_path, stream_condition_final_path, stream_decoder_step_path, vocoder_path]() {
          hidden_encoder_session = std::make_unique<Ort::Session>(
              env, hidden_encoder_path.c_str(), CreateSessionOptions(kSessionIntraOpThreads));
          stream_condition_chunk_session = std::make_unique<Ort::Session>(
              env, stream_condition_chunk_path.c_str(), CreateSessionOptions(kSessionIntraOpThreads));
          stream_condition_final_session = std::make_unique<Ort::Session>(
              env, stream_condition_final_path.c_str(), CreateSessionOptions(kSessionIntraOpThreads));
          stream_decoder_step_session = std::make_unique<Ort::Session>(
              env, stream_decoder_step_path.c_str(), CreateSessionOptions(kSessionIntraOpThreads));
          vocoder_session = std::make_unique<Ort::Session>(
              env, vocoder_path.c_str(), CreateSessionOptions(kVocoderIntraOpThreads));
        });
  }

  void EnsureLoaded() {
    if (load_future.valid()) {
      load_future.get();
    }
    if (!hidden_encoder_session || !stream_condition_chunk_session || !stream_condition_final_session ||
        !stream_decoder_step_session || !vocoder_session) {
      throw std::runtime_error("runtime sessions are not loaded");
    }
  }
};

struct RuntimeHolder {
  Runtime* runtime = nullptr;
};

struct SynthesizeAsyncContext {
  napi_env env = nullptr;
  napi_async_work work = nullptr;
  napi_deferred deferred = nullptr;
  RuntimeHolder* holder = nullptr;
  std::vector<int64_t> token_ids;
  int64_t speaker_id = 0;
  float length_scale = 1.0f;
  std::vector<int16_t> pcm;
  std::string error;
};

struct StreamingChunkPayload {
  std::vector<int16_t> pcm;
  int32_t sequence = 0;
};

struct SynthesizeStreamingAsyncContext {
  napi_env env = nullptr;
  napi_async_work work = nullptr;
  napi_deferred deferred = nullptr;
  napi_threadsafe_function tsfn = nullptr;
  RuntimeHolder* holder = nullptr;
  std::vector<int64_t> token_ids;
  int64_t speaker_id = 0;
  float length_scale = 1.0f;
  int chunk_size_override = 0;
  StreamingMetrics metrics;
  std::string error;
  std::mutex callback_mutex;
  std::condition_variable callback_cv;
  int pending_callbacks = 0;
};

void DeleteRuntime(RuntimeHolder* holder) {
  if (holder == nullptr) {
    return;
  }
  delete holder->runtime;
  holder->runtime = nullptr;
}

void FinalizeRuntimeHolder(napi_env /*env*/, void* data, void* /*hint*/) {
  auto* holder = static_cast<RuntimeHolder*>(data);
  DeleteRuntime(holder);
  delete holder;
}

std::string GetStringArgument(napi_env env, napi_value value, const char* name) {
  size_t size = 0;
  napi_status status = napi_get_value_string_utf8(env, value, nullptr, 0, &size);
  if (status != napi_ok) {
    throw std::runtime_error(std::string(name) + " must be a string");
  }
  std::string output(size, '\0');
  status = napi_get_value_string_utf8(env, value, output.data(), output.size() + 1, &size);
  if (status != napi_ok) {
    throw std::runtime_error(std::string("failed to read string argument: ") + name);
  }
  return output;
}

int64_t GetInt64Argument(napi_env env, napi_value value, const char* name) {
  int64_t output = 0;
  napi_status status = napi_get_value_int64(env, value, &output);
  if (status != napi_ok) {
    throw std::runtime_error(std::string(name) + " must be an integer");
  }
  return output;
}

double GetDoubleArgument(napi_env env, napi_value value, const char* name) {
  double output = 0.0;
  napi_status status = napi_get_value_double(env, value, &output);
  if (status != napi_ok) {
    throw std::runtime_error(std::string(name) + " must be a number");
  }
  return output;
}

std::vector<int64_t> GetTokenIds(napi_env env, napi_value value) {
  bool is_array = false;
  napi_status status = napi_is_array(env, value, &is_array);
  if (status != napi_ok || !is_array) {
    throw std::runtime_error("tokenIds must be an array");
  }

  uint32_t length = 0;
  status = napi_get_array_length(env, value, &length);
  if (status != napi_ok || length == 0) {
    throw std::runtime_error("tokenIds must not be empty");
  }

  std::vector<int64_t> output(length);
  for (uint32_t index = 0; index < length; ++index) {
    napi_value element = nullptr;
    status = napi_get_element(env, value, index, &element);
    if (status != napi_ok) {
      throw std::runtime_error("failed to read tokenIds element");
    }
    output[index] = GetInt64Argument(env, element, "tokenIds[]");
  }
  return output;
}

RuntimeHolder* GetRuntimeHolder(napi_env env, napi_value handle) {
  napi_valuetype value_type = napi_undefined;
  napi_status status = napi_typeof(env, handle, &value_type);
  if (status != napi_ok || value_type != napi_object) {
    throw std::runtime_error("runtime handle must be an object");
  }

  napi_value external = nullptr;
  status = napi_get_named_property(env, handle, kHandleProperty, &external);
  if (status != napi_ok) {
    throw std::runtime_error("runtime handle is invalid");
  }

  RuntimeHolder* holder = nullptr;
  status = napi_get_value_external(env, external, reinterpret_cast<void**>(&holder));
  if (status != napi_ok || holder == nullptr) {
    throw std::runtime_error("runtime handle is invalid");
  }
  return holder;
}

Runtime* GetRuntime(napi_env env, napi_value handle) {
  RuntimeHolder* holder = GetRuntimeHolder(env, handle);
  if (holder->runtime == nullptr) {
    throw std::runtime_error("runtime handle has been released");
  }
  return holder->runtime;
}

std::vector<int64_t> TensorShape(const Ort::Value& tensor) {
  return tensor.GetTensorTypeAndShapeInfo().GetShape();
}

template <typename T>
std::vector<T> TensorDataCopy(Ort::Value& tensor) {
  auto info = tensor.GetTensorTypeAndShapeInfo();
  const size_t count = info.GetElementCount();
  const T* data = tensor.GetTensorData<T>();
  return std::vector<T>(data, data + count);
}

HiddenEncoderOutput RunHiddenEncoder(
    Runtime* runtime,
    const std::vector<int64_t>& token_ids,
    int64_t speaker_id,
    float length_scale) {
  std::vector<int64_t> token_lengths = {static_cast<int64_t>(token_ids.size())};
  std::vector<int64_t> speaker_ids = {speaker_id};
  std::vector<float> length_scales = {std::clamp(length_scale, kMinLengthScale, kMaxLengthScale)};
  std::vector<int64_t> token_shape = {1, static_cast<int64_t>(token_ids.size())};
  std::vector<int64_t> single_shape = {1};

  Ort::Value token_tensor = Ort::Value::CreateTensor<int64_t>(
      runtime->memory_info, const_cast<int64_t*>(token_ids.data()), token_ids.size(), token_shape.data(), token_shape.size());
  Ort::Value length_tensor = Ort::Value::CreateTensor<int64_t>(
      runtime->memory_info, token_lengths.data(), token_lengths.size(), single_shape.data(), single_shape.size());
  Ort::Value speaker_tensor = Ort::Value::CreateTensor<int64_t>(
      runtime->memory_info, speaker_ids.data(), speaker_ids.size(), single_shape.data(), single_shape.size());
  Ort::Value length_scale_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, length_scales.data(), length_scales.size(), single_shape.data(), single_shape.size());

  std::array<Ort::Value, 4> inputs = {
      std::move(token_tensor), std::move(length_tensor), std::move(speaker_tensor), std::move(length_scale_tensor)};
  auto outputs = runtime->hidden_encoder_session->Run(
      Ort::RunOptions{nullptr}, kHiddenInputNames, inputs.data(), inputs.size(), kHiddenOutputNames, 4);
  if (outputs.size() != 4) {
    throw std::runtime_error("hidden encoder outputs are missing");
  }

  std::vector<int64_t> mel_lengths = TensorDataCopy<int64_t>(outputs[2]);
  if (mel_lengths.empty()) {
    throw std::runtime_error("hidden output mel_length is empty");
  }

  HiddenEncoderOutput hidden;
  hidden.mu_y_shape = TensorShape(outputs[0]);
  hidden.mu_y = TensorDataCopy<float>(outputs[0]);
  hidden.y_mask = TensorDataCopy<float>(outputs[1]);
  hidden.mel_length = mel_lengths.front();
  hidden.speaker_embedding_shape = TensorShape(outputs[3]);
  hidden.speaker_embedding = TensorDataCopy<float>(outputs[3]);
  return hidden;
}

int ChannelsFromShape(const std::vector<int64_t>& shape, int fallback) {
  if (shape.size() >= 2 && shape[1] > 0) {
    return static_cast<int>(shape[1]);
  }
  return fallback;
}

std::vector<float> SliceFrameRange(const std::vector<float>& values, int start_frame, int frame_count, int channels) {
  if (frame_count <= 0 || channels <= 0 || values.empty()) {
    return {};
  }
  const int total_frames = static_cast<int>(values.size()) / channels;
  const int safe_start = std::clamp(start_frame, 0, total_frames);
  const int safe_count = std::min(frame_count, total_frames - safe_start);
  std::vector<float> output(static_cast<size_t>(channels) * safe_count);
  for (int channel = 0; channel < channels; ++channel) {
    const int src_start = channel * total_frames + safe_start;
    const int dst_start = channel * safe_count;
    std::copy_n(values.begin() + src_start, safe_count, output.begin() + dst_start);
  }
  return output;
}

std::vector<float> SliceFramesFrom(const std::vector<float>& values, int start_frame, int channels) {
  if (channels <= 0 || values.empty()) {
    return {};
  }
  const int total_frames = static_cast<int>(values.size()) / channels;
  const int safe_start = std::clamp(start_frame, 0, total_frames);
  return SliceFrameRange(values, safe_start, total_frames - safe_start, channels);
}

std::vector<float> TailFrames(const std::vector<float>& values, int frame_count, int channels) {
  if (channels <= 0 || values.empty()) {
    return {};
  }
  const int total_frames = static_cast<int>(values.size()) / channels;
  return SliceFramesFrom(values, std::max(0, total_frames - frame_count), channels);
}

std::vector<float> ConcatFrames(const std::vector<float>& left, const std::vector<float>& right, int channels) {
  if (left.empty()) {
    return right;
  }
  if (right.empty()) {
    return left;
  }
  const int left_frames = static_cast<int>(left.size()) / channels;
  const int right_frames = static_cast<int>(right.size()) / channels;
  std::vector<float> output(static_cast<size_t>(channels) * (left_frames + right_frames));
  for (int channel = 0; channel < channels; ++channel) {
    const int output_start = channel * (left_frames + right_frames);
    std::copy_n(left.begin() + channel * left_frames, left_frames, output.begin() + output_start);
    std::copy_n(right.begin() + channel * right_frames, right_frames, output.begin() + output_start + left_frames);
  }
  return output;
}

std::vector<float> Prefix(const std::vector<float>& values, int count) {
  if (count <= 0 || values.empty()) {
    return {};
  }
  if (count >= static_cast<int>(values.size())) {
    return values;
  }
  return std::vector<float>(values.begin(), values.begin() + count);
}

std::vector<float> TakeLast(const std::vector<float>& values, int count) {
  if (count <= 0 || values.empty()) {
    return {};
  }
  const int actual = std::min(count, static_cast<int>(values.size()));
  return std::vector<float>(values.end() - actual, values.end());
}

std::vector<float> HammingWindow(int size) {
  if (size <= 0) {
    return {};
  }
  if (size == 1) {
    return {1.0f};
  }
  std::vector<float> output(size);
  for (int index = 0; index < size; ++index) {
    output[index] = static_cast<float>(0.54 - 0.46 * std::cos((2.0 * M_PI * index) / (size - 1)));
  }
  return output;
}

void CrossfadeLeadingInPlace(std::vector<float>* waveform, const std::vector<float>& previous_tail, const std::vector<float>& window) {
  const int overlap = std::min({static_cast<int>(previous_tail.size()), static_cast<int>(waveform->size()), static_cast<int>(window.size()) / 2});
  if (overlap <= 0) {
    return;
  }
  for (int index = 0; index < overlap; ++index) {
    (*waveform)[index] = (*waveform)[index] * window[index] + previous_tail[previous_tail.size() - overlap + index] * window[overlap + index];
  }
}

std::vector<StreamingChunkSlice> BuildStreamingChunkSlices(int mel_length, int first_chunk_size, int chunk_size) {
  const int normalized_first = std::max(1, first_chunk_size);
  const int normalized_chunk = std::max(1, chunk_size);
  if (mel_length <= normalized_first) {
    return {{0, normalized_first, 0}};
  }

  const int remaining_after_first = mel_length - normalized_first;
  const int upper = mel_length - (remaining_after_first % normalized_chunk);
  std::vector<StreamingChunkSlice> slices;
  int start_idx = 0;
  int current_chunk_size = normalized_first;
  int previous_chunk_size = 0;
  while (start_idx < upper) {
    slices.push_back({start_idx, current_chunk_size, previous_chunk_size});
    previous_chunk_size = current_chunk_size;
    start_idx += current_chunk_size;
    current_chunk_size = normalized_chunk;
  }
  if (slices.empty()) {
    slices.push_back({0, normalized_first, 0});
  }
  return slices;
}

std::vector<float> RunDecoder(
    Runtime* runtime,
    Ort::Session* session,
    const std::vector<float>& mu_y,
    int mu_frames,
    const std::vector<float>& y_mask,
    int mask_frames,
    const std::vector<float>& speaker_embedding,
    const std::vector<int64_t>& speaker_embedding_shape,
    int channels) {
  std::vector<int64_t> mu_shape = {1, channels, mu_frames};
  std::vector<int64_t> mask_shape = {1, 1, mask_frames};
  Ort::Value mu_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(mu_y.data()), mu_y.size(), mu_shape.data(), mu_shape.size());
  Ort::Value mask_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(y_mask.data()), y_mask.size(), mask_shape.data(), mask_shape.size());
  Ort::Value speaker_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info,
      const_cast<float*>(speaker_embedding.data()),
      speaker_embedding.size(),
      speaker_embedding_shape.data(),
      speaker_embedding_shape.size());
  std::array<Ort::Value, 3> inputs = {std::move(mu_tensor), std::move(mask_tensor), std::move(speaker_tensor)};
  auto outputs = session->Run(Ort::RunOptions{nullptr}, kDecoderInputNames, inputs.data(), inputs.size(), kDecoderOutputNames, 1);
  if (outputs.empty() || !outputs.front().IsTensor()) {
    throw std::runtime_error("decoder output mel is missing");
  }
  return TensorDataCopy<float>(outputs.front());
}

std::vector<float> GaussianNoise(size_t size, float scale, uint32_t seed) {
  std::mt19937 rng(seed);
  std::normal_distribution<float> distribution(0.0f, scale);
  std::vector<float> output(size);
  for (float& value : output) {
    value = distribution(rng);
  }
  return output;
}

std::vector<float> RunConditionEncoder(
    Runtime* runtime,
    Ort::Session* session,
    const std::vector<float>& mu_y,
    int mu_frames,
    const std::vector<float>& y_mask,
    int mask_frames,
    int channels) {
  std::vector<int64_t> mu_shape = {1, channels, mu_frames};
  std::vector<int64_t> mask_shape = {1, 1, mask_frames};
  Ort::Value mu_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(mu_y.data()), mu_y.size(), mu_shape.data(), mu_shape.size());
  Ort::Value mask_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(y_mask.data()), y_mask.size(), mask_shape.data(), mask_shape.size());
  std::array<Ort::Value, 2> inputs = {std::move(mu_tensor), std::move(mask_tensor)};
  auto outputs = session->Run(Ort::RunOptions{nullptr}, kConditionInputNames, inputs.data(), inputs.size(), kConditionOutputNames, 1);
  if (outputs.empty() || !outputs.front().IsTensor()) {
    throw std::runtime_error("condition output encoded_mu is missing");
  }
  return TensorDataCopy<float>(outputs.front());
}

struct DecoderStepOutput {
  std::vector<float> x_next;
  std::vector<float> mel;
};

DecoderStepOutput RunDecoderStep(
    Runtime* runtime,
    const std::vector<float>& x,
    const std::vector<float>& encoded_mu,
    const std::vector<float>& y_mask,
    int frames,
    const std::vector<float>& speaker_embedding,
    const std::vector<int64_t>& speaker_embedding_shape,
    int channels,
    float t,
    float dt) {
  std::vector<int64_t> frame_shape = {1, channels, frames};
  std::vector<int64_t> mask_shape = {1, 1, frames};
  std::vector<int64_t> scalar_shape = {1};
  Ort::Value x_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(x.data()), x.size(), frame_shape.data(), frame_shape.size());
  Ort::Value mu_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(encoded_mu.data()), encoded_mu.size(), frame_shape.data(), frame_shape.size());
  Ort::Value mask_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(y_mask.data()), y_mask.size(), mask_shape.data(), mask_shape.size());
  Ort::Value speaker_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info,
      const_cast<float*>(speaker_embedding.data()),
      speaker_embedding.size(),
      speaker_embedding_shape.data(),
      speaker_embedding_shape.size());
  Ort::Value t_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, &t, 1, scalar_shape.data(), scalar_shape.size());
  Ort::Value dt_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, &dt, 1, scalar_shape.data(), scalar_shape.size());
  std::array<Ort::Value, 6> inputs = {
      std::move(x_tensor),
      std::move(mu_tensor),
      std::move(mask_tensor),
      std::move(speaker_tensor),
      std::move(t_tensor),
      std::move(dt_tensor),
  };
  auto outputs = runtime->stream_decoder_step_session->Run(
      Ort::RunOptions{nullptr}, kStepInputNames, inputs.data(), inputs.size(), kStepOutputNames, 2);
  if (outputs.size() != 2 || !outputs[0].IsTensor() || !outputs[1].IsTensor()) {
    throw std::runtime_error("decoder step outputs x_next/mel are missing");
  }
  return {TensorDataCopy<float>(outputs[0]), TensorDataCopy<float>(outputs[1])};
}

std::vector<float> RunExternalLoopDecoder(
    Runtime* runtime,
    Ort::Session* condition_session,
    const std::vector<float>& mu_y,
    int mu_frames,
    const std::vector<float>& y_mask,
    int mask_frames,
    const std::vector<float>& speaker_embedding,
    const std::vector<int64_t>& speaker_embedding_shape,
    int channels,
    uint32_t seed,
    int chunk_index,
    const std::function<void(int32_t)>& on_progress) {
  std::vector<float> encoded_mu = RunConditionEncoder(
      runtime, condition_session, mu_y, mu_frames, y_mask, mask_frames, channels);
  on_progress(static_cast<int32_t>(-5000 - chunk_index));
  const int frames = channels == 0 ? 0 : static_cast<int>(encoded_mu.size()) / channels;
  std::vector<float> x = GaussianNoise(encoded_mu.size(), runtime->decoder_temperature, seed);
  std::vector<float> mel(encoded_mu.size());
  for (int step = 0; step < runtime->decoder_timesteps; ++step) {
    on_progress(static_cast<int32_t>(-600000 - chunk_index * 100 - step));
    const float t = static_cast<float>(step) / static_cast<float>(runtime->decoder_timesteps);
    const float dt = 1.0f / static_cast<float>(runtime->decoder_timesteps);
    DecoderStepOutput output = RunDecoderStep(
        runtime,
        x,
        encoded_mu,
        y_mask,
        frames,
        speaker_embedding,
        speaker_embedding_shape,
        channels,
        t,
        dt);
    x = std::move(output.x_next);
    mel = std::move(output.mel);
    on_progress(static_cast<int32_t>(-700000 - chunk_index * 100 - step));
  }
  return mel;
}

std::vector<float> RunVocoder(Runtime* runtime, const std::vector<float>& mel, int channels) {
  const int frames = channels == 0 ? 0 : static_cast<int>(mel.size()) / channels;
  std::vector<int64_t> mel_shape = {1, channels, frames};
  Ort::Value mel_tensor = Ort::Value::CreateTensor<float>(
      runtime->memory_info, const_cast<float*>(mel.data()), mel.size(), mel_shape.data(), mel_shape.size());
  auto outputs = runtime->vocoder_session->Run(Ort::RunOptions{nullptr}, kVocoderInputNames, &mel_tensor, 1, kVocoderOutputNames, 1);
  if (outputs.empty() || !outputs.front().IsTensor()) {
    throw std::runtime_error("vocoder output waveform is missing");
  }
  return TensorDataCopy<float>(outputs.front());
}

StreamingMetrics SynthesizeStreamingNative(
    Runtime* runtime,
    const std::vector<int64_t>& token_ids,
    int64_t speaker_id,
    float length_scale,
    const std::function<void(const std::vector<int16_t>&, int32_t)>& on_chunk,
    int chunk_size_override = 0) {
  runtime->EnsureLoaded();
  const auto started_at = std::chrono::steady_clock::now();
  StreamingMetrics metrics;
  if (runtime->cancel_requested.load(std::memory_order_relaxed)) {
    metrics.synthesis_ms = 0;
    NativeLogInfo("stream cancelled before hidden encoder");
    return metrics;
  }
  const float safe_length_scale = std::clamp(length_scale, kMinLengthScale, kMaxLengthScale);
  HiddenEncoderOutput hidden = RunHiddenEncoder(runtime, token_ids, speaker_id, safe_length_scale);
  if (runtime->cancel_requested.load(std::memory_order_relaxed)) {
    metrics.synthesis_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::steady_clock::now() - started_at)
                               .count();
    NativeLogInfo("stream cancelled after hidden encoder");
    return metrics;
  }
  const int mel_length = static_cast<int>(hidden.mel_length);
  const int channels = ChannelsFromShape(hidden.mu_y_shape, 80);
  const int source_cache_len = runtime->streaming_mel_cache_len * runtime->hop_length;
  const std::vector<float> speech_window = HammingWindow(source_cache_len * 2);
  const int chunk_size = std::max(1, chunk_size_override > 0 ? chunk_size_override : runtime->streaming_chunk_size);
  const std::vector<StreamingChunkSlice> slices =
      BuildStreamingChunkSlices(mel_length, chunk_size, chunk_size);
  {
    std::ostringstream log;
    log << "stream start tokenLength=" << token_ids.size()
        << " speakerId=" << speaker_id
        << " lengthScale=" << safe_length_scale
        << " melLength=" << mel_length
        << " channels=" << channels
        << " chunkSize=" << chunk_size
        << " lookahead=" << runtime->streaming_pre_lookahead_len
        << " melCacheLen=" << runtime->streaming_mel_cache_len
        << " hopLength=" << runtime->hop_length
        << " sliceCount=" << slices.size();
    NativeLogInfo(log.str());
  }

  std::vector<float> mel_cache;
  std::vector<float> waveform_cache;

  for (size_t index = 0; index < slices.size(); ++index) {
    if (runtime->cancel_requested.load(std::memory_order_relaxed)) {
      NativeLogInfo("stream cancelled before chunk index=" + std::to_string(index));
      break;
    }
    const StreamingChunkSlice& slice = slices[index];
    const bool finalize = index == slices.size() - 1;
    const int window_start_idx = std::max(0, slice.start_idx - slice.previous_chunk_size);
    const int window_end_idx = finalize
        ? mel_length
        : std::min(mel_length, slice.start_idx + slice.chunk_size + runtime->streaming_pre_lookahead_len);
    const int window_frames = std::max(0, window_end_idx - window_start_idx);
    std::vector<float> window_mu_y = SliceFrameRange(hidden.mu_y, window_start_idx, window_frames, channels);
    const int output_frames = finalize ? window_frames : std::max(1, window_frames - runtime->streaming_pre_lookahead_len);
    std::vector<float> window_mask(hidden.y_mask.begin() + window_start_idx, hidden.y_mask.begin() + window_start_idx + output_frames);
    on_chunk({}, static_cast<int32_t>(-1000 - static_cast<int>(index)));
    std::vector<float> mel_window = RunExternalLoopDecoder(
        runtime,
        finalize ? runtime->stream_condition_final_session.get() : runtime->stream_condition_chunk_session.get(),
        window_mu_y,
        window_frames,
        window_mask,
        output_frames,
        hidden.speaker_embedding,
        hidden.speaker_embedding_shape,
        channels,
        static_cast<uint32_t>(20260624 + index),
        static_cast<int>(index),
        [&on_chunk](int32_t marker) {
          on_chunk({}, marker);
        });
    on_chunk({}, static_cast<int32_t>(-2000 - static_cast<int>(index)));
    std::vector<float> mel_chunk = SliceFramesFrom(mel_window, slice.start_idx - window_start_idx, channels);
    if (!mel_cache.empty()) {
      mel_chunk = ConcatFrames(mel_cache, mel_chunk, channels);
    }
    std::vector<float> waveform = RunVocoder(runtime, mel_chunk, channels);
    on_chunk({}, static_cast<int32_t>(-3000 - static_cast<int>(index)));
    if (runtime->cancel_requested.load(std::memory_order_relaxed)) {
      NativeLogInfo("stream cancelled after vocoder index=" + std::to_string(index));
      break;
    }
    if (!waveform_cache.empty()) {
      CrossfadeLeadingInPlace(&waveform, waveform_cache, speech_window);
    }
    const int emit_samples = finalize ? static_cast<int>(waveform.size()) : std::max(0, static_cast<int>(waveform.size()) - source_cache_len);
    if (!finalize) {
      mel_cache = TailFrames(mel_chunk, runtime->streaming_mel_cache_len, channels);
      waveform_cache = TakeLast(waveform, source_cache_len);
    }
    std::vector<float> emitted = Prefix(waveform, emit_samples);
    if (emitted.empty()) {
      continue;
    }
    on_chunk({}, static_cast<int32_t>(-4000 - static_cast<int>(index)));
    std::vector<int16_t> chunk(emitted.size());
    for (size_t sample = 0; sample < emitted.size(); ++sample) {
      const float clipped = std::max(-1.0f, std::min(1.0f, emitted[sample]));
      chunk[sample] = static_cast<int16_t>(std::lround(clipped * 32767.0f));
    }
    if (metrics.first_chunk_ms < 0) {
      metrics.first_chunk_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                   std::chrono::steady_clock::now() - started_at)
                                   .count();
    }
    metrics.audio_bytes += static_cast<int64_t>(chunk.size() * sizeof(int16_t));
    {
      std::ostringstream log;
      log << "stream chunk index=" << index
          << " finalize=" << (finalize ? 1 : 0)
          << " startIdx=" << slice.start_idx
          << " chunkSize=" << slice.chunk_size
          << " previousChunkSize=" << slice.previous_chunk_size
          << " windowFrames=" << window_frames
          << " outputFrames=" << output_frames
          << " emitSamples=" << emit_samples
          << " emittedBytes=" << chunk.size() * sizeof(int16_t)
          << " readyAtMs=" << std::chrono::duration_cast<std::chrono::milliseconds>(
                                  std::chrono::steady_clock::now() - started_at)
                                  .count();
      NativeLogInfo(log.str());
    }
    on_chunk(chunk, metrics.chunk_count);
    metrics.chunk_count += 1;
  }
  metrics.synthesis_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::steady_clock::now() - started_at)
                             .count();
  {
    std::ostringstream log;
    log << "stream complete synthesisMs=" << metrics.synthesis_ms
        << " firstChunkMs=" << metrics.first_chunk_ms
        << " audioBytes=" << metrics.audio_bytes
        << " chunkCount=" << metrics.chunk_count;
    NativeLogInfo(log.str());
  }
  return metrics;
}

std::vector<int16_t> Synthesize(
    Runtime* runtime,
    const std::vector<int64_t>& token_ids,
    int64_t speaker_id,
    float length_scale = 1.0f) {
  std::vector<int16_t> pcm;
  SynthesizeStreamingNative(
      runtime,
      token_ids,
      speaker_id,
      length_scale,
      [&pcm](const std::vector<int16_t>& chunk, int32_t /*sequence*/) {
        const size_t base = pcm.size();
        pcm.resize(base + chunk.size());
        std::copy(chunk.begin(), chunk.end(), pcm.begin() + static_cast<std::ptrdiff_t>(base));
      });
  return pcm;
}

void ThrowError(napi_env env, const std::string& message) {
  napi_throw_error(env, nullptr, message.c_str());
}

std::string ErrnoMessage(const std::string& action) {
  return action + ": " + std::strerror(errno);
}

void CloseFd(int fd) {
  if (fd >= 0) {
    close(fd);
  }
}

void WriteAll(int fd, const std::string& payload) {
  const char* data = payload.data();
  size_t remaining = payload.size();
  while (remaining > 0) {
    const ssize_t written = write(fd, data, remaining);
    if (written < 0) {
      if (errno == EINTR) {
        continue;
      }
      throw std::runtime_error(ErrnoMessage("failed to write to TN process"));
    }
    data += written;
    remaining -= static_cast<size_t>(written);
  }
}

std::string ReadAll(int fd) {
  std::string output;
  std::array<char, 4096> buffer{};
  while (true) {
    const ssize_t read_size = read(fd, buffer.data(), buffer.size());
    if (read_size < 0) {
      if (errno == EINTR) {
        continue;
      }
      throw std::runtime_error(ErrnoMessage("failed to read from TN process"));
    }
    if (read_size == 0) {
      break;
    }
    output.append(buffer.data(), static_cast<size_t>(read_size));
  }
  return output;
}

std::string ReadLine(int fd) {
  std::string output;
  char ch = '\0';
  while (true) {
    const ssize_t read_size = read(fd, &ch, 1);
    if (read_size < 0) {
      if (errno == EINTR) {
        continue;
      }
      throw std::runtime_error(ErrnoMessage("failed to read line from TN process"));
    }
    if (read_size == 0 || ch == '\n' || ch == '\r') {
      break;
    }
    output.push_back(ch);
  }
  return output;
}

std::string TrimLine(std::string value) {
  while (!value.empty() && (value.back() == '\n' || value.back() == '\r' || value.back() == ' ' || value.back() == '\t')) {
    value.pop_back();
  }
  size_t start = 0;
  while (start < value.size() && (value[start] == '\n' || value[start] == '\r' || value[start] == ' ' || value[start] == '\t')) {
    start += 1;
  }
  if (start > 0) {
    value.erase(0, start);
  }
  const size_t newline = value.find_first_of("\r\n");
  if (newline != std::string::npos) {
    value.erase(newline);
  }
  return value;
}

class TnProcess {
 public:
  TnProcess(std::string binary_path, std::string working_dir)
      : binary_path_(std::move(binary_path)), working_dir_(std::move(working_dir)) {
    Start();
  }

  ~TnProcess() {
    Stop();
  }

  std::string Normalize(const std::string& text) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!IsAlive()) {
      TnLogInfo("TN process not alive; restarting binary=" + binary_path_);
      Stop();
      Start();
    }
    try {
      return NormalizeOnce(text);
    } catch (const std::exception& error) {
      TnLogError("TN normalize failed; restarting once pid=" + std::to_string(pid_) + " error=" + error.what());
      Stop();
      Start();
      return NormalizeOnce(text);
    } catch (...) {
      TnLogError("TN normalize failed; restarting once pid=" + std::to_string(pid_) + " error=unknown");
      Stop();
      Start();
      return NormalizeOnce(text);
    }
  }

 private:
  std::string binary_path_;
  std::string working_dir_;
  pid_t pid_ = -1;
  int stdin_fd_ = -1;
  int stdout_fd_ = -1;
  std::mutex mutex_;

  std::string NormalizeOnce(const std::string& text) {
    TnLogInfo("TN normalize write pid=" + std::to_string(pid_) + " textLen=" + std::to_string(text.size()) +
              " preview=" + PreviewForLog(text));
    WriteAll(stdin_fd_, text + "\n");
    const std::string normalized = TrimLine(ReadLine(stdout_fd_));
    if (normalized.empty() && !IsAlive()) {
      throw std::runtime_error("TN process exited without output");
    }
    TnLogInfo("TN normalize read pid=" + std::to_string(pid_) + " outputLen=" + std::to_string(normalized.size()) +
              " preview=" + PreviewForLog(normalized));
    return normalized.empty() ? text : normalized;
  }

  void Start() {
    const int chmod_result = chmod(binary_path_.c_str(), S_IRUSR | S_IWUSR | S_IXUSR);
    if (chmod_result != 0) {
      TnLogError("TN chmod failed binary=" + binary_path_ + " error=" + ErrnoMessage("chmod"));
    }
    TnLogInfo("TN start binary=" + binary_path_ + " cwd=" + working_dir_);
    int stdin_pipe[2] = {-1, -1};
    int stdout_pipe[2] = {-1, -1};
    int stderr_pipe[2] = {-1, -1};
    if (pipe(stdin_pipe) != 0) {
      throw std::runtime_error(ErrnoMessage("failed to create TN stdin pipe"));
    }
    if (pipe(stdout_pipe) != 0) {
      CloseFd(stdin_pipe[0]);
      CloseFd(stdin_pipe[1]);
      throw std::runtime_error(ErrnoMessage("failed to create TN stdout pipe"));
    }
    if (pipe(stderr_pipe) != 0) {
      CloseFd(stdin_pipe[0]);
      CloseFd(stdin_pipe[1]);
      CloseFd(stdout_pipe[0]);
      CloseFd(stdout_pipe[1]);
      throw std::runtime_error(ErrnoMessage("failed to create TN stderr pipe"));
    }

    const pid_t pid = fork();
    if (pid < 0) {
      CloseFd(stdin_pipe[0]);
      CloseFd(stdin_pipe[1]);
      CloseFd(stdout_pipe[0]);
      CloseFd(stdout_pipe[1]);
      CloseFd(stderr_pipe[0]);
      CloseFd(stderr_pipe[1]);
      throw std::runtime_error(ErrnoMessage("failed to fork TN process"));
    }
    if (pid == 0) {
      dup2(stdin_pipe[0], STDIN_FILENO);
      dup2(stdout_pipe[1], STDOUT_FILENO);
      dup2(stderr_pipe[1], STDERR_FILENO);
      CloseFd(stdin_pipe[0]);
      CloseFd(stdin_pipe[1]);
      CloseFd(stdout_pipe[0]);
      CloseFd(stdout_pipe[1]);
      CloseFd(stderr_pipe[0]);
      CloseFd(stderr_pipe[1]);
      if (chdir(working_dir_.c_str()) != 0) {
        dprintf(STDERR_FILENO, "chdir failed: %s\n", strerror(errno));
        _exit(126);
      }
      setenv("TTS_RULES_ROOT", working_dir_.c_str(), 1);
      setenv("TTS_RULES_FORMAT", "v2", 1);
      setenv("TTS_NORMALIZER_DEBUG", "1", 1);
      execl(binary_path_.c_str(), binary_path_.c_str(), static_cast<char*>(nullptr));
      dprintf(STDERR_FILENO, "exec failed: %s\n", strerror(errno));
      _exit(127);
    }

    CloseFd(stdin_pipe[0]);
    CloseFd(stdout_pipe[1]);
    CloseFd(stderr_pipe[1]);
    const int stderr_read_fd = stderr_pipe[0];
    const std::string stderr_binary = binary_path_;
    std::thread([stderr_read_fd, stderr_binary]() {
      try {
        while (true) {
          const std::string line = TrimLine(ReadLine(stderr_read_fd));
          if (line.empty()) {
            break;
          }
          TnLogError("TN stderr binary=" + stderr_binary + " output=" + PreviewForLog(line, 800));
        }
        CloseFd(stderr_read_fd);
      } catch (const std::exception& error) {
        CloseFd(stderr_read_fd);
        TnLogError("TN stderr reader failed binary=" + stderr_binary + " error=" + error.what());
      }
    }).detach();
    pid_ = pid;
    stdin_fd_ = stdin_pipe[1];
    stdout_fd_ = stdout_pipe[0];
    TnLogInfo("TN started pid=" + std::to_string(pid_) + " binary=" + binary_path_ +
              " rulesRoot=" + working_dir_ + " rulesFormat=v2 debug=1");
  }

  void Stop() {
    CloseFd(stdin_fd_);
    CloseFd(stdout_fd_);
    stdin_fd_ = -1;
    stdout_fd_ = -1;
    if (pid_ > 0) {
      TnLogInfo("TN stop pid=" + std::to_string(pid_) + " binary=" + binary_path_);
      kill(pid_, SIGTERM);
      int status = 0;
      while (waitpid(pid_, &status, 0) < 0 && errno == EINTR) {
      }
      LogExitStatus(status);
      pid_ = -1;
    }
  }

  bool IsAlive() {
    if (pid_ <= 0) {
      return false;
    }
    int status = 0;
    const pid_t result = waitpid(pid_, &status, WNOHANG);
    if (result == 0) {
      return true;
    }
    if (result == pid_) {
      LogExitStatus(status);
      pid_ = -1;
      return false;
    }
    return errno == EINTR;
  }

  void LogExitStatus(int status) const {
    if (WIFEXITED(status)) {
      TnLogError("TN exited pid=" + std::to_string(pid_) + " code=" + std::to_string(WEXITSTATUS(status)) +
                 " binary=" + binary_path_);
    } else if (WIFSIGNALED(status)) {
      TnLogError("TN signaled pid=" + std::to_string(pid_) + " signal=" + std::to_string(WTERMSIG(status)) +
                 " binary=" + binary_path_);
    } else {
      TnLogError("TN stopped pid=" + std::to_string(pid_) + " status=" + std::to_string(status) +
                 " binary=" + binary_path_);
    }
  }
};

std::mutex g_tn_processes_mutex;
std::map<std::string, std::unique_ptr<TnProcess>> g_tn_processes;

std::string NormalizeWithTnBinary(
    const std::string& binary_path,
    const std::string& working_dir,
    const std::string& text) {
  if (text.empty()) {
    return text;
  }
  const std::string key = working_dir + "\n" + binary_path;
  TnProcess* process = nullptr;
  {
    std::lock_guard<std::mutex> lock(g_tn_processes_mutex);
    auto& cached = g_tn_processes[key];
    if (!cached) {
      TnLogInfo("TN cache create binary=" + binary_path + " cwd=" + working_dir);
      cached = std::make_unique<TnProcess>(binary_path, working_dir);
    } else {
      TnLogInfo("TN cache reuse binary=" + binary_path + " cwd=" + working_dir);
    }
    process = cached.get();
  }
  return process->Normalize(text);
}

napi_value NormalizeTnSegmentWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 3;
    napi_value args[3] = {nullptr, nullptr, nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 3) {
      throw std::runtime_error("normalizeTnSegment expects binaryPath, workingDir, and text");
    }
    const std::string binary_path = GetStringArgument(env, args[0], "binaryPath");
    const std::string working_dir = GetStringArgument(env, args[1], "workingDir");
    const std::string text = GetStringArgument(env, args[2], "text");
    TnLogInfo("normalizeTnSegment call binary=" + binary_path + " cwd=" + working_dir +
              " textLen=" + std::to_string(text.size()) + " preview=" + PreviewForLog(text));
    const std::string normalized = NormalizeWithTnBinary(binary_path, working_dir, text);
    TnLogInfo("normalizeTnSegment success outputLen=" + std::to_string(normalized.size()) +
              " preview=" + PreviewForLog(normalized));
    napi_value output = nullptr;
    napi_create_string_utf8(env, normalized.c_str(), normalized.size(), &output);
    return output;
  } catch (const std::exception& error) {
    TnLogError(std::string("normalizeTnSegment failed error=") + error.what());
    ThrowError(env, error.what());
    return nullptr;
  }
}

napi_value CreateRuntimeWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 11;
    napi_value args[11] = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 11) {
      throw std::runtime_error("createRuntime expects hiddenEncoderPath, streamConditionChunkPath, streamConditionFinalPath, streamDecoderStepPath, vocoderPath, chunkSize, preLookaheadLen, melCacheLen, hopLength, decoderTimesteps, and decoderTemperature");
    }

    const std::string hidden_encoder_path = GetStringArgument(env, args[0], "hiddenEncoderPath");
    const std::string stream_condition_chunk_path = GetStringArgument(env, args[1], "streamConditionChunkPath");
    const std::string stream_condition_final_path = GetStringArgument(env, args[2], "streamConditionFinalPath");
    const std::string stream_decoder_step_path = GetStringArgument(env, args[3], "streamDecoderStepPath");
    const std::string vocoder_path = GetStringArgument(env, args[4], "vocoderPath");
    const int chunk_size = static_cast<int>(GetInt64Argument(env, args[5], "chunkSize"));
    const int pre_lookahead_len = static_cast<int>(GetInt64Argument(env, args[6], "preLookaheadLen"));
    const int mel_cache_len = static_cast<int>(GetInt64Argument(env, args[7], "melCacheLen"));
    const int hop_length = static_cast<int>(GetInt64Argument(env, args[8], "hopLength"));
    const int decoder_timesteps = static_cast<int>(GetInt64Argument(env, args[9], "decoderTimesteps"));
    double decoder_temperature = 0.0;
    napi_get_value_double(env, args[10], &decoder_temperature);

    std::unique_ptr<RuntimeHolder> holder(new RuntimeHolder());
    holder->runtime = new Runtime(
        hidden_encoder_path,
        stream_condition_chunk_path,
        stream_condition_final_path,
        stream_decoder_step_path,
        vocoder_path,
        chunk_size,
        pre_lookahead_len,
        mel_cache_len,
        hop_length,
        decoder_timesteps,
        static_cast<float>(decoder_temperature));

    napi_value external = nullptr;
    napi_create_external(env, holder.get(), FinalizeRuntimeHolder, nullptr, &external);

    napi_value handle = nullptr;
    napi_create_object(env, &handle);
    napi_set_named_property(env, handle, kHandleProperty, external);
    holder.release();
    return handle;
  } catch (const Ort::Exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  } catch (const std::exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  }
}

napi_value ReleaseRuntimeWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 1;
    napi_value args[1] = {nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 1) {
      throw std::runtime_error("releaseRuntime expects a runtime handle");
    }

    RuntimeHolder* holder = GetRuntimeHolder(env, args[0]);
    DeleteRuntime(holder);

    napi_value null_value = nullptr;
    napi_get_null(env, &null_value);
    napi_set_named_property(env, args[0], kHandleProperty, null_value);

    napi_value undefined_value = nullptr;
    napi_get_undefined(env, &undefined_value);
    return undefined_value;
  } catch (const std::exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  }
}

napi_value CancelRuntimeWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 1;
    napi_value args[1] = {nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 1) {
      throw std::runtime_error("cancelRuntime expects runtimeHandle");
    }
    RuntimeHolder* holder = GetRuntimeHolder(env, args[0]);
    if (holder->runtime != nullptr) {
      holder->runtime->cancel_requested.store(true, std::memory_order_relaxed);
      NativeLogInfo("runtime cancel requested");
    }
    napi_value output = nullptr;
    napi_get_undefined(env, &output);
    return output;
  } catch (const std::exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  }
}

napi_value SynthesizeWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 3;
    napi_value args[3] = {nullptr, nullptr, nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 3) {
      throw std::runtime_error("synthesize expects runtimeHandle, tokenIds, and speakerId");
    }

    Runtime* runtime = GetRuntime(env, args[0]);
    std::vector<int64_t> token_ids = GetTokenIds(env, args[1]);
    const int64_t speaker_id = GetInt64Argument(env, args[2], "speakerId");

    std::vector<int16_t> pcm = Synthesize(runtime, token_ids, speaker_id);

    void* data = nullptr;
    napi_value output = nullptr;
    napi_create_arraybuffer(env, pcm.size() * sizeof(int16_t), &data, &output);
    std::memcpy(data, pcm.data(), pcm.size() * sizeof(int16_t));
    return output;
  } catch (const Ort::Exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  } catch (const std::exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  }
}

void ExecuteSynthesize(napi_env /*env*/, void* data) {
  auto* context = static_cast<SynthesizeAsyncContext*>(data);
  try {
    if (context->holder == nullptr || context->holder->runtime == nullptr) {
      throw std::runtime_error("runtime handle has been released");
    }
    context->pcm = Synthesize(context->holder->runtime, context->token_ids, context->speaker_id, context->length_scale);
  } catch (const Ort::Exception& error) {
    context->error = error.what();
  } catch (const std::exception& error) {
    context->error = error.what();
  }
}

void CompleteSynthesize(napi_env env, napi_status /*status*/, void* data) {
  std::unique_ptr<SynthesizeAsyncContext> context(static_cast<SynthesizeAsyncContext*>(data));
  if (!context->error.empty()) {
    napi_value message = nullptr;
    napi_create_string_utf8(env, context->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_reject_deferred(env, context->deferred, message);
  } else {
    void* buffer_data = nullptr;
    napi_value output = nullptr;
    napi_create_arraybuffer(env, context->pcm.size() * sizeof(int16_t), &buffer_data, &output);
    std::memcpy(buffer_data, context->pcm.data(), context->pcm.size() * sizeof(int16_t));
    napi_resolve_deferred(env, context->deferred, output);
  }
  napi_delete_async_work(env, context->work);
}

napi_value SynthesizeAsyncWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 4;
    napi_value args[4] = {nullptr, nullptr, nullptr, nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 3) {
      throw std::runtime_error("synthesizeAsync expects runtimeHandle, tokenIds, and speakerId");
    }

    auto context = std::make_unique<SynthesizeAsyncContext>();
    context->env = env;
    context->holder = GetRuntimeHolder(env, args[0]);
    if (context->holder->runtime == nullptr) {
      throw std::runtime_error("runtime handle has been released");
    }
    context->holder->runtime->cancel_requested.store(false, std::memory_order_relaxed);
    context->token_ids = GetTokenIds(env, args[1]);
    context->speaker_id = GetInt64Argument(env, args[2], "speakerId");
    context->length_scale = argc >= 4
        ? static_cast<float>(GetDoubleArgument(env, args[3], "lengthScale"))
        : 1.0f;

    napi_value promise = nullptr;
    napi_create_promise(env, &context->deferred, &promise);
    napi_value resource_name = nullptr;
    napi_create_string_utf8(env, "LitsTtsSynthesize", NAPI_AUTO_LENGTH, &resource_name);
    napi_create_async_work(env, nullptr, resource_name, ExecuteSynthesize, CompleteSynthesize, context.get(), &context->work);
    napi_queue_async_work(env, context->work);
    context.release();
    return promise;
  } catch (const std::exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  }
}

void CallStreamingChunkJs(napi_env env, napi_value js_callback, void* context_data, void* data) {
  auto* context = static_cast<SynthesizeStreamingAsyncContext*>(context_data);
  std::unique_ptr<StreamingChunkPayload> payload(static_cast<StreamingChunkPayload*>(data));
  if (env != nullptr && js_callback != nullptr && payload != nullptr) {
    void* buffer_data = nullptr;
    napi_value chunk = nullptr;
    napi_create_arraybuffer(env, payload->pcm.size() * sizeof(int16_t), &buffer_data, &chunk);
    std::memcpy(buffer_data, payload->pcm.data(), payload->pcm.size() * sizeof(int16_t));
    napi_value sequence = nullptr;
    napi_create_int32(env, payload->sequence, &sequence);
    napi_value argv[2] = {chunk, sequence};
    napi_value global = nullptr;
    napi_get_global(env, &global);
    napi_call_function(env, global, js_callback, 2, argv, nullptr);
  }
  if (context != nullptr) {
    {
      std::lock_guard<std::mutex> lock(context->callback_mutex);
      context->pending_callbacks = std::max(0, context->pending_callbacks - 1);
    }
    context->callback_cv.notify_all();
  }
}

void ExecuteSynthesizeStreaming(napi_env /*env*/, void* data) {
  auto* context = static_cast<SynthesizeStreamingAsyncContext*>(data);
  try {
    if (context->holder == nullptr || context->holder->runtime == nullptr) {
      throw std::runtime_error("runtime handle has been released");
    }
    context->metrics = SynthesizeStreamingNative(
        context->holder->runtime,
        context->token_ids,
        context->speaker_id,
        context->length_scale,
        [context](const std::vector<int16_t>& chunk, int32_t sequence) {
          auto* payload = new StreamingChunkPayload();
          payload->pcm = chunk;
          payload->sequence = sequence;
          {
            std::lock_guard<std::mutex> lock(context->callback_mutex);
            context->pending_callbacks += 1;
          }
          napi_status status = napi_call_threadsafe_function(context->tsfn, payload, napi_tsfn_blocking);
          if (status != napi_ok) {
            delete payload;
            {
              std::lock_guard<std::mutex> lock(context->callback_mutex);
              context->pending_callbacks = std::max(0, context->pending_callbacks - 1);
            }
            context->callback_cv.notify_all();
          }
        },
        context->chunk_size_override);
    std::unique_lock<std::mutex> lock(context->callback_mutex);
    context->callback_cv.wait(lock, [context]() {
      return context->pending_callbacks == 0;
    });
  } catch (const Ort::Exception& error) {
    context->error = error.what();
    NativeLogError(std::string("synthesizeStreaming Ort exception: ") + context->error);
  } catch (const std::exception& error) {
    context->error = error.what();
    NativeLogError(std::string("synthesizeStreaming exception: ") + context->error);
  }
  if (context->tsfn != nullptr) {
    napi_release_threadsafe_function(context->tsfn, napi_tsfn_release);
  }
}

void CompleteSynthesizeStreaming(napi_env env, napi_status /*status*/, void* data) {
  std::unique_ptr<SynthesizeStreamingAsyncContext> context(static_cast<SynthesizeStreamingAsyncContext*>(data));
  if (!context->error.empty()) {
    napi_value message = nullptr;
    napi_create_string_utf8(env, context->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_reject_deferred(env, context->deferred, message);
  } else {
    napi_value output = nullptr;
    napi_create_object(env, &output);
    napi_value value = nullptr;
    napi_create_int64(env, context->metrics.synthesis_ms, &value);
    napi_set_named_property(env, output, "synthesisMs", value);
    napi_create_int64(env, context->metrics.first_chunk_ms, &value);
    napi_set_named_property(env, output, "firstChunkMs", value);
    napi_create_int64(env, context->metrics.audio_bytes, &value);
    napi_set_named_property(env, output, "audioBytes", value);
    napi_create_int32(env, context->metrics.chunk_count, &value);
    napi_set_named_property(env, output, "chunkCount", value);
    napi_resolve_deferred(env, context->deferred, output);
  }
  napi_delete_async_work(env, context->work);
}

napi_value SynthesizeStreamingWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 6;
    napi_value args[6] = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 5) {
      throw std::runtime_error("synthesizeStreaming expects runtimeHandle, tokenIds, speakerId, lengthScale, optional chunkSizeOverride, and onChunk");
    }
    const bool has_chunk_size_override = argc >= 6;
    napi_value callback_arg = has_chunk_size_override ? args[5] : args[4];
    napi_valuetype callback_type = napi_undefined;
    napi_typeof(env, callback_arg, &callback_type);
    if (callback_type != napi_function) {
      throw std::runtime_error("onChunk must be a function");
    }

    auto context = std::make_unique<SynthesizeStreamingAsyncContext>();
    context->env = env;
    context->holder = GetRuntimeHolder(env, args[0]);
    if (context->holder->runtime == nullptr) {
      throw std::runtime_error("runtime handle has been released");
    }
    context->holder->runtime->cancel_requested.store(false, std::memory_order_relaxed);
    context->token_ids = GetTokenIds(env, args[1]);
    context->speaker_id = GetInt64Argument(env, args[2], "speakerId");
    context->length_scale = static_cast<float>(GetDoubleArgument(env, args[3], "lengthScale"));
    if (has_chunk_size_override) {
      const int64_t chunk_size_override = GetInt64Argument(env, args[4], "chunkSizeOverride");
      context->chunk_size_override = chunk_size_override > 0 ? static_cast<int>(chunk_size_override) : 0;
    }

    napi_value promise = nullptr;
    napi_create_promise(env, &context->deferred, &promise);
    napi_value resource_name = nullptr;
    napi_create_string_utf8(env, "LitsTtsSynthesizeStreaming", NAPI_AUTO_LENGTH, &resource_name);
    napi_create_threadsafe_function(
        env,
        callback_arg,
        nullptr,
        resource_name,
        0,
        1,
        nullptr,
        nullptr,
        context.get(),
        CallStreamingChunkJs,
        &context->tsfn);
    napi_create_async_work(
        env,
        nullptr,
        resource_name,
        ExecuteSynthesizeStreaming,
        CompleteSynthesizeStreaming,
        context.get(),
        &context->work);
    napi_queue_async_work(env, context->work);
    context.release();
    return promise;
  } catch (const std::exception& error) {
    ThrowError(env, error.what());
    return nullptr;
  }
}

napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"createRuntime", nullptr, CreateRuntimeWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"releaseRuntime", nullptr, ReleaseRuntimeWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"cancelRuntime", nullptr, CancelRuntimeWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"synthesize", nullptr, SynthesizeWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"synthesizeAsync", nullptr, SynthesizeAsyncWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"synthesizeStreaming", nullptr, SynthesizeStreamingWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"normalizeTnSegment", nullptr, NormalizeTnSegmentWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
  };

  napi_define_properties(env, exports, sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
  return exports;
}

}  // namespace

NAPI_MODULE(litsttsnative, Init)
