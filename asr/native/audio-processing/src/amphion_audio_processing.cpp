#include "amphion_audio_processing.h"

#include <cmath>
#include <cstdint>
#include <new>

#include "api/audio/audio_processing.h"

#if defined(AMPHION_ANDROID_JNI)
#include <jni.h>
#endif

namespace {

// Keep a small deterministic floor under AGC2's speech-probability driven adaptive gain. The
// adaptive estimator alone can settle near unity on low-level conversational recordings; 4 dB is
// enough to recover those features without the substitutions observed with a 6 dB floor.
constexpr float kFixedDigitalGainDb = 4.0f;

}  // namespace

struct AmphionAgc {
  int sample_rate_hz;
  webrtc::StreamConfig stream_config;
  rtc::scoped_refptr<webrtc::AudioProcessing> processor;
};

AmphionAgc* amphion_agc_create(int sample_rate_hz) {
  if (sample_rate_hz <= 0 || sample_rate_hz % 100 != 0) {
    return nullptr;
  }

  webrtc::AudioProcessing::Config config;
  config.gain_controller2.enabled = true;
  config.gain_controller2.input_volume_controller.enabled = false;
  config.gain_controller2.adaptive_digital.enabled = true;
  config.gain_controller2.adaptive_digital.headroom_db = 6.0f;
  config.gain_controller2.adaptive_digital.max_gain_db = 20.0f;
  config.gain_controller2.adaptive_digital.initial_gain_db = 4.0f;
  config.gain_controller2.adaptive_digital.max_gain_change_db_per_second = 6.0f;
  config.gain_controller2.adaptive_digital.max_output_noise_level_dbfs = -50.0f;
  config.gain_controller2.fixed_digital.gain_db = kFixedDigitalGainDb;

  auto processor = webrtc::AudioProcessingBuilder().SetConfig(config).Create();
  if (!processor) {
    return nullptr;
  }
  return new (std::nothrow) AmphionAgc{
      sample_rate_hz,
      webrtc::StreamConfig(sample_rate_hz, 1),
      std::move(processor),
  };
}

int amphion_agc_process(AmphionAgc* agc, float* samples, size_t sample_count) {
  if (agc == nullptr || samples == nullptr ||
      sample_count != static_cast<size_t>(agc->sample_rate_hz / 100)) {
    return -1;
  }
  for (size_t i = 0; i < sample_count; ++i) {
    if (!std::isfinite(samples[i])) {
      return -2;
    }
  }

  const float* input[] = {samples};
  float* output[] = {samples};
  return agc->processor->ProcessStream(
      input, agc->stream_config, agc->stream_config, output);
}

void amphion_agc_destroy(AmphionAgc* agc) {
  delete agc;
}

#if defined(AMPHION_ANDROID_JNI)
extern "C" JNIEXPORT jlong JNICALL
Java_com_amphion_asr_internal_NativeAgcBackend_nativeCreate(
    JNIEnv*, jobject, jint sample_rate_hz) {
  return reinterpret_cast<jlong>(amphion_agc_create(sample_rate_hz));
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_amphion_asr_internal_NativeAgcBackend_nativeProcess(
    JNIEnv* env, jobject, jlong handle, jfloatArray frame) {
  if (handle == 0 || frame == nullptr) {
    return JNI_FALSE;
  }
  const jsize length = env->GetArrayLength(frame);
  jfloat* samples = env->GetFloatArrayElements(frame, nullptr);
  if (samples == nullptr) {
    return JNI_FALSE;
  }
  const int result = amphion_agc_process(
      reinterpret_cast<AmphionAgc*>(handle), samples, static_cast<size_t>(length));
  env->ReleaseFloatArrayElements(frame, samples, result == 0 ? 0 : JNI_ABORT);
  return result == 0 ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL
Java_com_amphion_asr_internal_NativeAgcBackend_nativeDestroy(
    JNIEnv*, jobject, jlong handle) {
  amphion_agc_destroy(reinterpret_cast<AmphionAgc*>(handle));
}
#endif
