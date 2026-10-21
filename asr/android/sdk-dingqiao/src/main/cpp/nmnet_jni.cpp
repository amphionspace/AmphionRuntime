#include "nmnet_sdk_session.h"
#include <jni.h>
#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include <unordered_map>

namespace {
std::mutex registryMutex;
std::unordered_map<jlong,std::shared_ptr<nmnet::SdkSession>> sessions;
jlong nextHandle=1;
std::shared_ptr<nmnet::SdkSession> Get(jlong handle) {
  std::lock_guard<std::mutex> lock(registryMutex);auto it=sessions.find(handle);
  if(it==sessions.end())throw std::runtime_error("NMNet session closed");return it->second;
}
void Error(JNIEnv* env,const std::exception& error){env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),error.what());}
}
#define NMNET_JNI(name) Java_com_amphion_dingqiao_diarization_NmnetDiarizationInference_##name
extern "C" JNIEXPORT jlong JNICALL NMNET_JNI(nativeLoad)(JNIEnv* env,jobject,jobject assets,jint capacity) {
  try {
    auto manager=AAssetManager_fromJava(env,assets);if(!manager)throw std::runtime_error("NMNet assets unavailable");
    std::array<std::vector<uint8_t>,5> models;
    for(size_t i=0;i<5;++i) {
      std::string name=std::string(nmnet::kModelResourceDirectory)+"/"+nmnet::kModelFileNames[i];
      std::unique_ptr<AAsset,decltype(&AAsset_close)> file(AAssetManager_open(manager,name.c_str(),AASSET_MODE_STREAMING),AAsset_close);
      if(!file)throw std::runtime_error("missing NMNet model: "+name);
      auto length=AAsset_getLength64(file.get());
      if(length<=0||length>512*1024*1024)throw std::runtime_error("invalid NMNet model size");
      auto& bytes=models[i];bytes.resize(length);size_t offset=0;
      while(offset<bytes.size()) {
        int n=AAsset_read(file.get(),bytes.data()+offset,bytes.size()-offset);
        if(n<=0)throw std::runtime_error("NMNet model read failed");offset+=n;
      }
    }
    auto session=std::make_shared<nmnet::SdkSession>(models,capacity);
    std::lock_guard<std::mutex> lock(registryMutex);auto handle=nextHandle++;
    sessions.emplace(handle,std::move(session));return handle;
  }catch(const std::exception& e){Error(env,e);return 0;}
}
extern "C" JNIEXPORT jstring JNICALL NMNET_JNI(nativeProcess)(JNIEnv* env,jobject,jlong handle,jfloatArray pcm,jint valid,jlong index) {
  try {
    if(!pcm||env->GetArrayLength(pcm)!=nmnet::kWindowSamples||index<0||index>UINT32_MAX)
      throw std::invalid_argument("invalid NMNet PCM/window index");
    std::vector<float> samples(nmnet::kWindowSamples);env->GetFloatArrayRegion(pcm,0,samples.size(),samples.data());
    if(env->ExceptionCheck())return nullptr;
    auto result=Get(handle)->Process(samples,valid,index);return env->NewStringUTF(result.c_str());
  }catch(const std::exception& e){Error(env,e);return nullptr;}
}
extern "C" JNIEXPORT jstring JNICALL NMNET_JNI(nativeFinish)(JNIEnv* env,jobject,jlong handle) {
  try {auto result=Get(handle)->Finish();return env->NewStringUTF(result.c_str());}
  catch(const std::exception& e){Error(env,e);return nullptr;}
}
extern "C" JNIEXPORT void JNICALL NMNET_JNI(nativeClose)(JNIEnv*,jobject,jlong handle) {
  std::lock_guard<std::mutex> lock(registryMutex);sessions.erase(handle);
}
