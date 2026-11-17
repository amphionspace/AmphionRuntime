#include "gtcrn_denoiser.h"
#include "stream_denoisers.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#include <rawfile/raw_file_manager.h>
namespace {
void ThrowJsError(napi_env env, const std::string& message) {
  napi_throw_error(env, nullptr, message.c_str());
}

template <typename T>
std::vector<T> CopyTypedArray(napi_env env, napi_value value, napi_typedarray_type expected,
                              const char* name) {
  napi_typedarray_type actual;
  size_t length = 0;
  void* data = nullptr;
  napi_value array_buffer = nullptr;
  size_t byte_offset = 0;
  if (napi_get_typedarray_info(env, value, &actual, &length, &data, &array_buffer,
                               &byte_offset) != napi_ok || actual != expected) {
    throw std::runtime_error(std::string(name) + " has an invalid typed-array type");
  }
  napi_value byte_length_value = nullptr;
  uint32_t view_bytes = 0;
  if (napi_get_named_property(env, value, "byteLength", &byte_length_value) != napi_ok ||
      napi_get_value_uint32(env, byte_length_value, &view_bytes) != napi_ok ||
      view_bytes % sizeof(T) != 0) {
    throw std::runtime_error(std::string(name) + " has an invalid byteLength");
  }
  void* buffer_data = nullptr;
  size_t buffer_bytes = 0;
  if (napi_get_arraybuffer_info(env, array_buffer, &buffer_data, &buffer_bytes) != napi_ok ||
      byte_offset > buffer_bytes || view_bytes > buffer_bytes - byte_offset) {
    throw std::runtime_error(std::string(name) + " exceeds its backing buffer");
  }
  const size_t element_count = view_bytes / sizeof(T);
  // Standard Node-API reports elements, while affected Harmony releases report bytes. The JS
  // view's own byteLength remains authoritative, including for a subarray of a larger buffer.
  if (length != element_count && length != view_bytes) {
    throw std::runtime_error(std::string(name) + " has an inconsistent native length");
  }
  if (element_count == 0) return {};
  if (data == nullptr) throw std::runtime_error("missing typed-array data");
  const T* begin = static_cast<const T*>(data);
  return std::vector<T>(begin, begin + element_count);
}


class Denoiser {
 public:
  explicit Denoiser(NativeResourceManager* manager, const std::string& name) {
    {
      other_ = amphion_denoise::CreateStreamDenoiser(name, [manager](const std::string& asset) {
        const std::string path = "amphion-dingqiao/" + asset;
        RawFile* file = OH_ResourceManager_OpenRawFile(manager, path.c_str());
        if (!file) throw std::runtime_error("missing denoiser model: " + path);
        struct Guard { RawFile* file; ~Guard() { OH_ResourceManager_CloseRawFile(file); } } guard{file};
        const long size = OH_ResourceManager_GetRawFileSize(file);
        if (size <= 0) throw std::runtime_error("empty denoiser model: " + path);
        std::vector<uint8_t> bytes(static_cast<size_t>(size));
        if (OH_ResourceManager_ReadRawFile(file, bytes.data(), bytes.size()) != size)
          throw std::runtime_error("failed to read denoiser model: " + path);
        return bytes;
      });
      return;
    }
  }
  std::vector<float> Process(const std::vector<float>& input, bool flush) {
    std::lock_guard<std::mutex> lock(mutex_);
    return other_->Process(input, flush);
  }
 private:
  std::unique_ptr<amphion_denoise::StreamDenoiser> other_;
  std::mutex mutex_;
};
struct Holder { std::shared_ptr<Denoiser> model; };
void Finalize(napi_env, void* data, void*) { delete static_cast<Holder*>(data); }
Holder* GetHolder(napi_env env, napi_value value) {
  void* data = nullptr;
  if (napi_get_value_external(env, value, &data) != napi_ok || !data) throw std::runtime_error("invalid GTCRN handle");
  return static_cast<Holder*>(data);
}
napi_value Create(napi_env env, napi_callback_info info) {
  try {
    size_t argc=2; napi_value args[2]{};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    if (argc < 1) throw std::runtime_error("createGtcrnDenoiser expects resourceManager");
    std::string name = "deepfilternet3";
    if (argc == 2) {
      char text[32]{}; size_t length=0;
      if (napi_get_value_string_utf8(env,args[1],text,sizeof(text),&length)!=napi_ok || length>=sizeof(text)-1)
        throw std::runtime_error("invalid noise suppression model name");
      name.assign(text,length);
      if(name!="deepfilternet3") throw std::runtime_error("unsupported noise suppression model");
    }
    auto* manager = OH_ResourceManager_InitNativeResourceManager(env, args[0]);
    if (!manager) throw std::runtime_error("invalid resource manager");
    struct Guard { NativeResourceManager* p; ~Guard() { OH_ResourceManager_ReleaseNativeResourceManager(p); } } guard{manager};
    auto holder = std::make_unique<Holder>();
    holder->model = std::make_shared<Denoiser>(manager,name);
    napi_value result;
    if (napi_create_external(env, holder.get(), Finalize, nullptr, &result) != napi_ok) throw std::runtime_error("GTCRN handle allocation failed");
    holder.release(); return result;
  } catch (const std::exception& e) { ThrowJsError(env,e.what()); return nullptr; }
}
struct Work {
  napi_deferred deferred=nullptr;
  napi_async_work work=nullptr;
  std::shared_ptr<Denoiser> model;
  std::vector<float> input, output;
  bool flush=false;
  double duration_ms=0;
  std::string error;
};
void Execute(napi_env, void* data) {
  auto* w=static_cast<Work*>(data);
  try {
    const auto start=std::chrono::steady_clock::now();
    w->output=w->model->Process(w->input,w->flush);
    w->duration_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
  } catch(const std::exception& e) { w->error=e.what(); }
}
void Complete(napi_env env,napi_status status,void* data) {
  std::unique_ptr<Work> w(static_cast<Work*>(data));
  if (status != napi_ok && w->error.empty()) w->error="GTCRN async work canceled";
  if (!w->error.empty()) {
    napi_value error; napi_create_string_utf8(env,w->error.c_str(),NAPI_AUTO_LENGTH,&error);
    napi_reject_deferred(env,w->deferred,error);
  } else {
    napi_value result,buffer,samples,duration; void* bytes=nullptr;
    napi_create_object(env,&result);
    napi_create_arraybuffer(env,w->output.size()*sizeof(float),&bytes,&buffer);
    if (!w->output.empty()) std::memcpy(bytes,w->output.data(),w->output.size()*sizeof(float));
    napi_create_typedarray(env,napi_float32_array,w->output.size(),buffer,0,&samples);
    napi_set_named_property(env,result,"samples",samples);
    napi_create_double(env,w->duration_ms,&duration);
    napi_set_named_property(env,result,"durationMs",duration);
    napi_resolve_deferred(env,w->deferred,result);
  }
  napi_delete_async_work(env,w->work);
}
napi_value Process(napi_env env,napi_callback_info info) {
  try {
    size_t argc=3; napi_value args[3]{};
    napi_get_cb_info(env,info,&argc,args,nullptr,nullptr);
    if(argc!=3) throw std::runtime_error("processGtcrn expects handle, samples, flush");
    auto w=std::make_unique<Work>();
    w->model=GetHolder(env,args[0])->model;
    if(!w->model) throw std::runtime_error("GTCRN is closed");
    w->input=CopyTypedArray<float>(env,args[1],napi_float32_array,"samples");
    if(napi_get_value_bool(env,args[2],&w->flush)!=napi_ok) throw std::runtime_error("invalid flush flag");
    napi_value promise,name;
    napi_create_promise(env,&w->deferred,&promise);
    napi_create_string_utf8(env,"AmphionGtcrn",NAPI_AUTO_LENGTH,&name);
    if(napi_create_async_work(env,nullptr,name,Execute,Complete,w.get(),&w->work)!=napi_ok) throw std::runtime_error("GTCRN async allocation failed");
    if(napi_queue_async_work(env,w->work)!=napi_ok) {
      napi_delete_async_work(env,w->work); throw std::runtime_error("GTCRN async queue failed");
    }
    w.release(); return promise;
  } catch(const std::exception& e) { ThrowJsError(env,e.what()); return nullptr; }
}
napi_value Close(napi_env env,napi_callback_info info) {
  try {
    size_t argc=1; napi_value args[1]{};
    napi_get_cb_info(env,info,&argc,args,nullptr,nullptr);
    if(argc!=1) throw std::runtime_error("closeGtcrnDenoiser expects handle");
    GetHolder(env,args[0])->model.reset();
    napi_value result; napi_get_undefined(env,&result); return result;
  } catch(const std::exception& e) { ThrowJsError(env,e.what()); return nullptr; }
}
}
void RegisterGtcrnDenoiser(napi_env env,napi_value exports) {
  napi_property_descriptor props[]={
    {"createGtcrnDenoiser",nullptr,Create,nullptr,nullptr,nullptr,napi_default,nullptr},
    {"processGtcrn",nullptr,Process,nullptr,nullptr,nullptr,napi_default,nullptr},
    {"closeGtcrnDenoiser",nullptr,Close,nullptr,nullptr,nullptr,napi_default,nullptr}
  };
  napi_define_properties(env,exports,sizeof(props)/sizeof(props[0]),props);
}
