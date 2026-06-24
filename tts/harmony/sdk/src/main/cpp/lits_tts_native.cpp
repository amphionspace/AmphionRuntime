#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <node_api.h>

#include "third_party/onnxruntime/include/onnxruntime_cxx_api.h"

namespace {

constexpr const char* kHandleProperty = "__nativeHandle";
constexpr const char* kAcousticInputNames[] = {"token_ids", "token_lengths", "speaker_id"};
constexpr const char* kAcousticOutputNames[] = {"mel"};
constexpr const char* kVocoderInputNames[] = {"mel"};
constexpr const char* kVocoderOutputNames[] = {"waveform"};
constexpr int kAcousticIntraOpThreads = 2;
constexpr int kVocoderIntraOpThreads = 6;

Ort::SessionOptions CreateSessionOptions(int intra_op_threads) {
  Ort::SessionOptions options;
  options.SetIntraOpNumThreads(intra_op_threads);
  options.SetInterOpNumThreads(1);
  options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
  options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
  return options;
}

struct Runtime {
  Ort::Env env;
  Ort::MemoryInfo memory_info;
  Ort::Session acoustic_session;
  Ort::Session vocoder_session;

  Runtime(const std::string& acoustic_model_path, const std::string& vocoder_model_path)
      : env(ORT_LOGGING_LEVEL_WARNING, "litsttsnative"),
        memory_info(Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault)),
        acoustic_session(env, acoustic_model_path.c_str(), CreateSessionOptions(kAcousticIntraOpThreads)),
        vocoder_session(env, vocoder_model_path.c_str(), CreateSessionOptions(kVocoderIntraOpThreads)) {}
};

struct RuntimeHolder {
  Runtime* runtime = nullptr;
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

std::vector<int16_t> Synthesize(Runtime* runtime, const std::vector<int64_t>& token_ids, int64_t speaker_id) {
  std::vector<int64_t> token_lengths = {static_cast<int64_t>(token_ids.size())};
  std::vector<int64_t> speaker_ids = {speaker_id};
  std::vector<int64_t> token_shape = {1, static_cast<int64_t>(token_ids.size())};
  std::vector<int64_t> single_value_shape = {1};

  Ort::Value token_tensor = Ort::Value::CreateTensor<int64_t>(
      runtime->memory_info,
      const_cast<int64_t*>(token_ids.data()),
      token_ids.size(),
      token_shape.data(),
      token_shape.size());
  Ort::Value token_length_tensor = Ort::Value::CreateTensor<int64_t>(
      runtime->memory_info,
      token_lengths.data(),
      token_lengths.size(),
      single_value_shape.data(),
      single_value_shape.size());
  Ort::Value speaker_tensor = Ort::Value::CreateTensor<int64_t>(
      runtime->memory_info,
      speaker_ids.data(),
      speaker_ids.size(),
      single_value_shape.data(),
      single_value_shape.size());

  std::array<Ort::Value, 3> acoustic_inputs = {
      std::move(token_tensor),
      std::move(token_length_tensor),
      std::move(speaker_tensor),
  };

  auto acoustic_outputs = runtime->acoustic_session.Run(
      Ort::RunOptions{nullptr},
      kAcousticInputNames,
      acoustic_inputs.data(),
      acoustic_inputs.size(),
      kAcousticOutputNames,
      1);

  if (acoustic_outputs.empty() || !acoustic_outputs.front().IsTensor()) {
    throw std::runtime_error("acoustic output mel is missing");
  }

  Ort::Value& mel_tensor = acoustic_outputs.front();

  auto vocoder_outputs = runtime->vocoder_session.Run(
      Ort::RunOptions{nullptr},
      kVocoderInputNames,
      &mel_tensor,
      1,
      kVocoderOutputNames,
      1);

  if (vocoder_outputs.empty() || !vocoder_outputs.front().IsTensor()) {
    throw std::runtime_error("vocoder output waveform is missing");
  }

  Ort::Value& waveform_tensor = vocoder_outputs.front();
  auto info = waveform_tensor.GetTensorTypeAndShapeInfo();
  size_t sample_count = info.GetElementCount();
  const float* waveform = waveform_tensor.GetTensorData<float>();

  std::vector<int16_t> pcm(sample_count);
  for (size_t index = 0; index < sample_count; ++index) {
    const float clipped = std::max(-1.0f, std::min(1.0f, waveform[index]));
    pcm[index] = static_cast<int16_t>(std::lround(clipped * 32767.0f));
  }
  return pcm;
}

void ThrowError(napi_env env, const std::string& message) {
  napi_throw_error(env, nullptr, message.c_str());
}

napi_value CreateRuntimeWrapped(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 2;
    napi_value args[2] = {nullptr, nullptr};
    napi_value this_arg = nullptr;
    napi_get_cb_info(env, info, &argc, args, &this_arg, nullptr);
    if (argc < 2) {
      throw std::runtime_error("createRuntime expects acousticPath and vocoderPath");
    }

    const std::string acoustic_path = GetStringArgument(env, args[0], "acousticPath");
    const std::string vocoder_path = GetStringArgument(env, args[1], "vocoderPath");

    std::unique_ptr<RuntimeHolder> holder(new RuntimeHolder());
    holder->runtime = new Runtime(acoustic_path, vocoder_path);

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

napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"createRuntime", nullptr, CreateRuntimeWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"releaseRuntime", nullptr, ReleaseRuntimeWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"synthesize", nullptr, SynthesizeWrapped, nullptr, nullptr, nullptr, napi_default, nullptr},
  };

  napi_define_properties(env, exports, sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
  return exports;
}

}  // namespace

NAPI_MODULE(litsttsnative, Init)
