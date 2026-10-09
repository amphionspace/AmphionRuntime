// Diagnostics-only MindSpore Lite backend probe.
//
// It answers one question before any engine work is attempted: does this
// device's NNRt accelerator accept a given MindIR graph, and what does one
// Predict cost there versus the CPU? Nothing in the recognition or diarization
// path calls this; it loads a caller-supplied model, feeds zeros, and reports
// timings. Zero inputs make the timings valid and the outputs meaningless, so
// this is a placement and latency probe, never an accuracy check.
#include <node_api.h>

#include <algorithm>
#include <chrono>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#ifndef __ANDROID__
#include <mindspore/context.h>
#include <mindspore/model.h>
#include <mindspore/status.h>
#include <mindspore/tensor.h>
#endif

namespace {

struct ProbeRequest {
  std::string model_path;
  std::string backend;
  int iterations = 3;
};

struct ProbeResult {
  bool ok = false;
  std::string stage;
  std::string device;
  std::string detail;
  int code = 0;
  double build_ms = 0;
  std::vector<double> latencies;
  size_t inputs = 0;
  size_t outputs = 0;
  size_t input_bytes = 0;
};

std::string JsonEscape(const std::string& value) {
  std::string out;
  for (char c : value) {
    if (c == '"' || c == '\\') {
      out += '\\';
      out += c;
    } else if (static_cast<unsigned char>(c) >= 0x20) {
      out += c;
    }
  }
  return out;
}

std::string Render(const ProbeRequest& request, const ProbeResult& result) {
  auto number = [](double value) {
    std::string text = std::to_string(value);
    return text;
  };
  std::string json = "{\"status\":\"";
  json += result.ok ? "PASS" : "FAIL";
  json += "\",\"requestedBackend\":\"" + JsonEscape(request.backend) + "\"";
  json += ",\"device\":\"" + JsonEscape(result.device) + "\"";
  json += ",\"buildMs\":" + number(result.build_ms);
  if (!result.ok) {
    json += ",\"stage\":\"" + JsonEscape(result.stage) + "\"";
    json += ",\"code\":" + std::to_string(result.code);
    if (!result.detail.empty()) json += ",\"detail\":\"" + JsonEscape(result.detail) + "\"";
    return json + "}";
  }
  std::vector<double> sorted = result.latencies;
  std::sort(sorted.begin(), sorted.end());
  double total = 0;
  for (double value : sorted) total += value;
  json += ",\"iterations\":" + std::to_string(sorted.size());
  json += ",\"minMs\":" + number(sorted.front());
  json += ",\"medianMs\":" + number(sorted[sorted.size() / 2]);
  json += ",\"meanMs\":" + number(total / static_cast<double>(sorted.size()));
  json += ",\"maxMs\":" + number(sorted.back());
  json += ",\"modelInputs\":" + std::to_string(result.inputs);
  json += ",\"modelOutputs\":" + std::to_string(result.outputs);
  json += ",\"inputBytes\":" + std::to_string(result.input_bytes);
  json += ",\"scope\":\"zero-filled inputs; latency and backend acceptance only, not accuracy\"";
  return json + "}";
}

#ifndef __ANDROID__
double MillisSince(std::chrono::steady_clock::time_point start) {
  return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
}

std::string Lowercase(std::string value) {
  for (char& c : value) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  return value;
}

void RunProbe(const ProbeRequest& request, ProbeResult& result) {
  if (request.model_path.empty()) {
    result.stage = "model-path";
    return;
  }
  auto context_deleter = [](OH_AI_ContextHandle handle) {
    if (handle) OH_AI_ContextDestroy(&handle);
  };
  std::unique_ptr<std::remove_pointer<OH_AI_ContextHandle>::type, decltype(context_deleter)> context(
    OH_AI_ContextCreate(), context_deleter);
  if (!context) {
    result.stage = "context";
    return;
  }
  OH_AI_ContextSetThreadNum(context.get(), 4);

  if (request.backend != "cpu") {
    auto descs_deleter = [](NNRTDeviceDesc* value) { OH_AI_DestroyAllNNRTDeviceDescs(&value); };
    size_t count = 0;
    std::unique_ptr<NNRTDeviceDesc, decltype(descs_deleter)> descs(
      OH_AI_GetAllNNRTDeviceDescs(&count), descs_deleter);
    const std::string match = Lowercase(request.backend == "npu" ? "kirin" : request.backend);
    std::string chosen;
    std::string available;
    for (size_t i = 0; descs && i < count; ++i) {
      NNRTDeviceDesc* desc = OH_AI_GetElementOfNNRTDeviceDescs(descs.get(), i);
      if (!desc) continue;
      const char* name = OH_AI_GetNameFromNNRTDeviceDesc(desc);
      if (!name) continue;
      if (!available.empty()) available += ",";
      available += name;
      if (chosen.empty() && OH_AI_GetTypeFromNNRTDeviceDesc(desc) == OH_AI_NNRTDEVICE_ACCELERATOR &&
          Lowercase(name).find(match) != std::string::npos) {
        chosen = name;
      }
    }
    if (chosen.empty()) {
      result.stage = "nnrt-device-absent";
      result.detail = available;
      return;
    }
    OH_AI_DeviceInfoHandle device = OH_AI_CreateNNRTDeviceInfoByName(chosen.c_str());
    if (!device) {
      result.stage = "nnrt-device-info";
      result.detail = chosen;
      return;
    }
    OH_AI_DeviceInfoSetPerformanceMode(device, OH_AI_PERFORMANCE_HIGH);
    OH_AI_ContextAddDeviceInfo(context.get(), device);
    result.device = chosen;
  }
  if (result.device.empty()) {
    // An NNRt context carries only the accelerator, exactly as the shipped
    // Community encoder does: adding a CPU device beside it makes Predict fail,
    // and a silent CPU placement would make the measurement meaningless.
    OH_AI_DeviceInfoHandle cpu = OH_AI_DeviceInfoCreate(OH_AI_DEVICETYPE_CPU);
    if (!cpu) {
      result.stage = "cpu-device-info";
      return;
    }
    OH_AI_DeviceInfoSetEnableFP16(cpu, true);
    OH_AI_ContextAddDeviceInfo(context.get(), cpu);
    result.device = "cpu";
  }

  OH_AI_ModelHandle model = OH_AI_ModelCreate();
  if (!model) {
    result.stage = "model-create";
    return;
  }
  const auto build_started = std::chrono::steady_clock::now();
  OH_AI_Status status =
    OH_AI_ModelBuildFromFile(model, request.model_path.c_str(), OH_AI_MODELTYPE_MINDIR, context.get());
  result.build_ms = MillisSince(build_started);
  if (status != OH_AI_STATUS_SUCCESS) {
    result.stage = "build";
    result.code = static_cast<int>(status);
    OH_AI_ModelDestroy(&model);
    return;
  }
  context.release();  // The built model owns the context from here on.

  OH_AI_TensorHandleArray inputs = OH_AI_ModelGetInputs(model);
  result.inputs = inputs.handle_num;
  for (size_t i = 0; i < inputs.handle_num; ++i) {
    OH_AI_TensorHandle tensor = inputs.handle_list ? inputs.handle_list[i] : nullptr;
    if (!tensor) continue;
    const size_t bytes = OH_AI_TensorGetDataSize(tensor);
    result.input_bytes += bytes;
    void* data = OH_AI_TensorGetMutableData(tensor);
    if (data) std::memset(data, 0, bytes);
  }

  for (int iteration = 0; iteration < std::max(1, request.iterations); ++iteration) {
    // NNRt needs the model's own output tensors; an empty array fails there.
    OH_AI_TensorHandleArray outputs = OH_AI_ModelGetOutputs(model);
    const auto started = std::chrono::steady_clock::now();
    status = OH_AI_ModelPredict(model, inputs, &outputs, nullptr, nullptr);
    const double elapsed = MillisSince(started);
    if (status != OH_AI_STATUS_SUCCESS) {
      result.stage = "predict";
      result.code = static_cast<int>(status);
      result.detail = "iteration " + std::to_string(iteration);
      OH_AI_ModelDestroy(&model);
      return;
    }
    result.latencies.push_back(elapsed);
    result.outputs = outputs.handle_num;
  }
  OH_AI_ModelDestroy(&model);
  result.ok = true;
}
#else
void RunProbe(const ProbeRequest&, ProbeResult& result) { result.stage = "unsupported-platform"; }
#endif

struct ProbeTask {
  ProbeRequest request;
  ProbeResult result;
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
};

std::string StringArgument(napi_env env, napi_value value) {
  size_t length = 0;
  if (napi_get_value_string_utf8(env, value, nullptr, 0, &length) != napi_ok) return std::string();
  std::string text(length, '\0');
  size_t written = 0;
  if (napi_get_value_string_utf8(env, value, text.data(), length + 1, &written) != napi_ok) {
    return std::string();
  }
  text.resize(written);
  return text;
}

napi_value ProbeMindSporeModel(napi_env env, napi_callback_info info) {
  size_t count = 3;
  napi_value argv[3];
  napi_get_cb_info(env, info, &count, argv, nullptr, nullptr);
  auto task = std::make_unique<ProbeTask>();
  if (count >= 1) task->request.model_path = StringArgument(env, argv[0]);
  task->request.backend = count >= 2 ? StringArgument(env, argv[1]) : "cpu";
  if (task->request.backend.empty()) task->request.backend = "cpu";
  if (count >= 3) {
    int32_t iterations = 3;
    if (napi_get_value_int32(env, argv[2], &iterations) == napi_ok) task->request.iterations = iterations;
  }

  napi_value promise = nullptr;
  if (napi_create_promise(env, &task->deferred, &promise) != napi_ok) return nullptr;
  napi_value name;
  napi_create_string_utf8(env, "probeMindSporeModel", NAPI_AUTO_LENGTH, &name);
  ProbeTask* raw = task.release();
  napi_create_async_work(
    env, nullptr, name,
    [](napi_env, void* data) {
      auto* item = static_cast<ProbeTask*>(data);
      RunProbe(item->request, item->result);
    },
    [](napi_env env, napi_status, void* data) {
      std::unique_ptr<ProbeTask> item(static_cast<ProbeTask*>(data));
      napi_value value;
      const std::string json = Render(item->request, item->result);
      napi_create_string_utf8(env, json.c_str(), NAPI_AUTO_LENGTH, &value);
      napi_resolve_deferred(env, item->deferred, value);
      napi_delete_async_work(env, item->work);
    },
    raw, &raw->work);
  napi_queue_async_work(env, raw->work);
  return promise;
}

}  // namespace

void RegisterMindSporeProbe(napi_env env, napi_value exports) {
  napi_property_descriptor desc[] = {
    {"probeMindSporeModel", nullptr, ProbeMindSporeModel, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
}
