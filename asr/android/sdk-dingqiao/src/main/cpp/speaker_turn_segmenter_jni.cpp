#include <jni.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace {

constexpr int64_t kWindowSamples = 160000;
constexpr int64_t kFrames = 589;
constexpr int64_t kClasses = 7;
constexpr int32_t kReceptiveFieldSize = 991;
constexpr int32_t kReceptiveFieldShift = 270;

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

class UtfChars {
 public:
  UtfChars(JNIEnv* env, jstring value) : env_(env), value_(value) {
    chars_ = env_->GetStringUTFChars(value_, nullptr);
    if (chars_ == nullptr) throw std::runtime_error("failed to read model path");
  }
  ~UtfChars() {
    if (chars_ != nullptr) env_->ReleaseStringUTFChars(value_, chars_);
  }
  const char* get() const { return chars_; }

 private:
  JNIEnv* env_;
  jstring value_;
  const char* chars_ = nullptr;
};

class SpeakerTurnSegmenter {
 public:
  explicit SpeakerTurnSegmenter(const char* model_path)
      : env_(ORT_LOGGING_LEVEL_WARNING, "amphion-speaker-turn") {
    Ort::SessionOptions options;
    options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
    options.SetIntraOpNumThreads(1);
    options.SetInterOpNumThreads(1);
    options.DisableCpuMemArena();
    options.DisableMemPattern();
    options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
    session_ = Ort::Session(env_, model_path, options);
    Ort::AllocatorWithDefaultOptions allocator;
    input_name_ = session_.GetInputNameAllocated(0, allocator).get();
    output_name_ = session_.GetOutputNameAllocated(0, allocator).get();
  }

  struct Segment {
    int32_t start;
    int32_t end;
    int32_t speaker;
    int32_t speaker_mask;
  };

  std::vector<Segment> Process(const std::vector<float>& samples) {
    std::lock_guard<std::mutex> lock(mutex_);
    const int32_t source_offset = samples.size() > kWindowSamples
                                      ? static_cast<int32_t>(samples.size() - kWindowSamples)
                                      : 0;
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
        output[0].GetTensorTypeAndShapeInfo().GetElementCount() != kFrames * kClasses) {
      throw std::runtime_error("speaker segmentation returned invalid output");
    }
    const float* logits = output[0].GetTensorData<float>();
    std::vector<Segment> result;
    int32_t active_mask = 0;
    int32_t active_start = 0;
    auto finish = [&](int32_t end) {
      if (active_mask != 0 && end > active_start) {
        result.push_back({active_start, end, PrimarySpeaker(active_mask), active_mask});
      }
      active_mask = 0;
    };
    for (int32_t frame = 0; frame < kFrames; ++frame) {
      const float* row = logits + frame * kClasses;
      const int32_t klass = static_cast<int32_t>(
          std::max_element(row, row + kClasses) - row);
      const int32_t speaker_mask = ClassToSpeakerMask(klass);
      const int32_t boundary = std::clamp(
          source_offset + kReceptiveFieldSize / 2 + frame * kReceptiveFieldShift,
          0, static_cast<int32_t>(samples.size()));
      if (speaker_mask == active_mask) continue;
      finish(boundary);
      if (speaker_mask != 0) {
        active_mask = speaker_mask;
        active_start = boundary;
      }
    }
    finish(static_cast<int32_t>(samples.size()));
    return result;
  }

 private:
  Ort::Env env_;
  Ort::Session session_{nullptr};
  std::string input_name_;
  std::string output_name_;
  std::mutex mutex_;
};

void ThrowJava(JNIEnv* env, const std::exception& error) {
  jclass type = env->FindClass("java/lang/IllegalStateException");
  if (type != nullptr) env->ThrowNew(type, error.what());
}

}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_com_amphion_dingqiao_diarization_SpeakerTurnSegmenter_nativeCreate(
    JNIEnv* env, jobject, jstring model_path) {
  try {
    if (model_path == nullptr) throw std::invalid_argument("model path is required");
    UtfChars path(env, model_path);
    return reinterpret_cast<jlong>(new SpeakerTurnSegmenter(path.get()));
  } catch (const std::exception& error) {
    ThrowJava(env, error);
    return 0;
  }
}

extern "C" JNIEXPORT jintArray JNICALL
Java_com_amphion_dingqiao_diarization_SpeakerTurnSegmenter_nativeProcess(
    JNIEnv* env, jobject, jlong handle, jfloatArray samples_array) {
  try {
    auto* segmenter = reinterpret_cast<SpeakerTurnSegmenter*>(handle);
    if (segmenter == nullptr) throw std::invalid_argument("segmenter is closed");
    if (samples_array == nullptr) throw std::invalid_argument("samples are required");
    const jsize count = env->GetArrayLength(samples_array);
    std::vector<float> samples(static_cast<size_t>(count));
    env->GetFloatArrayRegion(samples_array, 0, count, samples.data());
    if (env->ExceptionCheck()) return nullptr;
    const auto segments = segmenter->Process(samples);
    std::vector<jint> flattened(segments.size() * 4);
    for (size_t index = 0; index < segments.size(); ++index) {
      flattened[index * 4] = segments[index].start;
      flattened[index * 4 + 1] = segments[index].end;
      flattened[index * 4 + 2] = segments[index].speaker;
      flattened[index * 4 + 3] = segments[index].speaker_mask;
    }
    jintArray result = env->NewIntArray(static_cast<jsize>(flattened.size()));
    if (result == nullptr) return nullptr;
    env->SetIntArrayRegion(result, 0, static_cast<jsize>(flattened.size()), flattened.data());
    return result;
  } catch (const std::exception& error) {
    ThrowJava(env, error);
    return nullptr;
  }
}

extern "C" JNIEXPORT void JNICALL
Java_com_amphion_dingqiao_diarization_SpeakerTurnSegmenter_nativeClose(
    JNIEnv*, jobject, jlong handle) {
  delete reinterpret_cast<SpeakerTurnSegmenter*>(handle);
}
