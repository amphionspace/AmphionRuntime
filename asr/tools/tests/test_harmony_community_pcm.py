"""Execute the production PCM helper and Core/Local wrappers, never a copy of it."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.community_pcm_host import (
    ROOT, normalizer_wrapper_prelude, production_pcm_source,
)

CLIENT = ROOT / 'asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization/SpeakerDiarizationLocalClient.ets'


class HarmonyCommunityPcmTest(unittest.TestCase):
    def test_real_napi_helper_and_wrappers_preserve_all_int16_values(self):
        source = CLIENT.read_text()
        read_window = source[source.index('  private readWindow('):source.index('  private fail(')]
        script = normalizer_wrapper_prelude() + r'''
import assert from 'node:assert/strict';
const normalize = CommunityDiarizationInference.normalizePcm16Window;
function expected(pcm) {
  const out = new Float32Array(160000);
  // Original ArkTS readWindow contract, evaluated by the JS runtime.
  for (let i = 0; i < pcm.length; ++i) out[i] = pcm[i] / 32768.0;
  return out;
}
function bits(array) { return Buffer.from(array.buffer, array.byteOffset, array.byteLength); }
function check(pcm) {
  const before = Buffer.from(bits(pcm));
  const result = normalize(pcm);
  assert.ok(result instanceof Float32Array);
  assert.equal(result.length, 160000);
  assert.equal(result.byteOffset, 0);
  assert.equal(result.buffer.byteLength, 640000);
  assert.notEqual(result.buffer, pcm.buffer);
  assert.equal(Buffer.compare(bits(result), bits(expected(pcm))), 0, 'bitwise mismatch');
  assert.equal(Buffer.compare(bits(pcm), before), 0, 'input was mutated');
  for (let i = pcm.length; i < result.length; ++i) assert.ok(Object.is(result[i], 0));
  return result;
}
const domain = Int16Array.from({length: 65536}, (_, i) => i - 32768);
check(domain);
const backing = new Int16Array(domain.length + 7);
backing.fill(12345); backing.set(domain, 3);
const view = backing.subarray(3, 3 + domain.length), beforeBacking = Buffer.from(bits(backing));
const output = check(view);
assert.equal(Buffer.compare(bits(backing), beforeBacking), 0);
view[0] = 0; assert.equal(output[0], -1, 'output must own its storage');
output[1] = 99; assert.equal(view[1], -32767, 'output mutation cannot alter input');
for (const pcm of [new Int16Array(0), Int16Array.of(-32768,-1,0,1,32767),
                   new Int16Array(159999).fill(-7), new Int16Array(160000).fill(123)]) check(pcm);
const a = normalize(Int16Array.of(1)), b = normalize(Int16Array.of(1));
assert.notEqual(a.buffer, b.buffer); a[0] = 5; assert.equal(b[0], 1/32768);
assert.throws(() => normalize(new Int16Array(160001)), /sample limit/);
for (const value of [new Float32Array(1), new Uint16Array(1), new ArrayBuffer(2), null, {}]) {
  assert.throws(() => normalize(value));
}
const odd = new Int16Array(2); Object.defineProperty(odd, 'byteLength', {value:3});
assert.throws(() => normalize(odd), /typed array/);
const beyond = new Int16Array(2).subarray(1);
Object.defineProperty(beyond, 'byteLength', {value:4});
assert.throws(() => normalize(beyond), /backing buffer/);
const pending = new Error('original byteLength getter failure'), throwing = new Int16Array(1);
Object.defineProperty(throwing, 'byteLength', {get(){ throw pending; }});
assert.throws(() => normalize(throwing), error => error === pending, 'pending exception must survive');
class SpeakerDiarizationStorageError extends Error {}
class Reader {
''' + read_window + r'''
}
const reader = new Reader(), pcm = Int16Array.of(-32768, -1, 0, 32767);
let observed;
reader.spool = {read(offset, count){ observed=[offset,count]; return pcm.buffer; }};
assert.equal(Buffer.compare(bits(reader.readWindow({offsetBytes:32000,sampleCount:4})), bits(expected(pcm))), 0);
assert.deepEqual(observed, [32000,8]);
reader.spool.read = () => { throw Error('disk failed'); };
assert.throws(() => reader.readWindow({offsetBytes:0,sampleCount:1}), SpeakerDiarizationStorageError);
reader.spool.read = () => new ArrayBuffer(320002);
assert.throws(() => reader.readWindow({offsetBytes:0,sampleCount:160001}), error =>
  !(error instanceof SpeakerDiarizationStorageError) && /sample limit/.test(error.message));
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pcm.mts'
            path.write_text(script)
            subprocess.run(['node', '--experimental-strip-types', str(path)], check=True, cwd=ROOT, timeout=30)

    def test_real_helper_checks_length_bounds_allocation_and_pending_failures(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        program = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>
static size_t watched_size = 0, watched_allocations = 0;
static bool fail_watched_allocation = false;
void* operator new(size_t size) {
  if (size == watched_size) {
    ++watched_allocations;
    if (fail_watched_allocation) throw std::bad_alloc();
  }
  void* p = std::malloc(size ? size : 1);
  if (!p) throw std::bad_alloc();
  return p;
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
enum napi_status { napi_ok, napi_failed };
enum napi_typedarray_type { napi_int16_array, napi_float32_array, napi_uint8_array };
struct Value {
  napi_typedarray_type type = napi_int16_array;
  size_t native_length = 0, view_bytes = 0, offset = 0, backing_bytes = 0;
  void* data = nullptr;
  Value* backing = nullptr;
  std::vector<uint32_t> words;
};
using napi_value = Value*;
struct Call { Value* input = nullptr; size_t count = 1; };
using napi_callback_info = Call*;
enum Operation { None, CallbackInfo, TypedInfo, NamedProperty, Uint32Value, BufferInfo,
                 CreateBuffer, CreateTyped, PendingQuery, ThrowError };
struct State {
  Operation fail = None;
  bool fail_with_pending = false, pending = false, zero_allocation_pointer = false;
  int throws = 0, buffers = 0, arrays = 0;
  std::string error;
  std::vector<std::unique_ptr<Value>> owned;
  bool fails(Operation operation) {
    if (fail != operation) return false;
    if (fail_with_pending) { pending = true; error = "original pending exception"; }
    return true;
  }
};
using napi_env = State*;
napi_status napi_get_cb_info(napi_env env, napi_callback_info call, size_t* n,
                            napi_value* input, napi_value*, void**) {
  if (env->fails(CallbackInfo)) return napi_failed;
  *n = call->count; if (*n) *input = call->input; return napi_ok;
}
napi_status napi_get_typedarray_info(napi_env env, napi_value v, napi_typedarray_type* type,
                                   size_t* length, void** data, napi_value* backing, size_t* offset) {
  if (env->fails(TypedInfo) || !v) return napi_failed;
  *type=v->type; *length=v->native_length; *data=v->data; *backing=v->backing; *offset=v->offset;
  return napi_ok;
}
napi_status napi_get_named_property(napi_env env, napi_value v, const char*, napi_value* out) {
  if (env->fails(NamedProperty)) return napi_failed;
  *out=v; return napi_ok;
}
napi_status napi_get_value_uint32(napi_env env, napi_value v, uint32_t* out) {
  if (env->fails(Uint32Value)) return napi_failed;
  *out=static_cast<uint32_t>(v->view_bytes); return napi_ok;
}
napi_status napi_get_arraybuffer_info(napi_env env, napi_value v, void** data, size_t* bytes) {
  if (env->fails(BufferInfo) || !v) return napi_failed;
  *data=v->data; *bytes=v->backing_bytes; return napi_ok;
}
napi_status napi_create_arraybuffer(napi_env env, size_t bytes, void** data, napi_value* result) {
  ++env->buffers;
  if (env->fails(CreateBuffer)) return napi_failed;
  auto v=std::make_unique<Value>();
  v->words.assign(bytes/4, 0xffffffffu); // Require explicit positive-zero padding.
  v->backing_bytes=bytes; v->data=v->words.data();
  *data=env->zero_allocation_pointer?nullptr:v->data; *result=v.get();
  env->owned.push_back(std::move(v)); return napi_ok;
}
napi_status napi_create_typedarray(napi_env env, napi_typedarray_type type, size_t length,
                                  napi_value buffer, size_t offset, napi_value* result) {
  ++env->arrays;
  if (env->fails(CreateTyped)) return napi_failed;
  assert(type==napi_float32_array && length==160000 && offset==0);
  auto v=std::make_unique<Value>(); v->type=type; v->native_length=length;
  v->view_bytes=length*4; v->backing=buffer; v->data=buffer->data;
  *result=v.get(); env->owned.push_back(std::move(v)); return napi_ok;
}
napi_status napi_is_exception_pending(napi_env env, bool* pending) {
  if (env->fails(PendingQuery)) return napi_failed;
  *pending=env->pending; return napi_ok;
}
napi_status napi_throw_error(napi_env env, const char*, const char* message) {
  ++env->throws;
  if (env->fails(ThrowError)) return napi_failed;
  assert(!env->pending); env->pending=true; env->error=message; return napi_ok;
}
''' + production_pcm_source() + r'''
static uint32_t Bits(float value) { uint32_t bits; std::memcpy(&bits,&value,4); return bits; }
int main() {
  std::vector<int16_t> input(65540, 1234);
  for (int i=0;i<65536;++i) input[i+2]=static_cast<int16_t>(i-32768);
  const auto original=input;
  Value buffer; buffer.data=input.data(); buffer.backing_bytes=input.size()*2;
  Value view; view.backing=&buffer; view.data=input.data()+2; view.offset=4;
  view.view_bytes=65536*2;
  for (bool harmony:{false,true}) {
    view.native_length=harmony?view.view_bytes:view.view_bytes/2;
    State state; Call call{&view};
    watched_size=view.view_bytes; watched_allocations=0;
    auto result=NormalizeCommunityPcm16Window(&state,&call);
    assert(result && state.throws==0 && watched_allocations==1);
    watched_size=0;
    auto* output=static_cast<float*>(result->data);
    for (int i=0;i<65536;++i) {
      const float expected=static_cast<float>(static_cast<double>(i-32768)/32768.0);
      assert(Bits(output[i])==Bits(expected));
    }
    for (size_t i=65536;i<160000;++i) assert(Bits(output[i])==0);
    assert(input==original);
  }
  view.native_length=65536;
  // A synthetic oversized view needs no backing allocation. The allocation
  // watch and unreadable pointer catch a cap moved after snapshot allocation.
  Value huge_buffer; huge_buffer.backing_bytes=320002; huge_buffer.data=reinterpret_cast<void*>(1);
  Value huge; huge.backing=&huge_buffer; huge.data=reinterpret_cast<void*>(1);
  huge.view_bytes=320002; huge.native_length=160001;
  for (bool harmony:{false,true}) {
    huge.native_length=harmony?320002:160001;
    State state; Call call{&huge}; watched_size=320002; watched_allocations=0;
    assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr);
    assert(watched_allocations==0 && state.buffers==0 && state.arrays==0);
    assert(state.error.find("sample limit")!=std::string::npos); watched_size=0;
  }
  for (Operation operation:{CallbackInfo,TypedInfo,NamedProperty,Uint32Value,BufferInfo,CreateBuffer,CreateTyped}) {
    for (bool pending:{false,true}) {
      State state; state.fail=operation; state.fail_with_pending=pending; Call call{&view};
      assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr);
      assert(state.pending && state.throws==(pending?0:1));
      if (pending) assert(state.error=="original pending exception");
    }
  }
  for (size_t count:{size_t(0),size_t(2)}) {
    State state; Call call{&view,count};
    assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr && state.buffers==0);
  }
  for (int mode=0;mode<5;++mode) {
    Value bad=view;
    if (mode==0) bad.type=napi_float32_array;
    if (mode==1) bad.offset=buffer.backing_bytes+1;
    if (mode==2) bad.view_bytes=static_cast<uint32_t>(buffer.backing_bytes);
    if (mode==3) bad.native_length=17;
    if (mode==4) bad.view_bytes=3;
    State state; Call call{&bad};
    assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr && state.buffers==0);
  }
  {
    State state; state.zero_allocation_pointer=true; Call call{&view};
    assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr && state.arrays==0);
  }
  {
    State state; Call call{&view}; watched_size=view.view_bytes; watched_allocations=0;
    fail_watched_allocation=true;
    assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr);
    fail_watched_allocation=false; watched_size=0;
    assert(watched_allocations==1 && state.buffers==0 && state.pending);
  }
  {
    State state; state.fail=PendingQuery; state.pending=true; state.error="keep me";
    Call call{nullptr}; assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr);
    assert(state.throws==0 && state.error=="keep me");
  }
  {
    State state; state.fail=ThrowError; Call call{nullptr};
    assert(NormalizeCommunityPcm16Window(&state,&call)==nullptr && state.throws==1);
  }
  // Existing uncapped Float32 input copies retain their exact bit patterns.
  std::vector<uint32_t> float_bits(160001,0x80000000u);
  float_bits[0]=0x7fc01234u; float_bits[1]=0x7f800000u; float_bits[2]=0xff800000u;
  Value floats_buffer; floats_buffer.data=float_bits.data(); floats_buffer.backing_bytes=float_bits.size()*4;
  Value floats; floats.type=napi_float32_array; floats.backing=&floats_buffer;
  floats.data=float_bits.data(); floats.view_bytes=float_bits.size()*4; floats.native_length=float_bits.size();
  State state; const auto copied=CopyArray<float>(&state,&floats,napi_float32_array);
  assert(copied.size()==float_bits.size() && std::memcmp(copied.data(),float_bits.data(),floats.view_bytes)==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'pcm_faults.cpp'
            binary = Path(directory) / 'pcm_faults'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', str(source), '-o', str(binary)], check=True, timeout=60)
            subprocess.run([str(binary)], check=True, timeout=20)


if __name__ == '__main__':
    unittest.main()
