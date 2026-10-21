#include "nmnet_sdk_session.h"
#include <napi/native_api.h>
#include <rawfile/raw_file_manager.h>
#include <rawfile/raw_file.h>
#include <cstring>
#include <unordered_map>
#include <qos/qos.h>

namespace {
std::mutex registryMutex;
struct Entry {std::shared_ptr<nmnet::SdkSession> session;int qos;};
std::unordered_map<uint32_t,Entry> sessions;
uint32_t nextHandle=1;
enum class Op {Load,Process,Finish};
struct Work {
  Op op; napi_env env=nullptr; napi_async_work work=nullptr; napi_deferred deferred=nullptr;
  napi_ref ref=nullptr;NativeResourceManager* resources=nullptr;
  std::shared_ptr<nmnet::SdkSession> session;
  std::vector<float> pcm;int valid=0,capacity=0,qos=-1;uint64_t index=0;
  std::string result,error;
  ~Work(){if(resources)OH_ResourceManager_ReleaseNativeResourceManager(resources);if(ref)napi_delete_reference(env,ref);}
};
double Integer(napi_env env,napi_value value,double maximum) {
  double n;
  if(napi_get_value_double(env,value,&n)!=napi_ok||!std::isfinite(n)||n<0||n>maximum||std::floor(n)!=n)
    throw std::invalid_argument("invalid NMNet integer argument");
  return n;
}
std::vector<uint8_t> Asset(NativeResourceManager* resources,const char* fileName) {
  std::string name=std::string(nmnet::kModelResourceDirectory)+"/"+fileName;
  std::unique_ptr<RawFile,decltype(&OH_ResourceManager_CloseRawFile)> file(
    OH_ResourceManager_OpenRawFile(resources,name.c_str()),OH_ResourceManager_CloseRawFile);
  if(!file)throw std::runtime_error("missing NMNet model: "+name);
  long size=OH_ResourceManager_GetRawFileSize(file.get());
  if(size<=0||size>512*1024*1024)throw std::runtime_error("invalid NMNet model size");
  std::vector<uint8_t> bytes(size);size_t offset=0;
  while(offset<bytes.size()) {
    int n=OH_ResourceManager_ReadRawFile(file.get(),bytes.data()+offset,bytes.size()-offset);
    if(n<=0||size_t(n)>bytes.size()-offset)throw std::runtime_error("NMNet model read failed");
    offset+=n;
  }
  return bytes;
}
void Execute(napi_env,void* data) {
  auto& w=*static_cast<Work*>(data);
  // The N-API pool is shared: restore its prior scheduling state on every exit.
  struct QosScope {
    QoS_Level previous=QOS_DEFAULT;bool had=OH_QoS_GetThreadQoS(&previous)==0;
    bool changed;
    explicit QosScope(int requested):changed(requested>=0){if(changed)OH_QoS_SetThreadQoS(static_cast<QoS_Level>(requested));}
    ~QosScope(){if(changed){if(had)OH_QoS_SetThreadQoS(previous);else OH_QoS_ResetThreadQoS();}}
  } qos(w.qos);
  try {
    if(w.op==Op::Load) {
      std::array<std::vector<uint8_t>,5> models;
      for(size_t i=0;i<5;++i)models[i]=Asset(w.resources,nmnet::kModelFileNames[i]);
      w.session=std::make_shared<nmnet::SdkSession>(models,w.capacity);
    }else if(w.op==Op::Process)w.result=w.session->Process(w.pcm,w.valid,w.index);
    else w.result=w.session->Finish();
  }catch(const std::exception& e){w.error=e.what();}
}
void Complete(napi_env env,napi_status status,void* data) {
  std::unique_ptr<Work> w(static_cast<Work*>(data));napi_value value;
  if(status!=napi_ok&&w->error.empty())w->error="NMNet work cancelled";
  if(!w->error.empty()) {
    napi_value message;napi_create_string_utf8(env,w->error.c_str(),NAPI_AUTO_LENGTH,&message);
    napi_create_error(env,nullptr,message,&value);napi_reject_deferred(env,w->deferred,value);
  }else {
    if(w->op==Op::Load) {
      std::lock_guard<std::mutex> lock(registryMutex);
      uint32_t handle=nextHandle++;sessions.emplace(handle,Entry{w->session,w->qos});napi_create_uint32(env,handle,&value);
    }else napi_create_string_utf8(env,w->result.c_str(),w->result.size(),&value);
    napi_resolve_deferred(env,w->deferred,value);
  }
  napi_delete_async_work(env,w->work);
}
napi_value Queue(napi_env env,napi_callback_info info,Op op) {
  try {
    size_t count=4;napi_value args[4]={};napi_get_cb_info(env,info,&count,args,nullptr,nullptr);
    if(count!=(op==Op::Load?3u:op==Op::Process?4u:1u))throw std::invalid_argument("NMNet argument count");
    auto w=std::make_unique<Work>();w->op=op;w->env=env;
    if(op==Op::Load) {
      w->capacity=Integer(env,args[1],INT32_MAX);
      char text[32];size_t length=0;
      if(napi_get_value_string_utf8(env,args[2],text,sizeof(text),&length)!=napi_ok||length>=sizeof(text)-1)
        throw std::invalid_argument("invalid NMNet role QoS");
      const std::string qos(text,length);
      if(qos=="background")w->qos=QOS_BACKGROUND;
      else if(qos=="utility")w->qos=QOS_UTILITY;
      else if(qos=="default")w->qos=QOS_DEFAULT;
      else if(qos=="user-initiated")w->qos=QOS_USER_INITIATED;
      else if(qos!="inherit")throw std::invalid_argument("invalid NMNet role QoS");
      w->resources=OH_ResourceManager_InitNativeResourceManager(env,args[0]);
      if(!w->resources||napi_create_reference(env,args[0],1,&w->ref)!=napi_ok)
        throw std::runtime_error("NMNet resource manager unavailable");
    }else {
      auto handle=static_cast<uint32_t>(Integer(env,args[0],UINT32_MAX));
      {std::lock_guard<std::mutex> lock(registryMutex);auto it=sessions.find(handle);
       if(it==sessions.end())throw std::runtime_error("NMNet session closed");w->session=it->second.session;w->qos=it->second.qos;}
      if(op==Op::Process) {
        w->valid=Integer(env,args[2],nmnet::kWindowSamples);w->index=Integer(env,args[3],UINT32_MAX);
        napi_typedarray_type type;size_t length,offset;void* data;napi_value buffer;
        if(napi_get_typedarray_info(env,args[1],&type,&length,&data,&buffer,&offset)!=napi_ok||type!=napi_float32_array)
          throw std::invalid_argument("NMNet PCM must be Float32Array");
        napi_value sizeValue;uint32_t bytes=0;
        if(napi_get_named_property(env,args[1],"byteLength",&sizeValue)!=napi_ok||
           napi_get_value_uint32(env,sizeValue,&bytes)!=napi_ok||bytes!=nmnet::kWindowSamples*sizeof(float)||
           (length!=nmnet::kWindowSamples&&length!=bytes)||!data)
          throw std::invalid_argument("NMNet requires fixed 320000-sample PCM");
        w->pcm.resize(nmnet::kWindowSamples);std::memcpy(w->pcm.data(),data,bytes);
      }
    }
    napi_value promise,name;
    if(napi_create_promise(env,&w->deferred,&promise)!=napi_ok)throw std::runtime_error("NMNet promise failed");
    napi_create_string_utf8(env,"NmnetDiarization",NAPI_AUTO_LENGTH,&name);
    auto status=napi_create_async_work(env,nullptr,name,Execute,Complete,w.get(),&w->work);
    if(status==napi_ok)status=napi_queue_async_work(env,w->work);
    if(status!=napi_ok){if(w->work)napi_delete_async_work(env,w->work);throw std::runtime_error("NMNet work queue failed");}
    w.release();return promise;
  }catch(const std::exception& e){napi_throw_error(env,nullptr,e.what());return nullptr;}
}
napi_value Load(napi_env e,napi_callback_info i){return Queue(e,i,Op::Load);}
napi_value Process(napi_env e,napi_callback_info i){return Queue(e,i,Op::Process);}
napi_value Finish(napi_env e,napi_callback_info i){return Queue(e,i,Op::Finish);}
napi_value Close(napi_env env,napi_callback_info info) {
  try {size_t count=1;napi_value arg,result;napi_get_cb_info(env,info,&count,&arg,nullptr,nullptr);
    if(count!=1)throw std::invalid_argument("NMNet close argument count");
    auto handle=static_cast<uint32_t>(Integer(env,arg,UINT32_MAX));
    {std::lock_guard<std::mutex> lock(registryMutex);sessions.erase(handle);}
    napi_get_undefined(env,&result);return result;
  }catch(const std::exception& e){napi_throw_error(env,nullptr,e.what());return nullptr;}
}
}
void RegisterNmnetDiarization(napi_env env,napi_value exports) {
  napi_property_descriptor methods[]={
    {"loadNmnetDiarization",nullptr,Load,nullptr,nullptr,nullptr,napi_default,nullptr},
    {"processNmnetDiarization",nullptr,Process,nullptr,nullptr,nullptr,napi_default,nullptr},
    {"finishNmnetDiarization",nullptr,Finish,nullptr,nullptr,nullptr,napi_default,nullptr},
    {"closeNmnetDiarization",nullptr,Close,nullptr,nullptr,nullptr,napi_default,nullptr}};
  napi_define_properties(env,exports,4,methods);
}
