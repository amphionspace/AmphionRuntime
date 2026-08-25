#include "speaker_turn_segmenter.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace {

constexpr int64_t kWindowSamples = 160000;
constexpr int64_t kFrames = 589;
constexpr int64_t kClasses = 7;
constexpr int32_t kReceptiveFieldSize = 991;
constexpr int32_t kReceptiveFieldShift = 270;

// pyannote segmentation-3.0 powerset order:
// empty, S0, S1, S2, S0+S1, S0+S2, S1+S2.
constexpr int32_t ClassToSpeakerMask(int32_t klass) {
  constexpr std::array<int32_t, kClasses> kMasks{0, 1, 2, 4, 3, 5, 6};
  return klass >= 0 && klass < kClasses ? kMasks[klass] : 0;
}

constexpr int32_t PrimarySpeaker(int32_t speaker_mask) {
  if ((speaker_mask & 1) != 0) return 0;
  if ((speaker_mask & 2) != 0) return 1;
  if ((speaker_mask & 4) != 0) return 2;
  return -1;
}

template <typename T>
std::vector<T> CopyTypedArray(napi_env env, napi_value value,
                              napi_typedarray_type expected) {
  napi_typedarray_type actual;
  size_t length = 0;
  void* data = nullptr;
  napi_value buffer = nullptr;
  size_t byte_offset = 0;
  if (napi_get_typedarray_info(env, value, &actual, &length, &data, &buffer,
                               &byte_offset) != napi_ok || actual != expected) {
    throw std::runtime_error("invalid typed array");
  }
  napi_value byte_length_value = nullptr;
  uint32_t byte_length = 0;
  if (napi_get_named_property(env, value, "byteLength", &byte_length_value) != napi_ok ||
      napi_get_value_uint32(env, byte_length_value, &byte_length) != napi_ok ||
      byte_length % sizeof(T) != 0) {
    throw std::runtime_error("invalid typed array byteLength");
  }
  return std::vector<T>(static_cast<T*>(data),
                        static_cast<T*>(data) + byte_length / sizeof(T));
}

class SpeakerTurnSegmentationModel {
 public:
  explicit SpeakerTurnSegmentationModel(std::vector<uint8_t> model_bytes)
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-speaker-turn"),
        model_bytes_(std::move(model_bytes)) {
    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetIntraOpNumThreads(1);
    options.SetInterOpNumThreads(1);
    options.DisableCpuMemArena();
    options.DisableMemPattern();
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
    session_ = Ort::Session(env_, model_bytes_.data(), model_bytes_.size(), options);
    Ort::AllocatorWithDefaultOptions allocator;
    input_name_ = session_.GetInputNameAllocated(0, allocator).get();
    output_name_ = session_.GetOutputNameAllocated(0, allocator).get();
  }

  struct Segment {
    int32_t start = 0;
    int32_t end = 0;
    int32_t speaker = 0;
    int32_t speaker_mask = 0;
  };

  std::vector<Segment> Process(const std::vector<float>& samples) {
    std::lock_guard<std::mutex> lock(mutex_);
    const int32_t source_offset =
        samples.size() > kWindowSamples ? samples.size() - kWindowSamples : 0;
    std::vector<float> window(kWindowSamples, 0.0F);
    const size_t copied = std::min(samples.size(), static_cast<size_t>(kWindowSamples));
    std::copy(samples.end() - copied, samples.end(), window.begin());
    std::array<int64_t, 3> shape{1, 1, kWindowSamples};
    auto memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input = Ort::Value::CreateTensor<float>(
        memory, window.data(), window.size(), shape.data(), shape.size());
    const char* input_names[] = {input_name_.c_str()};
    const char* output_names[] = {output_name_.c_str()};
    auto output = session_.Run(Ort::RunOptions{nullptr}, input_names, &input, 1,
                               output_names, 1);
    if (output.size() != 1 || !output[0].IsTensor() ||
        output[0].GetTensorTypeAndShapeInfo().GetElementCount() !=
            kFrames * kClasses) {
      throw std::runtime_error("speaker segmentation returned invalid output");
    }
    const float* logits = output[0].GetTensorData<float>();
    std::vector<Segment> result;
    int32_t active_speaker_mask = 0;
    int32_t active_start = 0;
    auto finish = [&](int32_t end) {
      if (active_speaker_mask != 0 && end > active_start) {
        result.push_back({active_start, end,
                          PrimarySpeaker(active_speaker_mask),
                          active_speaker_mask});
      }
      active_speaker_mask = 0;
    };
    for (int32_t frame = 0; frame < kFrames; ++frame) {
      const float* row = logits + frame * kClasses;
      const int32_t klass = static_cast<int32_t>(
          std::max_element(row, row + kClasses) - row);
      const int32_t speaker_mask = ClassToSpeakerMask(klass);
      const int32_t boundary = source_offset + kReceptiveFieldSize / 2 +
                               frame * kReceptiveFieldShift;
      if (speaker_mask == active_speaker_mask) continue;
      finish(std::clamp(boundary, 0, static_cast<int32_t>(samples.size())));
      if (speaker_mask != 0) {
        active_speaker_mask = speaker_mask;
        active_start = std::clamp(boundary, 0, static_cast<int32_t>(samples.size()));
      }
    }
    finish(static_cast<int32_t>(samples.size()));
    return result;
  }

 private:
  Ort::Env env_;
  std::vector<uint8_t> model_bytes_;
  Ort::Session session_{nullptr};
  std::string input_name_;
  std::string output_name_;
  std::mutex mutex_;
};

std::mutex g_mutex;
std::shared_ptr<SpeakerTurnSegmentationModel> g_model;
uint64_t g_generation = 0;

struct LoadContext {
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
  std::vector<uint8_t> bytes;
  std::shared_ptr<SpeakerTurnSegmentationModel> model;
  std::string error;
  uint64_t generation = 0;
};

void ExecuteLoad(napi_env, void* data) {
  auto* context = static_cast<LoadContext*>(data);
  try {
    context->model = std::make_shared<SpeakerTurnSegmentationModel>(
        std::move(context->bytes));
  } catch (const std::exception& error) {
    context->error = error.what();
  }
}

void CompleteLoad(napi_env env, napi_status status, void* data) {
  std::unique_ptr<LoadContext> context(static_cast<LoadContext*>(data));
  if (status != napi_ok && context->error.empty()) {
    context->error = "speaker segmentation model load failed";
  }
  if (context->error.empty()) {
    {
      std::lock_guard<std::mutex> lock(g_mutex);
      if (context->generation == g_generation && g_model == nullptr) {
        g_model = std::move(context->model);
      } else {
        context->error = "speaker segmentation model load superseded";
      }
    }
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
}

napi_value LoadAsync(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value args[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
  try {
    if (argc != 1) throw std::runtime_error("speaker segmentation model bytes required");
    auto context = std::make_unique<LoadContext>();
    context->bytes = CopyTypedArray<uint8_t>(env, args[0], napi_uint8_array);
    {
      std::lock_guard<std::mutex> lock(g_mutex);
      context->generation = ++g_generation;
    }
    napi_value promise = nullptr;
    napi_status status = napi_create_promise(env, &context->deferred, &promise);
    if (status != napi_ok) {
      throw std::runtime_error("failed to create speaker segmentation load promise");
    }
    napi_value name = nullptr;
    status = napi_create_string_utf8(
        env, "AmphionSpeakerTurnSegmenterLoad", NAPI_AUTO_LENGTH, &name);
    if (status == napi_ok) {
      status = napi_create_async_work(env, nullptr, name, ExecuteLoad,
                                      CompleteLoad, context.get(),
                                      &context->work);
    }
    if (status == napi_ok) status = napi_queue_async_work(env, context->work);
    if (status != napi_ok) {
      if (context->work != nullptr) napi_delete_async_work(env, context->work);
      napi_value message = nullptr;
      napi_create_string_utf8(env, "failed to queue speaker segmentation model load",
                              NAPI_AUTO_LENGTH, &message);
      napi_reject_deferred(env, context->deferred, message);
      return promise;
    }
    context.release();
    return promise;
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

napi_value IsLoaded(napi_env env, napi_callback_info) {
  std::lock_guard<std::mutex> lock(g_mutex);
  napi_value value = nullptr;
  napi_get_boolean(env, g_model != nullptr, &value);
  return value;
}

napi_value Unload(napi_env env, napi_callback_info) {
  {
    std::lock_guard<std::mutex> lock(g_mutex);
    ++g_generation;
    g_model.reset();
  }
  napi_value value = nullptr;
  napi_get_undefined(env, &value);
  return value;
}

napi_value Process(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value args[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
  try {
    std::shared_ptr<SpeakerTurnSegmentationModel> model;
    {
      std::lock_guard<std::mutex> lock(g_mutex);
      model = g_model;
    }
    if (model == nullptr) throw std::runtime_error("speaker segmentation model not loaded");
    auto segments = model->Process(
        CopyTypedArray<float>(env, args[0], napi_float32_array));
    napi_value result = nullptr;
    napi_create_array_with_length(env, segments.size(), &result);
    for (uint32_t i = 0; i < segments.size(); ++i) {
      napi_value item = nullptr;
      napi_create_object(env, &item);
      napi_value value = nullptr;
      napi_create_int32(env, segments[i].start, &value);
      napi_set_named_property(env, item, "startSample", value);
      napi_create_int32(env, segments[i].end, &value);
      napi_set_named_property(env, item, "endSample", value);
      napi_create_int32(env, segments[i].speaker, &value);
      napi_set_named_property(env, item, "speaker", value);
      napi_create_int32(env, segments[i].speaker_mask, &value);
      napi_set_named_property(env, item, "speakerMask", value);
      napi_set_element(env, result, i, item);
    }
    return result;
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

struct ProcessContext {
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
  std::shared_ptr<SpeakerTurnSegmentationModel> model;
  std::vector<float> samples;
  std::vector<SpeakerTurnSegmentationModel::Segment> segments;
  std::string error;
};

void ExecuteProcess(napi_env, void* data) {
  auto* context = static_cast<ProcessContext*>(data);
  try {
    context->segments = context->model->Process(context->samples);
  } catch (const std::exception& error) {
    context->error = error.what();
  } catch (...) {
    context->error = "unknown speaker segmentation error";
  }
  context->model.reset();
  context->samples.clear();
}

void CompleteProcess(napi_env env, napi_status status, void* data) {
  std::unique_ptr<ProcessContext> context(static_cast<ProcessContext*>(data));
  if (status != napi_ok && context->error.empty()) {
    context->error = "speaker segmentation async work failed";
  }
  if (!context->error.empty()) {
    napi_value message = nullptr;
    napi_create_string_utf8(env, context->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_reject_deferred(env, context->deferred, message);
    napi_delete_async_work(env, context->work);
    return;
  }
  napi_value result = nullptr;
  napi_create_array_with_length(env, context->segments.size(), &result);
  for (uint32_t i = 0; i < context->segments.size(); ++i) {
    napi_value item = nullptr;
    napi_create_object(env, &item);
    napi_value value = nullptr;
    napi_create_int32(env, context->segments[i].start, &value);
    napi_set_named_property(env, item, "startSample", value);
    napi_create_int32(env, context->segments[i].end, &value);
    napi_set_named_property(env, item, "endSample", value);
    napi_create_int32(env, context->segments[i].speaker, &value);
    napi_set_named_property(env, item, "speaker", value);
    napi_create_int32(env, context->segments[i].speaker_mask, &value);
    napi_set_named_property(env, item, "speakerMask", value);
    napi_set_element(env, result, i, item);
  }
  napi_resolve_deferred(env, context->deferred, result);
  napi_delete_async_work(env, context->work);
}

napi_value ProcessAsync(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value args[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
  try {
    if (argc != 1) throw std::runtime_error("speaker segmentation samples required");
    auto context = std::make_unique<ProcessContext>();
    context->samples = CopyTypedArray<float>(env, args[0], napi_float32_array);
    {
      std::lock_guard<std::mutex> lock(g_mutex);
      context->model = g_model;
    }
    if (context->model == nullptr) {
      throw std::runtime_error("speaker segmentation model not loaded");
    }
    napi_value promise = nullptr;
    napi_status status = napi_create_promise(env, &context->deferred, &promise);
    if (status != napi_ok) {
      throw std::runtime_error("failed to create speaker segmentation promise");
    }
    napi_value name = nullptr;
    status = napi_create_string_utf8(
        env, "AmphionSpeakerTurnSegmenterProcess", NAPI_AUTO_LENGTH, &name);
    if (status == napi_ok) {
      status = napi_create_async_work(env, nullptr, name, ExecuteProcess,
                                      CompleteProcess, context.get(),
                                      &context->work);
    }
    if (status == napi_ok) status = napi_queue_async_work(env, context->work);
    if (status != napi_ok) {
      if (context->work != nullptr) napi_delete_async_work(env, context->work);
      napi_value message = nullptr;
      napi_create_string_utf8(env, "failed to queue speaker segmentation work",
                              NAPI_AUTO_LENGTH, &message);
      napi_reject_deferred(env, context->deferred, message);
      return promise;
    }
    context.release();
    return promise;
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

}  // namespace

void RegisterSpeakerTurnSegmenter(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"loadSpeakerTurnSegmentationModelAsync", nullptr, LoadAsync, nullptr, nullptr,
       nullptr, napi_default, nullptr},
      {"isSpeakerTurnSegmentationModelLoaded", nullptr, IsLoaded, nullptr, nullptr,
       nullptr, napi_default, nullptr},
      {"unloadSpeakerTurnSegmentationModel", nullptr, Unload, nullptr, nullptr,
       nullptr, napi_default, nullptr},
      {"processSpeakerTurnSegmentation", nullptr, Process, nullptr, nullptr,
       nullptr, napi_default, nullptr},
      {"processSpeakerTurnSegmentationAsync", nullptr, ProcessAsync, nullptr, nullptr,
       nullptr, napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(descriptors) / sizeof(descriptors[0]), descriptors);
}
