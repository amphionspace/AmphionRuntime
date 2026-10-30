// Sortformer 角色分离的 Android JNI 绑定。算法与鸿蒙共用 sortformer_diarization.cpp，
// 这里只做 JNI 转换：模型按文件路径读取，事件按 JSON 字符串回传，与鸿蒙 NAPI 侧同一份
// RenderEvents 输出，便于两端逐字段对照。
#include <jni.h>

namespace {

void SortformerThrow(JNIEnv* env, const char* message) {
  jclass type = env->FindClass("java/lang/IllegalStateException");
  if (type != nullptr) env->ThrowNew(type, message);
}

std::string SortformerString(JNIEnv* env, jstring value) {
  if (value == nullptr) throw std::runtime_error("Sortformer path missing");
  const char* chars = env->GetStringUTFChars(value, nullptr);
  if (chars == nullptr) throw std::runtime_error("Sortformer path unavailable");
  std::string copy(chars);
  env->ReleaseStringUTFChars(value, chars);
  return copy;
}

std::vector<float> SortformerFloats(JNIEnv* env, jfloatArray array) {
  if (array == nullptr) return {};
  std::vector<float> values(static_cast<size_t>(env->GetArrayLength(array)));
  if (!values.empty()) {
    env->GetFloatArrayRegion(array, 0, static_cast<jsize>(values.size()), values.data());
  }
  return values;
}

}  // namespace

#define SORTFORMER_JNI(name) \
  Java_com_amphion_dingqiao_diarization_SortformerDiarizationInference_##name

// Android 链的是 onnxruntime 1.24.3，而交付的 .ort 是用 1.16.3 转的（厂商连编码器都单独做了
// ort1163 变体），1.24 在 spkcache_update 的 TopK 上做形状推断时直接拒绝加载。所以 Android 装的
// 是版本无关的原始 .onnx，这里把共享实现请求的 .ort 名字映射到对应的 .onnx 文件。
// 图是同一张（.ort 本身由它派生），数值路径不变；代价是加载时多做一次图优化。
std::string SortformerAndroidAssetName(const std::string& name) {
  static const char kOrt[] = ".ort";
  const size_t suffix = sizeof(kOrt) - 1;
  if (name.size() > suffix && name.compare(name.size() - suffix, suffix, kOrt) == 0) {
    return name.substr(0, name.size() - suffix) + ".onnx";
  }
  return name;
}

extern "C" JNIEXPORT jint JNICALL SORTFORMER_JNI(nativeLoad)(
    JNIEnv* env, jobject, jstring model_dir, jint threads, jint preview_frames) {
  try {
    std::string dir = SortformerString(env, model_dir);
    if (!dir.empty() && dir.back() != '/') dir.push_back('/');
    const uint32_t handle = CreateSession(
      [dir](const std::string& name) {
        return ReadAssetFile(dir + SortformerAndroidAssetName(name));
      },
      threads, -1, preview_frames);
    return static_cast<jint>(handle);
  } catch (const Ort::Exception& error) {
    SortformerThrow(env, (std::string("Sortformer onnxruntime: ") + error.what()).c_str());
    return 0;
  } catch (const std::exception& error) {
    SortformerThrow(env, error.what());
    return 0;
  }
}

extern "C" JNIEXPORT jstring JNICALL SORTFORMER_JNI(nativeFeed)(
    JNIEnv* env, jobject, jint handle, jfloatArray pcm, jboolean flush) {
  try {
    std::shared_ptr<Session> session = LookupSession(static_cast<uint32_t>(handle));
    if (!session) throw std::runtime_error("Sortformer session is closed");
    const std::string rendered = FeedSession(session, SortformerFloats(env, pcm), flush == JNI_TRUE);
    return env->NewStringUTF(rendered.c_str());
  } catch (const Ort::Exception& error) {
    SortformerThrow(env, (std::string("Sortformer onnxruntime: ") + error.what()).c_str());
    return nullptr;
  } catch (const std::exception& error) {
    SortformerThrow(env, error.what());
    return nullptr;
  }
}

extern "C" JNIEXPORT void JNICALL SORTFORMER_JNI(nativeClose)(
    JNIEnv*, jobject, jint handle) {
  DestroySession(static_cast<uint32_t>(handle));
}
