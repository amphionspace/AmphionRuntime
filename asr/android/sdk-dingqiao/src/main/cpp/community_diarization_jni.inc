#include <jni.h>
#include <fstream>
#include <iterator>

namespace {
std::mutex android_model_mutex;
std::unordered_map<jlong, std::shared_ptr<Model>> android_models;
jlong android_next_handle = 1;
std::shared_ptr<Model> AndroidModel(jlong handle) {
  std::lock_guard<std::mutex> lock(android_model_mutex);
  auto found = android_models.find(handle);
  if (found == android_models.end()) throw std::runtime_error("Community model is closed");
  return found->second;
}
void AndroidError(JNIEnv* env, const std::exception& error) {
  env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), error.what());
}
std::vector<uint8_t> AndroidAsset(JNIEnv* env, jstring path) {
  const char* chars = env->GetStringUTFChars(path, nullptr);
  if (!chars) throw std::runtime_error("Community asset path unavailable");
  std::ifstream stream(chars, std::ios::binary);
  env->ReleaseStringUTFChars(path, chars);
  if (!stream) throw std::runtime_error("Community asset unavailable");
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(stream), {});
}
std::vector<float> AndroidFloats(JNIEnv* env, jfloatArray array) {
  if (!array) throw std::runtime_error("Community array missing");
  std::vector<float> values(env->GetArrayLength(array));
  env->GetFloatArrayRegion(array, 0, values.size(), values.data());
  return values;
}
jfloatArray AndroidArray(JNIEnv* env, const std::vector<float>& values) {
  auto array = env->NewFloatArray(values.size());
  if (array) env->SetFloatArrayRegion(array, 0, values.size(), values.data());
  return array;
}
}
#define COMMUNITY_JNI(name) Java_com_amphion_dingqiao_diarization_CommunityDiarizationInference_##name
extern "C" JNIEXPORT jlong JNICALL COMMUNITY_JNI(nativeLoad)(JNIEnv* env, jobject,
    jstring segmentation, jstring encoder, jstring pooling, jstring feature, jstring plda) {
  try {
    auto model = std::make_shared<Model>(AndroidAsset(env, segmentation), AndroidAsset(env, encoder), AndroidAsset(env, pooling),
      AndroidAsset(env, feature), AndroidAsset(env, plda));
    std::lock_guard<std::mutex> lock(android_model_mutex);
    const auto handle = android_next_handle++;
    android_models.emplace(handle, std::move(model));
    return handle;
  } catch (const std::exception& error) { AndroidError(env, error); return 0; }
}
extern "C" JNIEXPORT jobject JNICALL COMMUNITY_JNI(nativeProcess)(JNIEnv* env, jobject,
    jlong handle, jfloatArray pcm) {
  try {
    auto samples = AndroidFloats(env, pcm);
    auto result = AndroidModel(handle)->Process(samples);
    auto type = env->FindClass("com/amphion/dingqiao/diarization/CommunityDiarizationWindow");
    auto constructor = env->GetMethodID(type, "<init>", "([F[FDDD[F[F[F)V");
    return env->NewObject(type, constructor, AndroidArray(env, result.segments),
      AndroidArray(env, result.embeddings), result.segmentation_ms, result.feature_ms, result.embedding_ms,
      AndroidArray(env, result.run_embeddings), AndroidArray(env, result.run_ranges), AndroidArray(env, result.run_rms));
  } catch (const std::exception& error) { AndroidError(env, error); return nullptr; }
}
extern "C" JNIEXPORT jstring JNICALL COMMUNITY_JNI(nativeCluster)(JNIEnv* env, jobject,
    jlong handle, jfloatArray segments, jfloatArray embeddings, jint max_speakers,
    jdoubleArray starts, jdouble begin_sample, jfloatArray run_embeddings, jfloatArray run_ranges,
    jfloatArray run_rms) {
  try {
    if (!starts) throw std::runtime_error("Community window positions missing");
    std::vector<double> positions(env->GetArrayLength(starts));
    env->GetDoubleArrayRegion(starts, 0, positions.size(), positions.data());
    // Same per-run evidence as Harmony: run vectors, [window, channel, begin, end)
    // ranges and clean-PCM levels for every retained window of this snapshot.
    auto result = AndroidModel(handle)->Cluster(AndroidFloats(env, segments),
      AndroidFloats(env, embeddings), AndroidFloats(env, run_embeddings), AndroidFloats(env, run_ranges),
      max_speakers, positions, begin_sample, AndroidFloats(env, run_rms));
    return env->NewStringUTF(result.c_str());
  } catch (const std::exception& error) { AndroidError(env, error); return nullptr; }
}
extern "C" JNIEXPORT void JNICALL COMMUNITY_JNI(nativeClose)(JNIEnv*, jobject, jlong handle) {
  std::lock_guard<std::mutex> lock(android_model_mutex);
  android_models.erase(handle);
}
