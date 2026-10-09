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
#include <unistd.h>
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

struct ChainRequest {
  std::vector<std::string> model_paths;
  std::string backend;
  int pace_ms = 640;
  int duration_ms = 60000;
};

struct ChainResult {
  bool ok = false;
  std::string stage;
  std::string device;
  std::string detail;
  int code = 0;
  double build_ms = 0;
  size_t models = 0;
  size_t ticks = 0;
  size_t overruns = 0;
  double elapsed_ms = 0;
  std::vector<double> chain_latencies;
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

std::string RenderChain(const ChainRequest& request, const ChainResult& result) {
  auto number = [](double value) { return std::to_string(value); };
  std::string json = "{\"status\":\"";
  json += result.ok ? "PASS" : "FAIL";
  json += "\",\"kind\":\"chain\"";
  json += ",\"requestedBackend\":\"" + JsonEscape(request.backend) + "\"";
  json += ",\"device\":\"" + JsonEscape(result.device) + "\"";
  json += ",\"models\":" + std::to_string(result.models);
  json += ",\"buildMs\":" + number(result.build_ms);
  json += ",\"paceMs\":" + std::to_string(request.pace_ms);
  if (!result.ok) {
    json += ",\"stage\":\"" + JsonEscape(result.stage) + "\"";
    json += ",\"code\":" + std::to_string(result.code);
    if (!result.detail.empty()) json += ",\"detail\":\"" + JsonEscape(result.detail) + "\"";
    return json + "}";
  }
  std::vector<double> sorted = result.chain_latencies;
  std::sort(sorted.begin(), sorted.end());
  double total = 0;
  for (double value : sorted) total += value;
  json += ",\"ticks\":" + std::to_string(result.ticks);
  json += ",\"overruns\":" + std::to_string(result.overruns);
  json += ",\"elapsedMs\":" + number(result.elapsed_ms);
  if (!sorted.empty()) {
    json += ",\"chainMinMs\":" + number(sorted.front());
    json += ",\"chainMedianMs\":" + number(sorted[sorted.size() / 2]);
    json += ",\"chainMeanMs\":" + number(total / static_cast<double>(sorted.size()));
    json += ",\"chainP95Ms\":" + number(sorted[(sorted.size() * 95) / 100]);
    json += ",\"chainMaxMs\":" + number(sorted.back());
  }
  json += ",\"scope\":\"zero-filled inputs held across ticks; this measures placement, pacing and host CPU cost, never accuracy\"";
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

using ContextDeleter = void (*)(OH_AI_ContextHandle);
using ContextPtr =
  std::unique_ptr<std::remove_pointer<OH_AI_ContextHandle>::type, ContextDeleter>;

void DestroyContext(OH_AI_ContextHandle handle) {
  if (handle) OH_AI_ContextDestroy(&handle);
}

// Builds a context on the requested backend. On success `device` names what was
// selected; on failure `stage`/`detail` say why. Factored out so the single-model
// probe and the paced chain place work identically -- an NNRt context carrying
// only the accelerator, matching the shipped Community encoder.
ContextPtr MakeContext(const std::string& backend, std::string& device, std::string& stage,
                       std::string& detail) {
  ContextPtr context(OH_AI_ContextCreate(), &DestroyContext);
  if (!context) {
    stage = "context";
    return ContextPtr(nullptr, &DestroyContext);
  }
  OH_AI_ContextSetThreadNum(context.get(), 4);
  if (backend != "cpu") {
    auto descs_deleter = [](NNRTDeviceDesc* value) { OH_AI_DestroyAllNNRTDeviceDescs(&value); };
    size_t count = 0;
    std::unique_ptr<NNRTDeviceDesc, decltype(descs_deleter)> descs(
      OH_AI_GetAllNNRTDeviceDescs(&count), descs_deleter);
    const std::string match = Lowercase(backend == "npu" ? "kirin" : backend);
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
      stage = "nnrt-device-absent";
      detail = available;
      return ContextPtr(nullptr, &DestroyContext);
    }
    OH_AI_DeviceInfoHandle info = OH_AI_CreateNNRTDeviceInfoByName(chosen.c_str());
    if (!info) {
      stage = "nnrt-device-info";
      detail = chosen;
      return ContextPtr(nullptr, &DestroyContext);
    }
    OH_AI_DeviceInfoSetPerformanceMode(info, OH_AI_PERFORMANCE_HIGH);
    OH_AI_ContextAddDeviceInfo(context.get(), info);
    device = chosen;
    return context;
  }
  OH_AI_DeviceInfoHandle cpu = OH_AI_DeviceInfoCreate(OH_AI_DEVICETYPE_CPU);
  if (!cpu) {
    stage = "cpu-device-info";
    return ContextPtr(nullptr, &DestroyContext);
  }
  OH_AI_DeviceInfoSetEnableFP16(cpu, true);
  OH_AI_ContextAddDeviceInfo(context.get(), cpu);
  device = "cpu";
  return context;
}

// Runs every model once per tick at a fixed pace for a fixed duration, so a
// long thermal arm can be driven at the real chunk cadence without rebuilding.
void RunChain(const ChainRequest& request, ChainResult& result) {
  if (request.model_paths.empty()) {
    result.stage = "model-paths";
    return;
  }
  std::vector<OH_AI_ModelHandle> models;
  std::vector<OH_AI_TensorHandleArray> inputs;
  const auto build_started = std::chrono::steady_clock::now();
  auto destroy_all = [&models]() {
    for (OH_AI_ModelHandle handle : models) {
      if (handle) OH_AI_ModelDestroy(&handle);
    }
  };
  for (const std::string& path : request.model_paths) {
    std::string stage;
    std::string detail;
    ContextPtr context = MakeContext(request.backend, result.device, stage, detail);
    if (!context) {
      result.stage = stage;
      result.detail = detail;
      destroy_all();
      return;
    }
    OH_AI_ModelHandle model = OH_AI_ModelCreate();
    if (!model) {
      result.stage = "model-create";
      destroy_all();
      return;
    }
    OH_AI_Status status =
      OH_AI_ModelBuildFromFile(model, path.c_str(), OH_AI_MODELTYPE_MINDIR, context.get());
    if (status != OH_AI_STATUS_SUCCESS) {
      result.stage = "build";
      result.code = static_cast<int>(status);
      result.detail = path;
      OH_AI_ModelDestroy(&model);
      destroy_all();
      return;
    }
    context.release();  // The built model owns the context from here on.
    OH_AI_TensorHandleArray in = OH_AI_ModelGetInputs(model);
    for (size_t i = 0; i < in.handle_num; ++i) {
      OH_AI_TensorHandle tensor = in.handle_list ? in.handle_list[i] : nullptr;
      if (!tensor) continue;
      void* data = OH_AI_TensorGetMutableData(tensor);
      if (data) std::memset(data, 0, OH_AI_TensorGetDataSize(tensor));
    }
    models.push_back(model);
    inputs.push_back(in);
  }
  result.models = models.size();
  result.build_ms = MillisSince(build_started);

  const auto run_started = std::chrono::steady_clock::now();
  const double budget = static_cast<double>(std::max(1, request.duration_ms));
  const double pace = static_cast<double>(std::max(1, request.pace_ms));
  while (MillisSince(run_started) < budget) {
    const auto tick_started = std::chrono::steady_clock::now();
    for (size_t i = 0; i < models.size(); ++i) {
      OH_AI_TensorHandleArray outputs = OH_AI_ModelGetOutputs(models[i]);
      OH_AI_Status status =
        OH_AI_ModelPredict(models[i], inputs[i], &outputs, nullptr, nullptr);
      if (status != OH_AI_STATUS_SUCCESS) {
        result.stage = "predict";
        result.code = static_cast<int>(status);
        result.detail = "model " + std::to_string(i) + " tick " + std::to_string(result.ticks);
        destroy_all();
        return;
      }
    }
    const double chain_ms = MillisSince(tick_started);
    result.chain_latencies.push_back(chain_ms);
    ++result.ticks;
    if (chain_ms > pace) {
      ++result.overruns;
    } else {
      const int sleep_us = static_cast<int>((pace - chain_ms) * 1000.0);
      if (sleep_us > 0) usleep(static_cast<useconds_t>(sleep_us));
    }
  }
  result.elapsed_ms = MillisSince(run_started);
  destroy_all();
  result.ok = true;
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
void RunChain(const ChainRequest&, ChainResult& result) { result.stage = "unsupported-platform"; }
#endif

struct ChainTask {
  ChainRequest request;
  ChainResult result;
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
};

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

napi_value ProbeMindSporeChain(napi_env env, napi_callback_info info) {
  size_t count = 4;
  napi_value argv[4];
  napi_get_cb_info(env, info, &count, argv, nullptr, nullptr);
  auto task = std::make_unique<ChainTask>();
  if (count >= 1) {
    // One comma-separated list keeps the ArkTS surface to plain strings and
    // numbers, which is all the diagnostics carrier needs to pass through.
    const std::string joined = StringArgument(env, argv[0]);
    size_t from = 0;
    while (from <= joined.size()) {
      const size_t at = joined.find(',', from);
      const std::string piece = joined.substr(from, at == std::string::npos ? std::string::npos : at - from);
      if (!piece.empty()) task->request.model_paths.push_back(piece);
      if (at == std::string::npos) break;
      from = at + 1;
    }
  }
  task->request.backend = count >= 2 ? StringArgument(env, argv[1]) : "cpu";
  if (task->request.backend.empty()) task->request.backend = "cpu";
  if (count >= 3) {
    int32_t pace = 640;
    if (napi_get_value_int32(env, argv[2], &pace) == napi_ok) task->request.pace_ms = pace;
  }
  if (count >= 4) {
    int32_t duration = 60000;
    if (napi_get_value_int32(env, argv[3], &duration) == napi_ok) task->request.duration_ms = duration;
  }

  napi_value promise = nullptr;
  if (napi_create_promise(env, &task->deferred, &promise) != napi_ok) return nullptr;
  napi_value name;
  napi_create_string_utf8(env, "probeMindSporeChain", NAPI_AUTO_LENGTH, &name);
  ChainTask* raw = task.release();
  napi_create_async_work(
    env, nullptr, name,
    [](napi_env, void* data) {
      auto* item = static_cast<ChainTask*>(data);
      RunChain(item->request, item->result);
    },
    [](napi_env env, napi_status, void* data) {
      std::unique_ptr<ChainTask> item(static_cast<ChainTask*>(data));
      napi_value value;
      const std::string json = RenderChain(item->request, item->result);
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
    {"probeMindSporeChain", nullptr, ProbeMindSporeChain, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
}
