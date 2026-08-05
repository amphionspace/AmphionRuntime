#include <hilog/log.h>
#include <node_api.h>
#include <string>

#include "target_speaker_enhancer.h"

static napi_value NativeVersion(napi_env env, napi_callback_info info) {
  napi_value value;
  napi_create_string_utf8(env, "amphion-harmony-native-0.1.0", NAPI_AUTO_LENGTH, &value);
  return value;
}

static napi_value Probe(napi_env env, napi_callback_info info) {
  OH_LOG_INFO(LOG_APP, "Amphion native probe loaded");
  napi_value value;
  napi_create_string_utf8(env, "ok", NAPI_AUTO_LENGTH, &value);
  return value;
}

EXTERN_C_START
static napi_value Init(napi_env env, napi_value exports) {
  napi_property_descriptor desc[] = {
    {"nativeVersion", nullptr, NativeVersion, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"probe", nullptr, Probe, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
  RegisterTargetSpeakerEnhancer(env, exports);
  return exports;
}
EXTERN_C_END

static napi_module module = {
  .nm_version = 1,
  .nm_flags = 0,
  .nm_filename = nullptr,
  .nm_register_func = Init,
  .nm_modname = "libamphion_asr",
  .nm_priv = nullptr,
  .reserved = {0},
};

extern "C" __attribute__((constructor)) void RegisterModule() {
  napi_module_register(&module);
}
