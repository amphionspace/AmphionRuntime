#include "agc_bridge.h"

#include <stdexcept>
#include <string>

#include "amphion_audio_processing.h"

namespace {

struct AgcHolder {
  AmphionAgc* agc = nullptr;
};

void FinalizeAgc(napi_env, void* data, void*) {
  auto* holder = static_cast<AgcHolder*>(data);
  if (holder == nullptr) return;
  amphion_agc_destroy(holder->agc);
  delete holder;
}

void Throw(napi_env env, const std::string& message) {
  napi_throw_error(env, nullptr, message.c_str());
}

AgcHolder* GetHolder(napi_env env, napi_value value) {
  void* data = nullptr;
  if (napi_get_value_external(env, value, &data) != napi_ok || data == nullptr) {
    throw std::runtime_error("AGC handle is invalid");
  }
  auto* holder = static_cast<AgcHolder*>(data);
  if (holder->agc == nullptr) throw std::runtime_error("AGC handle is closed");
  return holder;
}

float* GetFloat32Array(napi_env env, napi_value value, size_t* length) {
  napi_typedarray_type type;
  size_t native_length = 0;
  void* data = nullptr;
  napi_value buffer = nullptr;
  size_t byte_offset = 0;
  if (napi_get_typedarray_info(env, value, &type, &native_length, &data, &buffer,
                               &byte_offset) != napi_ok || type != napi_float32_array) {
    throw std::runtime_error("AGC samples must be a Float32Array");
  }
  napi_value byte_length_value = nullptr;
  uint32_t byte_length = 0;
  if (napi_get_named_property(env, value, "byteLength", &byte_length_value) != napi_ok ||
      napi_get_value_uint32(env, byte_length_value, &byte_length) != napi_ok ||
      byte_length % sizeof(float) != 0) {
    throw std::runtime_error("AGC samples have an invalid byteLength");
  }
  *length = byte_length / sizeof(float);
  if (native_length != *length && native_length != byte_length) {
    throw std::runtime_error("AGC samples have an inconsistent native length");
  }
  return static_cast<float*>(data);
}

napi_value CreateAgc(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 1;
    napi_value argv[1];
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
    int32_t sample_rate = 0;
    if (argc != 1 || napi_get_value_int32(env, argv[0], &sample_rate) != napi_ok) {
      throw std::runtime_error("sampleRate must be an integer");
    }
    AmphionAgc* agc = amphion_agc_create(sample_rate);
    if (agc == nullptr) throw std::runtime_error("failed to create AGC processor");
    auto* holder = new AgcHolder{agc};
    napi_value result = nullptr;
    if (napi_create_external(env, holder, FinalizeAgc, nullptr, &result) != napi_ok) {
      FinalizeAgc(env, holder, nullptr);
      throw std::runtime_error("failed to create AGC handle");
    }
    return result;
  } catch (const std::exception& error) {
    Throw(env, error.what());
    return nullptr;
  }
}

napi_value ProcessAgc(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 2;
    napi_value argv[2];
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
    if (argc != 2) throw std::runtime_error("processAgc requires handle and samples");
    AgcHolder* holder = GetHolder(env, argv[0]);
    size_t sample_count = 0;
    float* samples = GetFloat32Array(env, argv[1], &sample_count);
    if (amphion_agc_process(holder->agc, samples, sample_count) != 0) {
      throw std::runtime_error("AGC processing failed");
    }
    return argv[1];
  } catch (const std::exception& error) {
    Throw(env, error.what());
    return nullptr;
  }
}

napi_value CloseAgc(napi_env env, napi_callback_info info) {
  try {
    size_t argc = 1;
    napi_value argv[1];
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
    if (argc != 1) throw std::runtime_error("closeAgc requires a handle");
    void* data = nullptr;
    if (napi_get_value_external(env, argv[0], &data) != napi_ok || data == nullptr) {
      throw std::runtime_error("AGC handle is invalid");
    }
    auto* holder = static_cast<AgcHolder*>(data);
    amphion_agc_destroy(holder->agc);
    holder->agc = nullptr;
    napi_value result = nullptr;
    napi_get_undefined(env, &result);
    return result;
  } catch (const std::exception& error) {
    Throw(env, error.what());
    return nullptr;
  }
}

}  // namespace

void RegisterAgcBridge(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"createAgc", nullptr, CreateAgc, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"processAgc", nullptr, ProcessAgc, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"closeAgc", nullptr, CloseAgc, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports,
                         sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
}
