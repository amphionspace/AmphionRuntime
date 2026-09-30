"""Portable clustering regressions; all vectors are synthetic, never voiceprints."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / 'asr/harmony/sdk/src/main/cpp'


class HarmonyCommunityNativeTest(unittest.TestCase):
    def test_resource_assets_preserve_bytes_and_release_failed_or_completed_loads(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        source_text = (CPP / 'community_diarization.cpp').read_text()
        reader = source_text[source_text.index('std::vector<uint8_t> ReadCommunityAsset'):
                             source_text.index('\n#endif', source_text.index('std::vector<uint8_t> ReadCommunityAsset'))]
        # Work carries the encoder budget default and the scheduling request, so
        # the slice has to bring the production definitions along instead of
        # restating their values. Keep the trailing newline: the closing #endif
        # must not share a line with the next slice.
        scheduling_end = source_text.index(
            'explicit ScopedCommunityScheduling(const CommunityScheduling&) {}')
        budget_end = source_text.index('\n', source_text.index('#endif', scheduling_end)) + 1
        budgets = source_text[source_text.index('constexpr int kDefaultEncoderThreads'):budget_end]
        work = source_text[source_text.index('struct Work {'):source_text.index('\nvoid Execute')]
        # Exercise production ownership with a platform resource provider that
        # returns partial reads and errors. No models or customer data needed.
        program = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using napi_env=void*;using napi_ref=void*;using napi_async_work=void*;using napi_deferred=void*;
enum class Operation { Load,Process,Cluster };
struct Model {};struct Window {};
struct NativeResourceManager {};
struct RawFile { size_t offset=0; };
static int closed=0,managers=0,references=0,readCalls=0;
static bool missing=false,truncated=false;
static long length=5;
RawFile* OH_ResourceManager_OpenRawFile(NativeResourceManager*,const char*) {
  return missing?nullptr:new RawFile;
}
void OH_ResourceManager_CloseRawFile(RawFile* f) { ++closed;delete f; }
long OH_ResourceManager_GetRawFileSize(RawFile*) { return length; }
int OH_ResourceManager_ReadRawFile(const RawFile* f,void* out,size_t size) {
  ++readCalls;if(truncated&&f->offset>=2)return 0;
  size_t count=std::min<size_t>(2,size);auto* bytes=static_cast<uint8_t*>(out);
  for(size_t i=0;i<count;++i)bytes[i]=static_cast<uint8_t>(f->offset+i+1);
  const_cast<RawFile*>(f)->offset+=count;return static_cast<int>(count);
}
void OH_ResourceManager_ReleaseNativeResourceManager(NativeResourceManager* manager) {
  assert(references==1);--managers;delete manager;
}
int napi_delete_reference(napi_env env,napi_ref ref) {
  assert(env&&ref&&managers==0);--references;return 0;
}
''' + budgets + reader + work + r'''
int main() {
  NativeResourceManager manager;
  assert(ReadCommunityAsset(&manager,"model")==std::vector<uint8_t>({1,2,3,4,5}));
  assert(readCalls==3&&closed==1);
  for(int mode=0;mode<3;++mode) {
    missing=mode==0;length=mode==1?0:5;truncated=mode==2;
    int before=closed;bool rejected=false;
    try { ReadCommunityAsset(&manager,"model"); }catch(const std::runtime_error&) {rejected=true;}
    assert(rejected&&closed==before+(missing?0:1));
  }
  for(bool fail:{false,true}) {
    try {
      auto pending=std::make_unique<Work>();pending->operation=Operation::Load;
      pending->resource_manager.reset(new NativeResourceManager);++managers;
      pending->resource_env=&manager;pending->resource_ref=&manager;++references;
      assert(managers==1&&references==1); // Held for the pending native work.
      if(fail)throw std::runtime_error("queue or load failed");
      auto completed=std::move(pending);
    }catch(const std::runtime_error&) {}
    assert(managers==0&&references==0);
  }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'resource.cpp'
            binary = Path(directory) / 'resource'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', str(source),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_ohos_scheduling_scope_parses_and_restores_thread_state(self):
        # The host slices compile the non-OHOS branch, so the branch that actually
        # ships is otherwise never built. Compile it against platform stubs and
        # check the parser rejections plus set/restore of both mask and QoS.
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        source_text = (CPP / 'community_diarization.cpp').read_text()
        # Anchor on the scheduling section itself. The platform includes above it
        # also sit behind `#if defined(__OHOS__)`, so the first occurrence of that
        # guard is not this one.
        marker = source_text.index('// The engine-wide scheduling request')
        ohos_if = source_text.rindex('#if defined(__OHOS__)', 0, marker)
        constants = source_text[source_text.index('constexpr int kDefaultEncoderThreads'):ohos_if]
        ohos_start = source_text.index('namespace {', ohos_if)
        block = constants + source_text[ohos_start:source_text.index('#else', marker)]
        program = r'''
#include <cassert>
#include <sched.h>
#include <qos/qos.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
''' + block + r'''
int main() {
  assert(kDefaultEncoderThreads == 4 && kMaxEncoderThreads == 8);
  CommunityScheduling none;
  assert(!none.has_thread_policy());
  CommunityScheduling policy;
  ParseCommunityScheduling("AmphionQos=user-initiated;AmphionCpuIds=4,5", &policy);
  assert(policy.qos == QOS_USER_INITIATED && policy.cpu_ids.size() == 2);
  assert(policy.cpu_ids[0] == 4 && policy.cpu_ids[1] == 5 && policy.has_thread_policy());
  // An empty request must stay a no-op rather than clearing an earlier one.
  CommunityScheduling untouched;
  ParseCommunityScheduling("", &untouched);
  assert(!untouched.has_thread_policy());
  for (const char* bad : {"AmphionQos=realtime", "AmphionCpuIds=4,4", "AmphionCpuIds=9999",
                          "AmphionCpuIds=4,", "AmphionCpuIds=x"}) {
    CommunityScheduling rejected_policy;
    bool rejected = false;
    try { ParseCommunityScheduling(bad, &rejected_policy); }
    catch (const std::runtime_error&) { rejected = true; }
    assert(rejected);
  }
  // A scope must leave both the mask and the QoS exactly as it found them.
  StubMask() = cpu_set_t{};
  CPU_SET(1, &StubMask());
  StubQos() = QOS_USER_INTERACTIVE;
  {
    ScopedCommunityScheduling scope(policy);
    assert(StubQos() == QOS_USER_INITIATED);
    assert(CPU_ISSET(4, &StubMask()) && CPU_ISSET(5, &StubMask()));
    assert(!CPU_ISSET(1, &StubMask()));
  }
  assert(StubQos() == QOS_USER_INTERACTIVE);
  assert(CPU_ISSET(1, &StubMask()) && !CPU_ISSET(4, &StubMask()));
  // A borrowed thread whose previous QoS cannot be read must be left alone: a
  // reset on exit would discard a policy this module never learned.
  StubQos() = QOS_USER_INTERACTIVE;
  StubQosGetFails() = true;
  StubQosSetCalls() = 0;
  {
    ScopedCommunityScheduling scope(policy);
    assert(StubQosSetCalls() == 0 && "unknown previous QoS must not be overwritten");
    assert(StubQos() == QOS_USER_INTERACTIVE);
  }
  assert(StubQos() == QOS_USER_INTERACTIVE);
  assert(StubQosSetCalls() == 0 && "unknown previous QoS must not be reset");
  StubQosGetFails() = false;
  // A failed setter must not leave a restore behind either.
  StubQos() = QOS_USER_INTERACTIVE;
  StubQosSetFails() = true;
  {
    ScopedCommunityScheduling scope(policy);
    assert(StubQos() == QOS_USER_INTERACTIVE);
  }
  assert(StubQos() == QOS_USER_INTERACTIVE);
  StubQosSetFails() = false;
  // The same rule applies to the affinity mask.
  StubMask() = cpu_set_t{};
  CPU_SET(1, &StubMask());
  StubMaskGetFails() = true;
  {
    ScopedCommunityScheduling scope(policy);
    assert(CPU_ISSET(1, &StubMask()) && "unreadable mask must not be replaced");
  }
  assert(CPU_ISSET(1, &StubMask()));
  StubMaskGetFails() = false;
  StubMask() = cpu_set_t{};
  CPU_SET(1, &StubMask());
  StubMaskSetFails() = true;
  {
    ScopedCommunityScheduling scope(policy);
    assert(CPU_ISSET(1, &StubMask()));
  }
  assert(CPU_ISSET(1, &StubMask()) && "failed set must not restore anything");
  StubMaskSetFails() = false;
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'qos').mkdir()
            (root / 'qos/qos.h').write_text(
                'typedef enum { QOS_DEFAULT=0, QOS_USER_INITIATED=2, QOS_USER_INTERACTIVE=3 } QoS_Level;\n'
                'inline QoS_Level& StubQos(){ static QoS_Level v = QOS_DEFAULT; return v; }\n'
                'inline bool& StubQosGetFails(){ static bool v = false; return v; }\n'
                'inline bool& StubQosSetFails(){ static bool v = false; return v; }\n'
                'inline int& StubQosSetCalls(){ static int v = 0; return v; }\n'
                'inline int OH_QoS_GetThreadQoS(QoS_Level* level){ if (StubQosGetFails()) return -1;'
                ' *level = StubQos(); return 0; }\n'
                'inline int OH_QoS_SetThreadQoS(QoS_Level level){ ++StubQosSetCalls();'
                ' if (StubQosSetFails()) return -1; StubQos() = level; return 0; }\n'
                'inline int OH_QoS_ResetThreadQoS(){ StubQos() = QOS_DEFAULT; return 0; }\n')
            (root / 'sched.h').write_text(
                '#pragma once\n#include <cstddef>\n'
                '#define CPU_SETSIZE 1024\n'
                'typedef struct { unsigned char bits[CPU_SETSIZE/8]; } cpu_set_t;\n'
                'inline void CPU_ZERO(cpu_set_t* s){ for (size_t i=0;i<sizeof(s->bits);++i) s->bits[i]=0; }\n'
                'inline void CPU_SET(int cpu, cpu_set_t* s){ s->bits[cpu/8] |= (unsigned char)(1u<<(cpu%8)); }\n'
                'inline int CPU_ISSET(int cpu, const cpu_set_t* s){ return (s->bits[cpu/8]>>(cpu%8))&1u; }\n'
                'inline cpu_set_t& StubMask(){ static cpu_set_t m{}; return m; }\n'
                'inline bool& StubMaskGetFails(){ static bool v = false; return v; }\n'
                'inline bool& StubMaskSetFails(){ static bool v = false; return v; }\n'
                'inline int sched_getaffinity(int,size_t,cpu_set_t* s){ if (StubMaskGetFails()) return -1;'
                ' *s = StubMask(); return 0; }\n'
                'inline int sched_setaffinity(int,size_t,const cpu_set_t* s){ if (StubMaskSetFails()) return -1;'
                ' StubMask() = *s; return 0; }\n')
            source = root / 'scheduling.cpp'
            binary = root / 'scheduling'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(root),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_load_arguments_parse_threads_and_scheduling_together(self):
        # The caller always passes (resourceManager, threads, scheduling), so a
        # parser that only reads threads at exactly two arguments silently drops
        # the public SpeakerDiarizationConfig.numThreads. Run the production
        # Queue() against NAPI stubs and inspect the Work it builds.
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        source_text = (CPP / 'community_diarization.cpp').read_text()
        marker = source_text.index('// The engine-wide scheduling request')
        ohos_if = source_text.rindex('#if defined(__OHOS__)', 0, marker)
        constants = source_text[source_text.index('constexpr int kDefaultEncoderThreads'):ohos_if]
        ohos_body = source_text[source_text.index('namespace {', ohos_if):
                                source_text.index('#else', marker)]
        optional_string = source_text[source_text.index('std::string OptionalString('):
                                      source_text.index('\nvoid FloatProperty')]
        work = source_text[source_text.index('struct Work {'):source_text.index('\nvoid Execute')]
        queue = source_text[source_text.index('napi_value Queue('):source_text.index('\nnapi_value Load(')]
        program = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include <sched.h>
#include <qos/qos.h>
struct Value { int kind = 0; long long integer = 0; const char* text = nullptr; };
struct CallInfo { Value* const* args = nullptr; size_t count = 0; };
namespace {
using napi_env = void*;
using napi_value = Value*;
using napi_ref = void*;
using napi_deferred = void*;
using napi_async_work = void*;
using napi_callback_info = CallInfo*;
using napi_status = int;
using napi_typedarray_type = int;
constexpr int napi_ok = 0;
constexpr int napi_uint8_array = 1, napi_float32_array = 2, napi_float64_array = 3;
constexpr size_t NAPI_AUTO_LENGTH = 0;
void* g_pending = nullptr;
bool g_queue_failed = false;
int g_throw_calls = 0;
int napi_get_cb_info(napi_env, napi_callback_info info, size_t* argc, napi_value* argv,
                     napi_value*, void*) {
  size_t n = std::min(*argc, info->count);
  for (size_t i = 0; i < n; ++i) argv[i] = info->args[i];
  *argc = info->count;
  return napi_ok;
}
int napi_get_value_int32(napi_env, napi_value value, int32_t* out) {
  if (value == nullptr || value->kind != 1) return 1;
  *out = static_cast<int32_t>(value->integer);
  return napi_ok;
}
int napi_get_value_double(napi_env, napi_value, double* out) { *out = 0; return napi_ok; }
int napi_get_value_uint32(napi_env, napi_value, uint32_t* out) { *out = 0; return napi_ok; }
int napi_get_value_bool(napi_env, napi_value, bool* out) { *out = true; return napi_ok; }
int napi_get_value_string_utf8(napi_env, napi_value value, char* buffer, size_t size,
                               size_t* written) {
  if (value == nullptr || value->kind != 2) return 1;
  const size_t length = std::strlen(value->text);
  if (buffer == nullptr) { *written = length; return napi_ok; }
  const size_t copied = std::min(size - 1, length);
  std::memcpy(buffer, value->text, copied);
  buffer[copied] = '\0';
  *written = copied;
  return napi_ok;
}
int napi_create_reference(napi_env, napi_value, uint32_t, napi_ref* ref) {
  *ref = reinterpret_cast<void*>(1); return napi_ok;
}
int napi_delete_reference(napi_env, napi_ref) { return napi_ok; }
int napi_create_promise(napi_env, napi_deferred* deferred, napi_value* promise) {
  static Value value;
  *deferred = reinterpret_cast<void*>(1);
  *promise = &value;
  return napi_ok;
}
int napi_create_string_utf8(napi_env, const char*, size_t, napi_value* out) {
  static Value value; *out = &value; return napi_ok;
}
int napi_create_async_work(napi_env, napi_value, napi_value, void (*)(napi_env, void*),
                           void (*)(napi_env, napi_status, void*), void* data,
                           napi_async_work* handle) {
  g_pending = data; *handle = reinterpret_cast<void*>(1); return napi_ok;
}
int napi_queue_async_work(napi_env, napi_async_work) { return g_queue_failed ? 1 : napi_ok; }
int napi_delete_async_work(napi_env, napi_async_work) { return napi_ok; }
int napi_reject_deferred(napi_env, napi_deferred, napi_value) { return napi_ok; }
int napi_throw_error(napi_env, const char*, const char*) { ++g_throw_calls; return napi_ok; }
void Execute(napi_env, void*) {}
void Complete(napi_env, napi_status, void*) {}
struct NativeResourceManager {};
NativeResourceManager* OH_ResourceManager_InitNativeResourceManager(napi_env, napi_value) {
  static NativeResourceManager manager; return &manager;
}
void OH_ResourceManager_ReleaseNativeResourceManager(NativeResourceManager*) {}
enum class Operation { Load, Process, Cluster };
struct Model {}; struct Window {};
template <typename T> std::vector<T> CopyArray(napi_env, napi_value, napi_typedarray_type) {
  return std::vector<T>();
}
std::mutex model_mutex;
std::unordered_map<uint32_t, std::shared_ptr<Model>> models;
uint32_t next_handle = 1;
''' + constants + ohos_body + optional_string + work + queue + r'''
Work* Run(Operation operation, bool from_resources, Value* values, size_t count) {
  g_pending = nullptr; g_throw_calls = 0;
  Value* slots[10] = {};
  for (size_t index = 0; index < count; ++index) slots[index] = &values[index];
  CallInfo info{slots, count};
  napi_value result = Queue(nullptr, &info, operation, from_resources);
  (void)result;
  return static_cast<Work*>(g_pending);
}
}  // namespace
int main() {
  Value values[7] = {};
  for (int index = 0; index < 7; ++index) {
    values[index].kind = 1;
    values[index].integer = 9;
  }
  Value threads, scheduling;
  threads.kind = 1;
  scheduling.kind = 2;

  values[0].kind = 0;                       // resource manager handle
  threads.integer = 2;

  // One argument keeps the documented default.
  Work* work = Run(Operation::Load, true, values, 1);
  assert(work != nullptr && work->encoder_threads == kDefaultEncoderThreads);
  assert(work->scheduling.qos < 0 && work->scheduling.cpu_ids.empty());
  delete work;

  // Two arguments carry the budget.
  values[1] = threads;
  work = Run(Operation::Load, true, values, 2);
  assert(work != nullptr && work->encoder_threads == 2);
  assert(work->scheduling.qos < 0 && work->scheduling.cpu_ids.empty());
  delete work;

  // Three arguments carry the budget AND the scheduling request. This is the
  // shape every Harmony caller uses, empty request included.
  scheduling.text = "";
  values[2] = scheduling;
  work = Run(Operation::Load, true, values, 3);
  assert(work != nullptr && work->encoder_threads == 2 && "threads must survive a third argument");
  assert(work->scheduling.qos < 0 && work->scheduling.cpu_ids.empty());
  delete work;

  scheduling.text = "AmphionQos=user-initiated;AmphionCpuIds=4,5";
  values[2] = scheduling;
  threads.integer = 3;
  values[1] = threads;
  work = Run(Operation::Load, true, values, 3);
  assert(work != nullptr && work->encoder_threads == 3);
  assert(work->scheduling.qos == QOS_USER_INITIATED);
  assert(work->scheduling.cpu_ids.size() == 2 && work->scheduling.cpu_ids[0] == 4);
  delete work;

  // A malformed budget must be reported, not replaced by the default.
  values[1].kind = 0;
  assert(Run(Operation::Load, true, values, 2) == nullptr && g_throw_calls == 1);

  // The asset path keeps the same rule at five, six and seven arguments.
  values[1].kind = 1; values[1].integer = 2;
  values[5] = threads;
  values[6] = scheduling;
  work = Run(Operation::Load, false, values, 5);
  assert(work != nullptr && work->encoder_threads == kDefaultEncoderThreads);
  delete work;
  work = Run(Operation::Load, false, values, 6);
  assert(work != nullptr && work->encoder_threads == 3);
  assert(work->scheduling.qos < 0);
  delete work;
  work = Run(Operation::Load, false, values, 7);
  assert(work != nullptr && work->encoder_threads == 3 && "threads must survive a seventh argument");
  assert(work->scheduling.qos == QOS_USER_INITIATED && work->scheduling.cpu_ids.size() == 2);
  delete work;
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'qos').mkdir()
            (root / 'qos/qos.h').write_text(
                'typedef enum { QOS_DEFAULT=0, QOS_USER_INITIATED=2, QOS_USER_INTERACTIVE=3 } QoS_Level;\n'
                'inline int OH_QoS_GetThreadQoS(QoS_Level* level){ *level = QOS_DEFAULT; return 0; }\n'
                'inline int OH_QoS_SetThreadQoS(QoS_Level){ return 0; }\n'
                'inline int OH_QoS_ResetThreadQoS(){ return 0; }\n')
            (root / 'sched.h').write_text(
                '#pragma once\n#include <cstddef>\n'
                '#define CPU_SETSIZE 1024\n'
                'typedef struct { unsigned char bits[CPU_SETSIZE/8]; } cpu_set_t;\n'
                'inline void CPU_ZERO(cpu_set_t* s){ for (size_t i=0;i<sizeof(s->bits);++i) s->bits[i]=0; }\n'
                'inline void CPU_SET(int, cpu_set_t*) {}\n'
                'inline int sched_getaffinity(int,size_t,cpu_set_t* s){ CPU_ZERO(s); return 0; }\n'
                'inline int sched_setaffinity(int,size_t,const cpu_set_t*){ return 0; }\n')
            source = root / 'queue.cpp'
            binary = root / 'queue'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O1', '-I', str(root),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_platform_headers_are_included_outside_every_namespace(self):
        # Including <sched.h>/<qos/qos.h> from inside an anonymous namespace is
        # ill-formed. The compile tests paste their own includes first, so only a
        # structural check can catch a regression here.
        text = (CPP / 'community_diarization.cpp').read_text()
        first_namespace = text.index('namespace {')
        for header in ('#include <sched.h>', '#include <qos/qos.h>'):
            self.assertLess(text.index(header), first_namespace,
                            f'{header} must precede the first namespace')

    def test_encoder_features_and_run_vectors_belong_to_one_window(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        source = (CPP / 'community_diarization.cpp').read_text()
        body = source[source.index('    std::array<int64_t, 3> feature_shape'):
                      source.index('    result.embedding_ms = Milliseconds(start);')]
        # Execute production run extraction with a mask-independent model stub.
        # The pinned ONNX graph pools each mask channel independently as well.
        program = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>
namespace Ort {
struct RunOptions { RunOptions(std::nullptr_t) {} };
struct Value {
  std::vector<float> values;
  template<class T> static Value CreateTensor(int,T* data,size_t n,const int64_t*,size_t) {
    return {std::vector<float>(data,data+n)};
  }
  struct Info { size_t count;size_t GetElementCount() const {return count;} };
  Info GetTensorTypeAndShapeInfo() const {return {values.size()};}
  template<class T> const T* GetTensorData() const {return values.data();}
  template<class T> T* GetTensorMutableData() {return values.data();}
};
}
float MaskValue(const std::vector<float>& mask,int channel,float pcm) {
  float value=pcm;
  for(int f=0;f<589;++f)value+=mask[channel*589+f]*(f+1);
  return value;
}
static int encoderCalls=0;
struct Encoder {
  int calls=0;bool encoderOnly=false;
  std::vector<Ort::Value> Run(Ort::RunOptions,const char** names,Ort::Value* inputs,size_t,const char**,size_t) {
    ++calls;Ort::Value out;
    if(std::string(names[0])=="fbank")++encoderCalls;
    if(encoderOnly) {out.values.assign(2560*125,inputs[0].values[0]);return {out};}
    out.values.resize(768);
    for(int c=0;c<3;++c)std::fill_n(out.values.begin()+c*256,256,
      MaskValue(inputs[1].values,c,inputs[0].values[0]));
    return {out};
  }
} embedding_, encoder_{0,true}, pooling_;
struct Window {std::vector<float> embeddings,run_embeddings,run_ranges,run_rms;};
Window ProcessRuns(std::vector<float> masks,std::vector<float> clean,float level,bool varied=false) {
  Window result;
  std::vector<float> features{level},pcm(160000,level);int memory=0;
  if(varied){
    std::fill(pcm.begin(),pcm.end(),100.f); // Loud unowned context must be ignored.
    std::fill(pcm.begin()+496,pcm.begin()+496+130*270,.125f);
    std::fill(pcm.begin()+496+131*270,pcm.begin()+496+261*270,.5f);
  }
  struct Clock { static int now() {return 0;} };int start=0;
''' + body + r'''
  return result;
}
void On(std::vector<float>& m,int channel,int b,int e) {
  std::fill(m.begin()+channel*589+b,m.begin()+channel*589+e,1.f);
}
int main() {
  std::vector<float> masks(1767);On(masks,0,0,180);On(masks,1,200,340);
  auto same=ProcessRuns(masks,masks,3);
  assert(same.run_ranges==std::vector<float>({0,0,0,180,0,1,200,340}));
  assert(same.run_embeddings.size()==512);
  assert(same.run_rms==std::vector<float>({3,3}));
  for(int i=0;i<256;++i) {
    assert(same.run_embeddings[i]==same.embeddings[i]);
    assert(same.run_embeddings[256+i]==same.embeddings[256+i]);
  }
  assert(encoderCalls==1 && "one encoder per window");
  auto next=ProcessRuns(masks,masks,7);
  assert(next.run_embeddings[0]==same.run_embeddings[0]+4 && "never reuse another window PCM");
  assert(next.run_rms==std::vector<float>({7,7}));
  std::vector<float> mixed(1767);On(mixed,0,0,130);On(mixed,0,131,261);
  auto split=ProcessRuns(mixed,mixed,3);
  assert(encoderCalls==3 && "disconnected runs share only this window encoder");
  assert(split.run_ranges==std::vector<float>({0,0,0,130,0,0,131,261}));
  std::vector<float> left(1767),right(1767);On(left,0,0,130);On(right,0,131,261);
  assert(split.run_embeddings[0]==MaskValue(left,0,3));
  assert(split.run_embeddings[256]==MaskValue(right,0,3));
  assert(split.run_embeddings[0]!=split.embeddings[0]);
  std::vector<float> tail(1767);On(tail,0,0,150);On(tail,0,300,320);
  auto withShortTail=ProcessRuns(tail,tail,3);
  std::vector<float> mainRun(1767);On(mainRun,0,0,150);
  assert(encoderCalls==4);
  assert(withShortTail.run_embeddings[0]==MaskValue(mainRun,0,3));
  assert(withShortTail.run_embeddings[0]!=withShortTail.embeddings[0]);
  assert(withShortTail.run_embeddings[256]==0);
  std::vector<float> shortMask(1767);On(shortMask,0,0,80);
  auto shortRun=ProcessRuns(shortMask,shortMask,3);
  assert(encoderCalls==5 && shortRun.run_embeddings==std::vector<float>(256,0));
  auto overlap=ProcessRuns(masks,std::vector<float>(1767),3);
  assert(encoderCalls==6 && overlap.run_embeddings.size()==512);
  for(float v:overlap.run_embeddings)assert(std::isnan(v));
  assert(overlap.run_rms==std::vector<float>({0,0}));
  auto levels=ProcessRuns(mixed,mixed,3,true);
  assert(levels.run_rms==std::vector<float>({.125f,.5f}));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'run-mask.cpp'
            binary = Path(directory) / 'run-mask'
            cpp.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_native_input_copy_uses_real_view_bounds(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        source_text = (CPP / 'community_diarization.cpp').read_text()
        copy_array = source_text[source_text.index('template <typename T>'):
                                 source_text.index('\n#endif', source_text.index('template <typename T>'))]
        # Compile the real bridge copy function. Only the platform N-API boundary
        # is substituted; both native length conventions must bound the copy.
        program = r'''
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>
#include <cassert>
using napi_env=void*;
using napi_value=void*;
enum napi_status { napi_ok,napi_invalid_arg };
enum napi_typedarray_type { napi_float32_array,napi_uint8_array };
struct View {
  napi_typedarray_type type;size_t length;void* data;uint32_t viewBytes;
  void* backing;size_t backingBytes;size_t offset;
};
napi_status napi_get_typedarray_info(napi_env,napi_value value,napi_typedarray_type* type,
 size_t* length,void** data,napi_value* buffer,size_t* offset) {
  if(!value)return napi_invalid_arg;
  auto* v=static_cast<View*>(value);
  *type=v->type;*length=v->length;*data=v->data;*buffer=value;*offset=v->offset;return napi_ok;
}
napi_status napi_get_named_property(napi_env,napi_value value,const char*,napi_value* out) {
  *out=value;return napi_ok;
}
napi_status napi_get_value_uint32(napi_env,napi_value value,uint32_t* out) {
  *out=static_cast<View*>(value)->viewBytes;return napi_ok;
}
napi_status napi_get_arraybuffer_info(napi_env,napi_value value,void** data,size_t* bytes) {
  auto* v=static_cast<View*>(value);*data=v->backing;*bytes=v->backingBytes;return napi_ok;
}
''' + copy_array + r'''
int main() {
  float backing[]={-99.f,.125f,.25f,99.f};
  View view{napi_float32_array,2,backing+1,8,backing,sizeof(backing),4};
  assert(CopyArray<float>(nullptr,&view,napi_float32_array)==std::vector<float>({.125f,.25f}));
  view.length=8; // Harmony's byte-count convention.
  assert(CopyArray<float>(nullptr,&view,napi_float32_array)==std::vector<float>({.125f,.25f}));
  uint8_t bytes[]={99,1,2,3,99};
  View model{napi_uint8_array,3,bytes+1,3,bytes,sizeof(bytes),1};
  assert(CopyArray<uint8_t>(nullptr,&model,napi_uint8_array)==std::vector<uint8_t>({1,2,3}));
  View empty{napi_float32_array,0,nullptr,0,nullptr,0,0};
  assert(CopyArray<float>(nullptr,&empty,napi_float32_array).empty());
  bool wrongType=false,invalid=false;
  try { CopyArray<float>(nullptr,&model,napi_float32_array); }
  catch(const std::runtime_error&) { wrongType=true; }
  try { CopyArray<float>(nullptr,nullptr,napi_float32_array); }
  catch(const std::runtime_error&) { invalid=true; }
  assert(wrongType&&invalid);
  // Shadowed metadata must not authorize a read outside the actual backing
  // allocation; offsets are checked before subtracting to avoid underflow.
  for(View bad: std::vector<View>{
      {napi_float32_array,2,backing+1,4,backing,sizeof(backing),4},
      {napi_float32_array,8,backing+1,32,backing,sizeof(backing),4},
      {napi_float32_array,2,backing+1,8,backing,sizeof(backing),20}}) {
    bool rejected=false;
    try { CopyArray<float>(nullptr,&bad,napi_float32_array); }
    catch(const std::runtime_error&) { rejected=true; }
    assert(rejected);
  }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'array.cpp'
            binary = Path(directory) / 'array'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', str(source),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_long_meeting_clustering_keeps_labels_with_bounded_work_memory(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        # Count live allocations in the clustering call, independently of RSS
        # accounting on the host. The previous all-pairs heap exceeds 100 MiB.
        program = r'''
#include <cstddef>
#include <cstdlib>
#include <new>
struct alignas(std::max_align_t) Allocation { size_t bytes; };
static size_t liveBytes=0,peakBytes=0;
void* operator new(size_t bytes) {
  auto* p=static_cast<Allocation*>(std::malloc(sizeof(Allocation)+bytes));
  if(!p)throw std::bad_alloc();
  p->bytes=bytes;liveBytes+=bytes;if(liveBytes>peakBytes)peakBytes=liveBytes;
  return p+1;
}
void operator delete(void* value) noexcept {
  if(!value)return;
  auto* p=static_cast<Allocation*>(value)-1;liveBytes-=p->bytes;std::free(p);
}
void* operator new[](size_t bytes) { return ::operator new(bytes); }
void operator delete[](void* value) noexcept { ::operator delete(value); }
void operator delete(void* value,size_t) noexcept { ::operator delete(value); }
void operator delete[](void* value,size_t) noexcept { ::operator delete(value); }
#include "community_cluster.h"
#include <cassert>
int main() {
  // Equal distances and duplicate vectors retain the original public ordering.
  community::Matrix tied(8,community::Vec(4));
  for(int i=0;i<8;++i)tied[i][i%4]=1.;
  assert(community::Ahc(tied)==std::vector<int>({2,3,1,0,2,3,1,0}));
  // The last centroid merge is shorter than its child merge. It must not
  // erase that child's above-cut distance and collapse three distinct voices.
  community::Matrix inversion(3,community::Vec(3));
  for(int i=0;i<3;++i) {
    double angle=2*std::acos(-1.)*i/3;
    inversion[i]={std::sqrt(1-.35*.35),.35*std::cos(angle),.35*std::sin(angle)};
  }
  auto separate=community::Ahc(inversion);
  assert(separate[0]!=separate[1]&&separate[0]!=separate[2]&&separate[1]!=separate[2]);
  constexpr int n=2048;
  community::Matrix x(n,community::Vec(256));
  for(int i=0;i<n;++i) {
    for(int j=0;j<256;++j)x[i][j]=.02*std::sin((i+1.)*(j+1.));
    x[i][i%4]=1.;
  }
  size_t before=liveBytes;peakBytes=before;
  auto labels=community::Ahc(x);
  assert(peakBytes-before<32u*1024u*1024u);
  assert(labels.size()==n);
  for(int i=0;i<n;++i)assert(labels[i]==labels[i%4]);
  for(int i=0;i<4;++i)for(int j=i+1;j<4;++j)assert(labels[i]!=labels[j]);
  // A corrupt zero-norm embedding must fail instead of stalling the worker.
  bool rejected=false;
  try { community::Ahc(community::Matrix(2,community::Vec(256))); }
  catch(const std::runtime_error&) { rejected=true; }
  assert(rejected);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'memory.cpp'
            binary = Path(directory) / 'memory'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_reconstruction_uses_recorded_starts_after_hop_change_and_pruning(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  std::vector<float> speech(20*589*3);
  std::vector<int> hard(20*3,-2);
  std::vector<double> starts;
  for(int w=0;w<20;++w){
    starts.push_back(w*32000);hard[w*3]=0;
    for(int f=0;f<589;++f)speech[(w*589+f)*3]=1;
  }
  auto turns=community::Reconstruct(speech,hard,starts,0);
  assert(turns.size()==1 && turns[0].speaker==0 && turns[0].end>47.8);
  // A retained enrollment window must not shift a later batch or allocate
  // a reconstruction timeline for the entire elapsed session.
  starts={0,16000.*3600,16000.*3604};
  speech.resize(3*589*3);hard.resize(9);
  turns=community::Reconstruct(speech,hard,starts,16000.*3600);
  assert(turns.size()==1 && turns[0].begin>=3600 && turns[0].end>3613.8);
  starts={16000.*3600,16000.*3604};speech.resize(2*589*3);hard.resize(6);
  auto pruned=community::Reconstruct(speech,hard,starts,16000.*3600);
  assert(pruned.size()==turns.size());
  assert(pruned[0].begin==turns[0].begin && pruned[0].end==turns[0].end);
  // Missing intermediate jobs are acoustic gaps, never compressed time.
  starts={0,16000.*20};
  turns=community::Reconstruct(speech,hard,starts,0);
  assert(turns.size()==2 && turns[0].end<10.1 && turns[1].begin>19.9);
  bool rejected=false;
  try { community::Reconstruct(speech,hard,{0},0); }
  catch(const std::runtime_error&) { rejected=true; }
  assert(rejected);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'timeline.cpp'
            binary = Path(directory) / 'timeline'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_frame_reconstruction_keeps_disconnected_runs_separate(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  std::vector<float> segments(589*3);
  for(int f=20;f<180;++f)segments[f*3]=1;
  for(int f=300;f<460;++f)segments[f*3]=1;
  std::vector<int> hard={0,-2,-2};
  std::vector<int> frame(589*3,-2);
  for(int f=20;f<180;++f)frame[f*3]=0;
  for(int f=300;f<460;++f)frame[f*3]=1;
  auto turns=community::Reconstruct(segments,hard,{0},0,4,frame);
  assert(turns.size()==2);
  assert(turns[0].speaker==0 && turns[1].speaker==1);
  assert(turns[0].end<turns[1].begin);
  // Unknown frames remain anonymous even when the old per-channel label is
  // known; a short or ambiguous run must not inherit the mixed vector.
  frame.assign(589*3,-2);
  auto unknown=community::Reconstruct(segments,hard,{0},0,4,frame);
  assert(unknown.size()==2);
  assert(unknown[0].speaker==-1 && unknown[1].speaker==-1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'frame-runs.cpp'
            binary = Path(directory) / 'frame-runs'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_run_embeddings_split_a_channel_before_clustering(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  community::Plda p;
  p.mean1=community::Vec(256);p.mean2=community::Vec(128);p.mu=community::Vec(128);
  p.phi=community::Vec(128,1.);p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1.;p.transform[i][i]=1.;}
  std::vector<float> segments(589*3),embeddings(768),runs(768);
  for(int f=10;f<180;++f)segments[f*3]=1;
  for(int f=300;f<470;++f)segments[f*3]=1;
  for(int f=100;f<300;++f)segments[f*3+1]=1;
  runs[0]=1.;runs[256+1]=1.;
  std::fill(runs.begin()+512,runs.end(),std::numeric_limits<float>::quiet_NaN());
  std::vector<int32_t> ranges={0,0,10,180,0,0,300,470,0,1,100,300};
  auto result=community::Cluster(segments,embeddings,1,p,4,runs,ranges);
  assert(result.trainingRunIndices.size()==2);
  assert(result.shortRunTrainingCount==0 && !result.usedAhcFallback);
  assert(result.frame_hard.size()==589*3);
  assert(result.frame_hard[20*3]>=0 && result.frame_hard[320*3]>=0);
  assert(result.frame_hard[20*3]!=result.frame_hard[320*3]);
  assert(result.frame_hard[120*3+1]==-2);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'cluster-runs.cpp'
            binary = Path(directory) / 'cluster-runs'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_speech_without_run_evidence_falls_back_to_channel_vector(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  community::Plda p;
  p.mean1=community::Vec(256);p.mean2=community::Vec(128);p.mu=community::Vec(128);
  p.phi=community::Vec(128,1.);p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1.;p.transform[i][i]=1.;}
  // Two long voices overlap at 250..300; a short clean run on channel 2
  // sounds like voice A, so it opens no identity and has no run vector.
  std::vector<float> segments(589*3),embeddings(768),runs(3*256);
  for(int f=10;f<300;++f)segments[f*3]=1;
  for(int f=250;f<500;++f)segments[f*3+1]=1;
  for(int f=520;f<560;++f)segments[f*3+2]=1;
  embeddings[0]=1.;embeddings[256+1]=1.;embeddings[512]=1.;
  runs[0]=1.;runs[256+1]=1.;
  std::vector<int32_t> ranges={0,0,10,250,0,1,300,500,0,2,520,560};
  auto result=community::Cluster(segments,embeddings,1,p,4,runs,ranges);
  assert(result.centroids.size()==2 && result.shortRunTrainingCount==0);
  const int a=result.frame_hard[20*3],b=result.frame_hard[400*3+1];
  assert(a>=0 && b>=0 && a!=b);
  // Overlap frames keep their channel identity instead of staying anonymous.
  for(int f=250;f<300;++f)assert(result.frame_hard[f*3]==a && result.frame_hard[f*3+1]==b);
  // The unadmitted short run is named from its channel's full-window vector.
  for(int f=520;f<560;++f)assert(result.frame_hard[f*3+2]==a);
  // Window identities used by the public registry still come from run evidence only.
  assert(result.hard==std::vector<int>({a,b,-2}));
  auto turns=community::Reconstruct(segments,result.hard,{0},0,4,result.frame_hard);
  for(const auto& turn:turns)assert(turn.speaker>=0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'fallback.cpp'
            binary = Path(directory) / 'fallback'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_missing_enrollment_keeps_unknown_speech_and_overlap(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  community::Plda p;
  std::vector<float> segments(589*3);
  std::vector<float> unavailable(768,std::numeric_limits<float>::quiet_NaN());
  for(int frame=10;frame<30;++frame)segments[frame*3]=1;
  for(int frame=15;frame<20;++frame)segments[frame*3+1]=1;
  auto unknown=community::Cluster(segments,unavailable,1,p,4);
  assert(unknown.trainingIndices.empty());
  assert(unknown.centroids.empty());
  for(int label:unknown.hard)assert(label<0);
  auto turns=community::Reconstruct(segments,unknown.hard,{0},0);
  assert(turns.size()==2);
  for(const auto& turn:turns)assert(turn.speaker==-1);
  assert(turns[0].begin<turns[1].end && turns[1].begin<turns[0].end);
  auto silence=community::Cluster(std::vector<float>(589*3),unavailable,1,p,4);
  assert(community::Reconstruct(std::vector<float>(589*3),silence.hard,{0},0).empty());
  // A later call with real enrollment evidence still names that voice.
  std::vector<float> speech(589*3),valid(768);
  for(int frame=100;frame<300;++frame)speech[frame*3+2]=1;
  valid[512]=1;
  auto known=community::Cluster(speech,valid,1,p,4);
  assert(known.trainingIndices.size()==1 && known.trainingIndices[0]==2);
  assert(known.centroids.size()==1 && known.centroids[0][0]==1);
  auto named=community::Reconstruct(speech,known.hard,{0},0);
  assert(named.size()==1 && named[0].speaker==0);
  // A single enrolled voice must not erase a simultaneous unenrolled voice.
  // The upstream reconstruction pads zero-score tracks to the observed count.
  for(int frame=150;frame<170;++frame)speech[frame*3+1]=1;
  auto partial=community::Reconstruct(speech,{-2,-2,0},{0},0);
  assert(partial.size()==2);
  int namedCount=0,unknownCount=0;
  for(const auto& turn:partial) {
    if(turn.speaker==0) { ++namedCount;assert(turn.begin==named[0].begin && turn.end==named[0].end); }
    else { ++unknownCount;assert(turn.speaker==-1 && turn.begin>named[0].begin && turn.end<named[0].end); }
  }
  assert(namedCount==1 && unknownCount==1);
  auto capped=community::Reconstruct(speech,{-2,-2,0},{0},0,1);
  assert(capped.size()==1 && capped[0].speaker==0);
  assert(capped[0].begin==named[0].begin && capped[0].end==named[0].end);
  auto anonymousCapped=community::Reconstruct(segments,unknown.hard,{0},0,1);
  assert(anonymousCapped.size()==1 && anonymousCapped[0].speaker==-1);
  // Two named voices plus a third anonymous one retain all three tracks.
  for(int frame=155;frame<165;++frame)speech[frame*3]=1;
  auto three=community::Reconstruct(speech,{-2,1,0},{0},0);
  assert(three.size()==3);
  std::vector<int> speakers;
  for(const auto& turn:three)speakers.push_back(turn.speaker);
  std::sort(speakers.begin(),speakers.end());
  assert(speakers==std::vector<int>({-1,0,1}));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'unknown.cpp'
            binary = Path(directory) / 'unknown'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_short_turns_without_identity_evidence_are_not_painted_with_known_id(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main(int argc,char**) {
  // One short voice followed by a different, enrollment-eligible voice.
  // A single training vector does not make every local track that person.
  std::vector<float> segments(589*3), embeddings(768);
  for(int f=50;f<110;++f)segments[f*3+1]=1;
  for(int f=290;f<435;++f)segments[f*3+2]=1;
  embeddings[256]=1;embeddings[513]=1;
  auto cluster=community::Cluster(segments,embeddings,1,community::Plda{},4);
  assert(cluster.trainingIndices==std::vector<int>({2}));
  if(argc==1)assert(cluster.hard==std::vector<int>({-2,-2,0}));

  // Recorded failure: after clustering returns fewer identities than local
  // voices, voice count alone must not supply an identity with score zero.
  auto turns=community::Reconstruct(segments,{-2,-2,0},{0},0);
  assert(turns.size()==2 && turns[0].speaker==-1 && turns[1].speaker==0);
  assert(turns[0].end<turns[1].begin);
  // The speaker cap limits simultaneous output, not whether silence between
  // an enrolled voice's turns can be occupied by an anonymous voice.
  std::fill(segments.begin(),segments.end(),0);
  for(int f=30;f<80;++f)segments[f*3]=1;
  for(int f=100;f<150;++f)segments[f*3+1]=1;
  for(int f=170;f<220;++f)segments[f*3]=1;
  auto separated=community::Reconstruct(segments,{0,-2,-2},{0},0,1);
  assert(separated.size()==3);
  assert(separated[0].speaker==0 && separated[1].speaker==-1 && separated[2].speaker==0);
  // Nonzero acoustic support remains valid: the same voice in two windows
  // must not become unknown just because another window lacks its assignment.
  std::vector<float> repeated(2*589*3);
  for(int w=0;w<2;++w)for(int f=30;f<80;++f)repeated[(w*589+f)*3]=1;
  auto supported=community::Reconstruct(repeated,{0,-2,-2,-2,-2,-2},{0,0},0);
  assert(supported.size()==1 && supported[0].speaker==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'short-turns.cpp'
            binary = Path(directory) / 'short-turns'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            for args in [[], ['reconstruction']]:
                with self.subTest(stage=args or 'single-enrollment'):
                    subprocess.run([str(binary), *args], check=True)

    def test_isolated_short_run_can_open_one_ahc_identity_without_exceeding_cap(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        # Three repeated eligible runs establish three acoustic groups.  The
        # first short run is the only clean evidence for a fourth group and is
        # admitted through the masked full-window vector.  A later unrelated
        # short run would create a fifth group and must not open an identity;
        # like the official pipeline, its speech falls back to the nearest
        # existing identity without becoming window evidence. The
        # PLDA supports these distinct groups. No voice data or expected
        # speaker count is supplied to the clusterer.
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  community::Plda p;
  p.mean1=community::Vec(256);p.mean2=community::Vec(128);p.mu=community::Vec(128);
  p.phi=community::Vec(128,1.);p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1.;p.transform[i][i]=1.;}
  constexpr int windows=3;
  std::vector<float> segments(windows*589*3),embeddings(windows*3*256),runEmbeddings;
  std::vector<int32_t> ranges;
  auto run=[&](int w,int ch,int begin,int end,int axis){
    for(int f=begin;f<end;++f)segments[(w*589+f)*3+ch]=1;
    embeddings[(w*3+ch)*256+axis]=1;
    runEmbeddings.resize(runEmbeddings.size()+256);runEmbeddings[runEmbeddings.size()-256+axis]=1;
    ranges.insert(ranges.end(),{w,ch,begin,end});
  };
  run(0,0,0,130,0);run(0,1,150,280,1);run(0,2,300,430,2);
  run(1,0,0,68,3);run(1,1,150,280,1);run(1,2,300,430,2);
  run(2,0,0,68,4);
  auto result=community::Cluster(segments,embeddings,windows,p,4,runEmbeddings,ranges);
  assert(result.shortRunTrainingCount==1);
  assert(result.centroids.size()==4);
  assert(result.frame_hard[20*3]>=0);
  assert(result.frame_hard[20*3+3*589]>=0);
  assert(result.hard[6]==-2 && result.frame_hard[20*3+6*589]>=0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'short-enrollment.cpp'
            binary=Path(directory)/'short-enrollment'
            source.write_text(program)
            subprocess.run([compiler,'-std=c++17','-O2','-I',str(CPP),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

    def test_saturated_short_tail_does_not_repeat_training(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        # Count fitted rows in an isolated header, not wall-clock time. Extending
        # a saturated input with evidence that cannot be admitted must preserve
        # identities without repeating the same training for every short tail.
        header = (CPP / 'community_cluster.h').read_text()
        entry = 'inline std::vector<int> Ahc(const Matrix& x) {'
        self.assertEqual(header.count(entry), 1)
        instrumented = header.replace(entry, 'inline size_t fittedRows=0;\n' + entry +
                                      '\n  fittedRows+=x.size();')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  community::Plda p;
  p.mean1=community::Vec(256);p.mean2=community::Vec(128);p.mu=community::Vec(128);
  p.phi=community::Vec(128,1.);p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1.;p.transform[i][i]=1.;}
  for(bool initiallyFull:{false,true}) {
    std::vector<float> segments(2*589*3),embeddings(2*3*256),runs;
    std::vector<int32_t> ranges;
    auto add=[&](int w,int ch,int begin,int end,int axis) {
      for(int f=begin;f<end;++f)segments[(w*589+f)*3+ch]=1;
      embeddings[(w*3+ch)*256+axis]=1;
      runs.resize(runs.size()+256);
      if(end-begin>=118)runs[runs.size()-256+axis]=1;
      ranges.insert(ranges.end(),{w,ch,begin,end});
    };
    add(0,0,0,130,0);add(0,1,150,280,1);add(0,2,300,430,2);
    add(1,0,0,initiallyFull?130:68,3);
    add(1,1,150,280,1);add(1,2,300,430,2);
    community::fittedRows=0;
    auto before=community::Cluster(segments,embeddings,2,p,4,runs,ranges);
    const auto fitWork=community::fittedRows;
    assert(before.centroids.size()==4);
    assert(before.shortRunTrainingCount==(initiallyFull?0:1));
    constexpr int windows=34;
    segments.resize(windows*589*3);embeddings.resize(windows*3*256);
    for(int w=2;w<windows;++w)add(w,0,0,68,w+2);
    community::fittedRows=0;
    auto after=community::Cluster(segments,embeddings,windows,p,4,runs,ranges);
    assert(after.trainingRunIndices==before.trainingRunIndices);
    assert(after.ahc==before.ahc && after.vbx.q==before.vbx.q);
    assert(after.centroids==before.centroids);
    assert(std::equal(before.frame_hard.begin(),before.frame_hard.end(),after.frame_hard.begin()));
    for(int w=2;w<windows;++w)assert(after.hard[w*3]==-2 && after.frame_hard[(w*589+20)*3]>=0);
    assert(community::fittedRows==fitWork);
  }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            (local / 'community_cluster.h').write_text(instrumented)
            source = local / 'saturated-tail.cpp'
            binary = local / 'saturated-tail'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(local),
                            '-I', str(CPP), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_short_enrollment_owns_the_full_embedding_mask(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        # Process pools the original channel mask when clean coverage is only
        # one or two frames. A unique clean run does not then own the vector
        # if this channel also contains overlap. Pure short evidence must
        # remain eligible; this is not a minimum-duration rule.
        program = r'''
#include "community_cluster.h"
#include <cassert>
community::Plda Plda() {
  community::Plda p;
  p.mean1=community::Vec(256);p.mean2=community::Vec(128);p.mu=community::Vec(128);
  p.phi=community::Vec(128,1.);p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1.;p.transform[i][i]=1.;}
  return p;
}
community::ClusterResult Run(int cleanFrames,bool overlap) {
  std::vector<float> seg(2*589*3),full(2*3*256),runs(2*256,0.f);
  std::vector<int32_t> ranges{0,0,0,150,1,0,0,cleanFrames};
  for(int f=0;f<150;++f)seg[f*3]=1.f;
  for(int f=0;f<cleanFrames;++f)seg[(589+f)*3]=1.f;
  if(overlap) {
    for(int f=cleanFrames;f<cleanFrames+22;++f){
      seg[(589+f)*3]=1.f;seg[(589+f)*3+1]=1.f;
    }
    if(cleanFrames<=2){
      ranges.insert(ranges.end(),{1,0,cleanFrames,cleanFrames+22});
      runs.insert(runs.end(),256,NAN);
    }
    ranges.insert(ranges.end(),{1,1,cleanFrames,cleanFrames+22});
    runs.insert(runs.end(),256,NAN);
  }
  full[0]=1.f;full[3*256+1]=1.f;runs[0]=1.f;
  return community::Cluster(seg,full,2,Plda(),4,runs,ranges);
}
int main() {
  for(int n:{1,2}) {
    auto mixed=Run(n,true);
    assert(mixed.centroids.size()==1 && "overlap vector must not manufacture a short identity");
    // Its speech falls back to the existing identity but is not window evidence.
    assert(mixed.hard[3]==-2);
    for(int f=0;f<n;++f)assert(mixed.frame_hard[(589+f)*3]==mixed.frame_hard[0]);
  }
  for(int n:{1,2,3,80})for(bool overlap:{false,true}) {
    if(overlap&&n<=2)continue;
    auto clean=Run(n,overlap);
    assert(clean.centroids.size()==2 && "owned short speaker evidence must survive");
    int label=clean.frame_hard[589*3];assert(label>=0&&label!=clean.frame_hard[0]);
    for(int f=0;f<n;++f)assert(clean.frame_hard[(589+f)*3]==label);
    if(overlap)for(int f=n;f<n+22;++f)assert(clean.frame_hard[(589+f)*3+1]==-2);
  }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'short-mask.cpp';binary=Path(directory)/'short-mask'
            source.write_text(program)
            subprocess.run([compiler,'-std=c++17','-O2','-I',str(CPP),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

    def test_short_admission_does_not_split_long_runs_merged_by_vbx(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        # The long runs have two AHC groups but one VBx identity. A new short
        # candidate must not resurrect the discarded long-run group. This is
        # the state fork seen in the confirmed single-speaker recording.
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  community::Plda p;
  p.mean1=community::Vec(256);p.mean2=community::Vec(128);p.mu=community::Vec(128);
  p.phi=community::Vec(128,10.);p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1.;p.transform[i][i]=1.;}
  constexpr int windows=6;
  std::vector<float> segments(windows*589*3),embeddings(windows*3*256),runEmbeddings;
  std::vector<int32_t> ranges;
  for(int w=0;w<windows;++w){
    const int axis=w<4?0:w-3, end=w==5?68:200;
    for(int f=0;f<end;++f)segments[(w*589+f)*3]=1;
    embeddings[w*3*256+axis]=1;
    runEmbeddings.resize(runEmbeddings.size()+256);
    runEmbeddings[runEmbeddings.size()-256+axis]=1;
    ranges.insert(ranges.end(),{w,0,0,end});
  }
  auto withoutShort=embeddings;
  std::fill(withoutShort.begin()+5*768,withoutShort.end(),
            std::numeric_limits<float>::quiet_NaN());
  auto before=community::Cluster(segments,withoutShort,windows,p,4,runEmbeddings,ranges);
  assert(before.centroids.size()==1);
  auto after=community::Cluster(segments,embeddings,windows,p,4,runEmbeddings,ranges);
  assert(after.shortRunTrainingCount==1);
  assert(after.centroids.size()==1);
  for(int w=0;w<5;++w)
    assert(after.frame_hard[(w*589+20)*3]==after.frame_hard[20*3]);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'short-merge.cpp';binary=Path(directory)/'short-merge'
            source.write_text(program)
            subprocess.run([compiler,'-std=c++17','-O2','-I',str(CPP),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

    def test_fbank_keeps_sparse_filter_edges_internal_gaps_and_empty_filters(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        # Synthetic PCM and filters only. Golden values come from the original
        # dense implementation; the private real-window differential checks
        # every output float against that implementation as well.
        program = r'''
#include "community_fbank.h"
#include <cassert>
#include <cstdint>
int main() {
  std::vector<float> constants(400+80*257);
  for(int i=0;i<400;++i)constants[i]=1.f;
  for(int m=0;m<79;++m) {
    constants[400+m*257+m%128]=.3f;
    constants[400+m*257+m%128+3]=.7f;
  }
  std::vector<float> pcm(160000);
  uint32_t state=123;
  for(float& x:pcm) {
    state=1664525u*state+1013904223u;
    x=(int(state>>16)-32768)/32768.f;
  }
  auto features=community::Fbank(pcm,constants);
  const int indices[]={0,1,78,79,80,400,1599,20000,40000,79838,79839};
  const float expected[]={-.13578414917f,-1.48220062256f,-.37323570251f,0.f,
    .44764328003f,.69540596008f,0.f,-.57683563232f,-1.29904556274f,.63313865662f,0.f};
  assert(features.size()==998*80);
  for(int i=0;i<11;++i)assert(std::abs(features[indices[i]]-expected[i])<1e-5f);
  for(int frame=0;frame<998;++frame)assert(features[frame*80+79]==0.f);
  for(float value:community::Fbank(std::vector<float>(160000),constants))assert(value==0.f);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'features.cpp'
            binary = Path(directory) / 'features'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_run_capacity_keeps_distinct_foreground_and_anonymous_background(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
#include <set>
int main() {
  community::Plda p;
  p.mean1.resize(256);p.mean2.resize(128);p.mu.resize(128);p.phi.resize(128,1.);
  p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1;p.transform[i][i]=1;}
  constexpr int n=48;
  std::vector<float> segments(n*589*3),embeddings(n*768),runs(n*256),rms(n);
  std::vector<int32_t> ranges;
  for(int w=0;w<n;++w){
    for(int f=0;f<589;++f)segments[(w*589+f)*3]=1;
    embeddings[w*768+w%6]=runs[w*256+w%6]=1.;
    ranges.insert(ranges.end(),{w,0,0,589});
    rms[w]=w%6<4?(.7f+.1f*(w%6)):.1f;
  }
  auto result=community::Cluster(segments,embeddings,n,p,4,runs,ranges,rms);
  std::set<int> foreground;
  for(int w=0;w<n;++w){
    int label=result.hard[w*3];
    if(w%6<4){assert(label>=0);foreground.insert(label);assert(label==result.hard[(w%6)*3]);}
    else assert(label==-2 && "capacity must not turn background into a foreground speaker");
    for(int f=0;f<589;++f)assert(result.frame_hard[(w*589+f)*3]==label);
  }
  assert(foreground.size()==4 && !result.usedKMeans);
  auto scaled=rms;for(auto& value:scaled)value*=.01f;
  auto quiet=community::Cluster(segments,embeddings,n,p,4,runs,ranges,scaled);
  assert(quiet.hard==result.hard && quiet.frame_hard==result.frame_hard);
  // A tighter caller capacity can leave more voices unknown but never merge
  // them. Selection does not manufacture additional groups to fill the cap.
  auto limited=community::Cluster(segments,embeddings,n,p,2,runs,ranges,rms);
  assert(limited.centroids.size()==2 && !limited.usedKMeans);
  for(int w=0;w<n;++w)assert((limited.hard[w*3]>=0)==(w%6==2||w%6==3));
  // Quiet speakers remain enrolled while all identities fit. A session-level
  // RMS gate here would erase a valid minority speaker in public recordings.
  constexpr int count=4;
  segments.resize(count*589*3);embeddings.resize(count*768);runs.resize(count*256);
  ranges.resize(count*4);rms.resize(count);rms[0]=.001f;
  auto original=community::Cluster(segments,embeddings,count,p,4,runs,ranges);
  auto within=community::Cluster(segments,embeddings,count,p,4,runs,ranges,rms);
  assert(within.hard==original.hard && within.frame_hard==original.frame_hard);
  assert(within.centroids==original.centroids && within.capacityRms.empty());
  // Level snapshots must belong to exactly these runs, not another window.
  bool rejected=false;rms.pop_back();
  try {community::Cluster(segments,embeddings,count,p,4,runs,ranges,rms);}
  catch(const std::runtime_error&){rejected=true;}assert(rejected);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'capacity.cpp'
            binary = Path(directory) / 'capacity'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_speaker_cap_uses_unconstrained_kmeans_and_keeps_active_channels(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include "community_cluster.h"
#include <cassert>
int main() {
  community::Plda p;
  p.mean1.resize(256);p.mean2.resize(128);p.mu.resize(128);p.phi.resize(128,1.);
  p.lda=community::Matrix(256,community::Vec(128));
  p.transform=community::Matrix(128,community::Vec(128));
  for(int i=0;i<128;++i){p.lda[i][i]=1;p.transform[i][i]=1;}
  constexpr int windows=48;
  std::vector<float> seg(windows*589*3),emb(windows*3*256);
  for(int w=0;w<windows;++w) {
    for(int f=0;f<589;++f)seg[(w*589+f)*3+f%3]=1;
    for(int c=0;c<3;++c)emb[(w*3+c)*256+w%6]=1;
  }
  for(int cap: {1,2,3,4}) {
    auto result=community::Cluster(seg,emb,windows,p,cap);
    assert(result.usedKMeans);
    assert(result.centroids.size()==static_cast<size_t>(cap));
    assert(result.hard.size()==windows*3);
    for(int label:result.hard)assert(label>=0&&label<cap);
    // All three local channels carry the same synthetic voice. The cap branch
    // must not impose distinct cluster IDs and discard an active local channel.
    for(int w=0;w<windows;++w) {
      assert(result.hard[w*3]==result.hard[w*3+1]);
      assert(result.hard[w*3]==result.hard[w*3+2]);
    }
  }
  auto silence=community::Cluster(std::vector<float>(589*3),std::vector<float>(768),1,p,4);
  assert(community::Reconstruct(std::vector<float>(589*3),silence.hard,{0},0).empty());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'regression.cpp'
            binary=Path(directory)/'regression'
            source.write_text(program)
            subprocess.run([compiler,'-std=c++17','-O2','-I',str(CPP),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

    def test_cluster_serialization_emits_frame_labels_only_on_request(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        source = (CPP / 'community_diarization.cpp').read_text()
        # Compile the production serialization verbatim. The per-frame label
        # grid is 589*3 integers per window and grows with the whole session
        # (about 1.57 M integers at 15 minutes), so a caller that records no
        # diagnostics must not receive it while reconstruction is unaffected.
        body = source[source.index('    std::ostringstream json;'):
                      source.index('    return json.str();')]
        program = r'''
#include "community_cluster.h"
#include <cassert>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>
namespace {
struct Vbx { community::Matrix q; std::vector<double> priors; };
struct Turn { double begin; double end; int speaker; };
struct Result {
  std::vector<int> hard, frame_hard, trainingIndices, trainingRunIndices, ahc, retainedClusters;
  community::Matrix scores, centroids;
  Vbx vbx;
  std::vector<double> capacityRms;
  bool usedKMeans = false, usedAhcFallback = false;
  int shortRunTrainingCount = 0;
};
std::string Serialize(const Result& result, const std::vector<Turn>& turns,
                      bool include_frame_hard) {
''' + body + r'''
  return json.str();
}
}  // namespace
int main() {
  Result result;
  result.hard = {0, 1};
  result.frame_hard = {0, 1, 2, -2, 1, 0};
  result.trainingIndices = {0};
  result.trainingRunIndices = {0};
  result.ahc = {0};
  result.retainedClusters = {0};
  result.scores = {{0.5, 0.25}};
  result.centroids = {{0.5, 0.25}};
  result.vbx.q = {{0.75, 0.25}};
  result.vbx.priors = {1.0, 0.0};
  result.capacityRms = {0.25};
  const std::vector<Turn> turns = {{0, 1000, 0}};
  const std::string withLabels = Serialize(result, turns, true);
  const std::string withoutLabels = Serialize(result, turns, false);
  assert(withLabels.find("\"frameHard\"") != std::string::npos);
  assert(withoutLabels.find("\"frameHard\"") == std::string::npos);
  // Everything the caller consumes, including the reconstructed timeline and
  // the window-level registry evidence, is identical either way.
  for (const char* key : {"\"speakerCount\"", "\"hard\"", "\"trainingIndices\"",
                          "\"trainingRunIndices\"", "\"ahc\"", "\"retainedClusters\"",
                          "\"scores\"", "\"centroids\"", "\"posteriors\"",
                          "\"capacityRms\"", "\"priors\"", "\"turns\""}) {
    assert(withLabels.find(key) != std::string::npos);
    assert(withoutLabels.find(key) != std::string::npos);
  }
  assert(withoutLabels.size() < withLabels.size());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'serialize.cpp'
            binary = Path(directory) / 'serialize'
            path.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_encoder_pool_and_scheduling_reach_the_native_model(self):
        # The encoder builds its own pthread pool, so the ASR threads neither
        # bound it nor disable its idle spinning. The budget has to travel from
        # the caller into the XNNPACK provider explicitly, and the engine-wide
        # scheduling request has to be forwarded for the same reason.
        source = (CPP / 'community_diarization.cpp').read_text()
        self.assertIn('int encoder_threads = kDefaultEncoderThreads', source)
        self.assertIn('{"intra_op_num_threads", std::to_string(encoder_threads)}', source)
        self.assertIn('Community encoder threads must be in [1, 8]', source)
        self.assertIn('bool include_frame_hard = true', source)
        self.assertIn('const CommunityScheduling& scheduling = CommunityScheduling()', source)
        self.assertIn('ScopedCommunityScheduling scope(scheduling_);', source)
        # The pool is created while the encoder session is built and inherits that
        # thread's affinity, so the scope has to wrap the session construction.
        self.assertIn('ScopedCommunityScheduling scope(scheduling_);\n      options.AppendExecutionProvider("XNNPACK"', source)
        self.assertIn('"invalid Community scheduling QoS"', source)
        self.assertIn('"Community scheduling CPU id out of range"', source)
        self.assertIn('if (count == 3) {', source)
        self.assertIn('if (count == 7) {', source)
        declaration = (CPP / 'types/libamphion_asr/index.d.ts').read_text()
        self.assertIn('loadCommunityDiarizationResources(resourceManager: Object,\n'
                      '  encoderThreads?: number, scheduling?: string)', declaration)
        self.assertIn('plda: Uint8Array, encoderThreads?: number,\n  scheduling?: string', declaration)
        self.assertIn('runRms: Float32Array, includeFrameHard?: boolean', declaration)
