// Diagnostics-only ONNX Runtime probe.
//
// It exists to supply the one number the MindSpore Lite probes cannot: what the
// delivered INT8 encoder actually costs on the CPU path the product ships. The
// MindSpore Lite CPU backend runs an fp16 graph, which is not the same baseline,
// so comparing an accelerator against it overstates the saving. This loads a
// caller-supplied ONNX file with the same runtime and thread count the engine
// uses, feeds zeros, and reports timings. Zero inputs make the timings valid and
// the outputs meaningless; this is never an accuracy check, and nothing in the
// recognition or diarization path calls it.
#include "onnxruntime_cxx_api.h"

#include <node_api.h>

#include <algorithm>
#include <chrono>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace {

struct OrtProbeRequest {
  std::string model_path;
  int threads = 4;
  int iterations = 3;
};

struct OrtProbeResult {
  bool ok = false;
  std::string stage;
  std::string detail;
  double load_ms = 0;
  size_t inputs = 0;
  size_t outputs = 0;
  size_t input_bytes = 0;
  std::vector<double> latencies;
};

std::string OrtJsonEscape(const std::string& value) {
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

double OrtMillisSince(std::chrono::steady_clock::time_point start) {
  return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
}

std::string RenderOrt(const OrtProbeRequest& request, const OrtProbeResult& result) {
  auto number = [](double value) { return std::to_string(value); };
  std::string json = "{\"status\":\"";
  json += result.ok ? "PASS" : "FAIL";
  json += "\",\"runtime\":\"onnxruntime\"";
  json += ",\"threads\":" + std::to_string(request.threads);
  json += ",\"loadMs\":" + number(result.load_ms);
  if (!result.ok) {
    json += ",\"stage\":\"" + OrtJsonEscape(result.stage) + "\"";
    if (!result.detail.empty()) json += ",\"detail\":\"" + OrtJsonEscape(result.detail) + "\"";
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
  json += ",\"p95Ms\":" + number(sorted[(sorted.size() * 95) / 100]);
  json += ",\"maxMs\":" + number(sorted.back());
  json += ",\"modelInputs\":" + std::to_string(result.inputs);
  json += ",\"modelOutputs\":" + std::to_string(result.outputs);
  json += ",\"inputBytes\":" + std::to_string(result.input_bytes);
  json += ",\"scope\":\"zero-filled inputs; latency and host CPU cost only, not accuracy\"";
  return json + "}";
}

size_t ElementSize(ONNXTensorElementDataType type) {
  switch (type) {
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT: return 4;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64: return 8;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32: return 4;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL: return 1;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16: return 2;
    default: return 0;
  }
}

void RunOrtProbe(const OrtProbeRequest& request, OrtProbeResult& result) {
  if (request.model_path.empty()) {
    result.stage = "model-path";
    return;
  }
  try {
    Ort::Env env(ORT_LOGGING_LEVEL_ERROR, "amphion-ort-probe");
    Ort::SessionOptions options;
    options.SetIntraOpNumThreads(std::max(1, request.threads));
    options.SetInterOpNumThreads(1);
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    const auto load_started = std::chrono::steady_clock::now();
    Ort::Session session(env, request.model_path.c_str(), options);
    result.load_ms = OrtMillisSince(load_started);

    Ort::AllocatorWithDefaultOptions allocator;
    const size_t input_count = session.GetInputCount();
    const size_t output_count = session.GetOutputCount();
    result.inputs = input_count;
    result.outputs = output_count;

    std::vector<std::string> input_names_owned;
    std::vector<std::string> output_names_owned;
    for (size_t i = 0; i < input_count; ++i) {
      input_names_owned.push_back(session.GetInputNameAllocated(i, allocator).get());
    }
    for (size_t i = 0; i < output_count; ++i) {
      output_names_owned.push_back(session.GetOutputNameAllocated(i, allocator).get());
    }
    std::vector<const char*> input_names;
    std::vector<const char*> output_names;
    for (const std::string& name : input_names_owned) input_names.push_back(name.c_str());
    for (const std::string& name : output_names_owned) output_names.push_back(name.c_str());

    // Zero-filled inputs at the model's own static shapes. A dimension the model
    // leaves symbolic is pinned to 1, which is what the streaming engine feeds.
    Ort::MemoryInfo memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    std::vector<std::vector<int64_t>> shapes(input_count);
    std::vector<std::vector<uint8_t>> buffers(input_count);
    std::vector<Ort::Value> inputs;
    inputs.reserve(input_count);
    for (size_t i = 0; i < input_count; ++i) {
      Ort::TypeInfo info = session.GetInputTypeInfo(i);
      auto tensor_info = info.GetTensorTypeAndShapeInfo();
      const ONNXTensorElementDataType type = tensor_info.GetElementType();
      const size_t element = ElementSize(type);
      if (element == 0) {
        result.stage = "input-dtype";
        result.detail = input_names_owned[i];
        return;
      }
      shapes[i] = tensor_info.GetShape();
      size_t count = 1;
      for (int64_t& dim : shapes[i]) {
        if (dim <= 0) dim = 1;
        count *= static_cast<size_t>(dim);
      }
      buffers[i].assign(count * element, 0);
      result.input_bytes += buffers[i].size();
      inputs.push_back(Ort::Value::CreateTensor(memory, buffers[i].data(), buffers[i].size(),
                                                shapes[i].data(), shapes[i].size(), type));
    }

    for (int iteration = 0; iteration < std::max(1, request.iterations); ++iteration) {
      const auto started = std::chrono::steady_clock::now();
      std::vector<Ort::Value> outputs =
        session.Run(Ort::RunOptions{nullptr}, input_names.data(), inputs.data(), inputs.size(),
                    output_names.data(), output_names.size());
      result.latencies.push_back(OrtMillisSince(started));
      if (outputs.size() != output_count) {
        result.stage = "output-count";
        return;
      }
    }
    result.ok = true;
  } catch (const Ort::Exception& error) {
    result.stage = "onnxruntime";
    result.detail = error.what();
  } catch (const std::exception& error) {
    result.stage = "exception";
    result.detail = error.what();
  }
}

struct OrtProbeTask {
  OrtProbeRequest request;
  OrtProbeResult result;
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
};

std::string OrtStringArgument(napi_env env, napi_value value) {
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

napi_value ProbeOrtModel(napi_env env, napi_callback_info info) {
  size_t count = 3;
  napi_value argv[3];
  napi_get_cb_info(env, info, &count, argv, nullptr, nullptr);
  auto task = std::make_unique<OrtProbeTask>();
  if (count >= 1) task->request.model_path = OrtStringArgument(env, argv[0]);
  if (count >= 2) {
    int32_t threads = 4;
    if (napi_get_value_int32(env, argv[1], &threads) == napi_ok) task->request.threads = threads;
  }
  if (count >= 3) {
    int32_t iterations = 3;
    if (napi_get_value_int32(env, argv[2], &iterations) == napi_ok) task->request.iterations = iterations;
  }

  napi_value promise = nullptr;
  if (napi_create_promise(env, &task->deferred, &promise) != napi_ok) return nullptr;
  napi_value name;
  napi_create_string_utf8(env, "probeOrtModel", NAPI_AUTO_LENGTH, &name);
  OrtProbeTask* raw = task.release();
  napi_create_async_work(
    env, nullptr, name,
    [](napi_env, void* data) {
      auto* item = static_cast<OrtProbeTask*>(data);
      RunOrtProbe(item->request, item->result);
    },
    [](napi_env env, napi_status, void* data) {
      std::unique_ptr<OrtProbeTask> item(static_cast<OrtProbeTask*>(data));
      napi_value value;
      const std::string json = RenderOrt(item->request, item->result);
      napi_create_string_utf8(env, json.c_str(), NAPI_AUTO_LENGTH, &value);
      napi_resolve_deferred(env, item->deferred, value);
      napi_delete_async_work(env, item->work);
    },
    raw, &raw->work);
  napi_queue_async_work(env, raw->work);
  return promise;
}

}  // namespace

void RegisterOrtProbe(napi_env env, napi_value exports) {
  napi_property_descriptor desc[] = {
    {"probeOrtModel", nullptr, ProbeOrtModel, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
}
