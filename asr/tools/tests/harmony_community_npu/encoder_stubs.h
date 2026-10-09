#pragma once
#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// Mirror standalone CLT signatures; the optional mode checks against the real
// headers without linking any platform libraries.
#ifdef COMMUNITY_CLT_HEADERS
#include <mindspore/context.h>
#include <mindspore/model.h>
#include <mindspore/tensor.h>
#else
using OH_AI_ContextHandle = void*;
using OH_AI_DeviceInfoHandle = void*;
using OH_AI_ModelHandle = void*;
using OH_AI_TensorHandle = void*;
enum OH_AI_NNRTDeviceType { OH_AI_NNRTDEVICE_CPU = 1, OH_AI_NNRTDEVICE_GPU = 2,
                           OH_AI_NNRTDEVICE_ACCELERATOR = 3 };
enum OH_AI_PerformanceMode { OH_AI_PERFORMANCE_HIGH = 3 };
enum OH_AI_ModelType { OH_AI_MODELTYPE_MINDIR = 0 };
enum OH_AI_Status { OH_AI_STATUS_SUCCESS = 0, OH_AI_STATUS_LITE_ERROR = -1 };
enum OH_AI_DataType { OH_AI_DATATYPE_NUMBERTYPE_FLOAT16 = 42,
                     OH_AI_DATATYPE_NUMBERTYPE_FLOAT32 = 43 };
struct OH_AI_TensorHandleArray { size_t handle_num; OH_AI_TensorHandle* handle_list; };
struct OH_AI_CallBackParam { char* node_name; char* node_type; };
using OH_AI_KernelCallBack = bool (*)(OH_AI_TensorHandleArray, OH_AI_TensorHandleArray, OH_AI_CallBackParam);
#endif

inline void Check(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}
struct NNRTDeviceDesc {
  std::string name;
  OH_AI_NNRTDeviceType type = OH_AI_NNRTDEVICE_ACCELERATOR;
  bool null_name = false, null_desc = false;
};
struct StubTensor {
  std::vector<int64_t> shape;
  OH_AI_DataType dtype = OH_AI_DATATYPE_NUMBERTYPE_FLOAT32;
  int64_t count = 0;
  size_t bytes = 0;
  std::vector<float> owned;
  void* borrowed = nullptr;
  bool null_shape = false, null_data = false;
};
struct StubDevice { std::string name; bool attached = false; };
struct StubContext { StubDevice* device = nullptr; };
struct StubModel {
  StubTensor input, output;
  OH_AI_TensorHandle inputs[2] = {}, outputs[2] = {};
};
inline struct StubState {
  std::vector<NNRTDeviceDesc> devices{{"Kirin990"}};
  std::vector<StubModel*> models;
  std::string fail, input_fault, output_fault, predict_fault, built_name;
  bool null_descs = false;
  int live_descs = 0, live_contexts = 0, live_devices = 0, live_models = 0;
  int desc_frees = 0, context_frees = 0, device_frees = 0, model_frees = 0;
  int set_data_calls = 0, caller_free_attempts = 0, mutable_calls = 0, invalid_calls = 0;
  int predict_calls = 0, data_reads = 0, cpu_builds = 0, cpu_runs = 0, fp16_calls = 0;
  void* input_address = nullptr;
  const void* output_address = nullptr;
  std::vector<std::string> log_formats;
} state;
inline void ValidHandle(const void* handle) {
  if (!handle) { ++state.invalid_calls; throw std::runtime_error("CAPI called with null handle"); }
}
inline void Configure(StubTensor& tensor, bool input, const std::string& fault) {
  tensor.shape = input ? std::vector<int64_t>{1, 998, 80} : std::vector<int64_t>{1, 2560, 125};
  tensor.count = input ? 998 * 80 : 2560 * 125;
  tensor.bytes = tensor.count * sizeof(float);
  tensor.dtype = OH_AI_DATATYPE_NUMBERTYPE_FLOAT32;
  tensor.null_shape = fault == "null-shape";
  tensor.null_data = fault == "null-data";
  if (fault == "dtype") tensor.dtype = OH_AI_DATATYPE_NUMBERTYPE_FLOAT16;
  if (fault == "shape") std::swap(tensor.shape[1], tensor.shape[2]); // Same element count.
  if (fault == "rank") tensor.shape = {tensor.count};
  if (fault == "dynamic") tensor.shape[1] = -1;
  if (fault == "count") --tensor.count;
  if (fault == "bytes") tensor.bytes /= 2;
  if (fault == "oversized-bytes") tensor.bytes += sizeof(float);
}
inline OH_AI_TensorHandleArray Handles(StubModel& model, bool input, const std::string& fault) {
  auto& tensor = input ? model.input : model.output;
  auto* list = input ? model.inputs : model.outputs;
  Configure(tensor, input, fault);
  list[0] = fault == "null-handle" ? nullptr : &tensor;
  list[1] = &tensor;
  return {fault == "zero-tensors" ? 0u : fault == "extra-tensor" ? 2u : 1u,
          fault == "null-list" ? nullptr : list};
}
inline void ResourcesReleased() {
  Check(state.live_descs == 0 && state.live_contexts == 0 && state.live_devices == 0 && state.live_models == 0,
        "resources still live: descs=" + std::to_string(state.live_descs) +
        " context=" + std::to_string(state.live_contexts) + " device=" + std::to_string(state.live_devices) +
        " model=" + std::to_string(state.live_models));
  Check(state.caller_free_attempts == 0, "runtime attempted to free caller buffer");
  Check(state.invalid_calls == 0, "production called CAPI with a null handle/list");
}

extern "C" {
inline NNRTDeviceDesc* OH_AI_GetAllNNRTDeviceDescs(size_t* count) {
  *count = state.null_descs ? 2 : state.devices.size();
  if (state.null_descs) return nullptr;
  auto* descs = new NNRTDeviceDesc[state.devices.size()];
  std::copy(state.devices.begin(), state.devices.end(), descs);
  ++state.live_descs; return descs;
}
inline NNRTDeviceDesc* OH_AI_GetElementOfNNRTDeviceDescs(NNRTDeviceDesc* descs, size_t i) {
  ValidHandle(descs);
  if (state.fail == "enumerate") throw std::bad_alloc();
  return descs[i].null_desc ? nullptr : descs + i;
}
inline const char* OH_AI_GetNameFromNNRTDeviceDesc(const NNRTDeviceDesc* desc) {
  return desc->null_name ? nullptr : desc->name.c_str();
}
inline OH_AI_NNRTDeviceType OH_AI_GetTypeFromNNRTDeviceDesc(const NNRTDeviceDesc* desc) { return desc->type; }
inline void OH_AI_DestroyAllNNRTDeviceDescs(NNRTDeviceDesc** descs) {
  delete[] *descs; *descs = nullptr; --state.live_descs; ++state.desc_frees;
}
inline OH_AI_ContextHandle OH_AI_ContextCreate() {
  if (state.fail == "context") return nullptr;
  ++state.live_contexts; return new StubContext;
}
inline OH_AI_DeviceInfoHandle OH_AI_CreateNNRTDeviceInfoByName(const char* name) {
  if (state.fail == "device") return nullptr;
  ++state.live_devices; return new StubDevice{name};
}
inline void OH_AI_DeviceInfoDestroy(OH_AI_DeviceInfoHandle* handle) {
  auto* device = static_cast<StubDevice*>(*handle);
  Check(!device->attached, "device destroyed outside its owning context");
  delete device; *handle = nullptr; --state.live_devices; ++state.device_frees;
}
inline void OH_AI_DeviceInfoSetEnableFP16(OH_AI_DeviceInfoHandle, bool) { ++state.fp16_calls; }
inline void OH_AI_DeviceInfoSetPerformanceMode(OH_AI_DeviceInfoHandle, OH_AI_PerformanceMode mode) {
  Check(mode == OH_AI_PERFORMANCE_HIGH, "wrong performance request");
  if (state.fail == "performance") throw std::bad_alloc();
}
inline void OH_AI_ContextAddDeviceInfo(OH_AI_ContextHandle context, OH_AI_DeviceInfoHandle handle) {
  if (state.fail == "attach") throw std::bad_alloc();
  auto* device = static_cast<StubDevice*>(handle);
  device->attached = true; static_cast<StubContext*>(context)->device = device;
}
inline void OH_AI_ContextDestroy(OH_AI_ContextHandle* handle) {
  auto* context = static_cast<StubContext*>(*handle);
  if (context->device) {
    context->device->attached = false;
    OH_AI_DeviceInfoHandle device = context->device; OH_AI_DeviceInfoDestroy(&device);
  }
  delete context; *handle = nullptr; --state.live_contexts; ++state.context_frees;
}
inline OH_AI_ModelHandle OH_AI_ModelCreate() {
  if (state.fail == "model") return nullptr;
  auto* model = new StubModel; state.models.push_back(model); ++state.live_models; return model;
}
inline void OH_AI_ModelDestroy(OH_AI_ModelHandle* handle) {
  auto* model = static_cast<StubModel*>(*handle);
  if (model->input.borrowed) ++state.caller_free_attempts;
  state.models.erase(std::find(state.models.begin(), state.models.end(), model));
  delete model; *handle = nullptr; --state.live_models; ++state.model_frees;
}
inline OH_AI_Status OH_AI_ModelBuild(OH_AI_ModelHandle, const void* bytes, size_t size,
                                    OH_AI_ModelType type, const OH_AI_ContextHandle handle) {
  Check(bytes && size && type == OH_AI_MODELTYPE_MINDIR, "invalid MindIR build input");
  state.built_name = static_cast<StubContext*>(handle)->device->name;
  return state.fail == "build" ? OH_AI_STATUS_LITE_ERROR : OH_AI_STATUS_SUCCESS;
}
inline OH_AI_TensorHandleArray OH_AI_ModelGetInputs(const OH_AI_ModelHandle handle) {
  return Handles(*static_cast<StubModel*>(handle), true, state.input_fault);
}
inline OH_AI_TensorHandleArray OH_AI_ModelGetOutputs(const OH_AI_ModelHandle handle) {
  return Handles(*static_cast<StubModel*>(handle), false, state.output_fault);
}
inline OH_AI_DataType OH_AI_TensorGetDataType(const OH_AI_TensorHandle handle) {
  ValidHandle(handle); return static_cast<StubTensor*>(handle)->dtype;
}
inline const int64_t* OH_AI_TensorGetShape(const OH_AI_TensorHandle handle, size_t* rank) {
  ValidHandle(handle); auto& tensor = *static_cast<StubTensor*>(handle);
  *rank = tensor.shape.size(); return tensor.null_shape ? nullptr : tensor.shape.data();
}
inline int64_t OH_AI_TensorGetElementNum(const OH_AI_TensorHandle handle) {
  ValidHandle(handle); return static_cast<StubTensor*>(handle)->count;
}
inline size_t OH_AI_TensorGetDataSize(const OH_AI_TensorHandle handle) {
  ValidHandle(handle); return static_cast<StubTensor*>(handle)->bytes;
}
inline void OH_AI_TensorSetData(OH_AI_TensorHandle handle, void* data) {
  ValidHandle(handle); ++state.set_data_calls; static_cast<StubTensor*>(handle)->borrowed = data;
}
inline void* OH_AI_TensorGetMutableData(const OH_AI_TensorHandle handle) {
  ValidHandle(handle); ++state.mutable_calls; auto& tensor = *static_cast<StubTensor*>(handle);
  if (tensor.null_data) return nullptr;
  if (tensor.owned.empty()) tensor.owned.resize(998 * 80);
  return tensor.borrowed ? tensor.borrowed : tensor.owned.data();
}
inline const void* OH_AI_TensorGetData(const OH_AI_TensorHandle handle) {
  ++state.data_reads; ValidHandle(handle); auto& tensor = *static_cast<StubTensor*>(handle);
  return tensor.null_data ? nullptr : tensor.borrowed ? tensor.borrowed : tensor.owned.data();
}
inline OH_AI_Status OH_AI_ModelPredict(OH_AI_ModelHandle handle, const OH_AI_TensorHandleArray inputs,
                                      OH_AI_TensorHandleArray* outputs, const OH_AI_KernelCallBack,
                                      const OH_AI_KernelCallBack) {
  ++state.predict_calls;
  if (state.fail == "predict") return OH_AI_STATUS_LITE_ERROR;
  auto& input = *static_cast<StubTensor*>(inputs.handle_list[0]);
  auto* data = input.borrowed ? static_cast<float*>(input.borrowed) : input.owned.data();
  Check(data != nullptr, "predict called without input data"); state.input_address = data;
  auto& model = *static_cast<StubModel*>(handle);
  *outputs = Handles(model, false, state.predict_fault);
  model.output.owned.resize(2560 * 125);
  for (size_t i = 0; i < model.output.owned.size(); ++i)
    model.output.owned[i] = data[i % (998 * 80)] + static_cast<float>(i % 251) / 1024.f;
  if (state.predict_fault == "nan") model.output.owned.back() = std::numeric_limits<float>::quiet_NaN();
  if (state.predict_fault == "inf") model.output.owned.back() = std::numeric_limits<float>::infinity();
  state.output_address = model.output.owned.data(); return OH_AI_STATUS_SUCCESS;
}
}

constexpr int LOG_APP = 0, LOG_INFO = 1, LOG_WARN = 2;
inline int OH_LOG_Print(int, int, unsigned int, const char*, const char* format, ...) {
  state.log_formats.emplace_back(format); return 0;
}
constexpr int OrtArenaAllocator = 0, OrtMemTypeDefault = 0;
namespace Ort {
struct Env {};
struct SessionOptions {};
struct RunOptions { explicit RunOptions(std::nullptr_t) {} };
struct MemoryInfo { static int CreateCpu(int, int) { return 0; } };
struct Value {
  std::vector<float> values;
  template<class T> static Value CreateTensor(int, T* data, size_t n, const int64_t*, size_t) {
    return {std::vector<float>(data, data + n)};
  }
  struct Info { size_t count; size_t GetElementCount() const { return count; } };
  Info GetTensorTypeAndShapeInfo() const { return {values.size()}; }
  template<class T> const T* GetTensorData() const { return values.data(); }
};
struct Session {
  bool loaded = false;
  explicit Session(std::nullptr_t) {}
  Session(Env&, const void*, size_t, const SessionOptions&) : loaded(true) { ++state.cpu_builds; }
  std::vector<Value> Run(RunOptions, const char**, Value* inputs, size_t, const char**, size_t) {
    Check(loaded, "run on unloaded CPU session"); ++state.cpu_runs;
    return {{std::vector<float>(2560 * 125, inputs[0].values[0])}};
  }
};
}
