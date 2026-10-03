"""Execute the production PCM helper through a portable host N-API shim."""
import atexit
import functools
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / 'asr/harmony/sdk/src/main/cpp/community_diarization.cpp'
CORE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/CommunityDiarizationInference.ets'


def production_pcm_source():
    source = CPP.read_text()
    start = source.index('template <typename T>')
    return source[start:source.index('\n#endif', start)]


def production_normalizer_wrapper():
    source = CORE.read_text()
    start = source.index('  static normalizePcm16Window(')
    return source[start:source.index('\n  }', start) + len('\n  }')]


@functools.lru_cache(maxsize=1)
def native_normalizer_binary():
    compiler = shutil.which('clang++') or shutil.which('g++')
    if compiler is None:
        raise unittest.SkipTest('host C++ compiler required')
    directory = tempfile.TemporaryDirectory(prefix='community-pcm-host-')
    atexit.register(directory.cleanup)
    root = Path(directory.name)
    source = root / 'pcm.cpp'
    binary = root / 'pcm'
    # This shim supplies platform calls only. The input validation, cap,
    # normalization, allocation checks and exception handling are production C++.
    source.write_text(r'''
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
enum napi_status { napi_ok, napi_failed };
enum napi_typedarray_type { napi_int16_array, napi_float32_array, napi_uint8_array };
struct Value {
  napi_typedarray_type type = napi_int16_array;
  size_t length=0, bytes=0, offset=0, capacity=0;
  void* data=nullptr;
  Value* backing=nullptr;
};
using napi_value=Value*;
using napi_env=void*;
using napi_callback_info=Value*;
static Value output_buffer, output_view;
static std::vector<float> output;
static bool pending=false;
static std::string error;
napi_status napi_get_cb_info(napi_env, napi_callback_info input, size_t* count,
                            napi_value* value, napi_value*, void**) {
  *count=1; *value=input; return napi_ok;
}
napi_status napi_get_typedarray_info(napi_env, napi_value input, napi_typedarray_type* type,
                                   size_t* length, void** data, napi_value* buffer, size_t* offset) {
  *type=input->type; *length=input->length; *data=input->data;
  *buffer=input->backing; *offset=input->offset; return napi_ok;
}
napi_status napi_get_named_property(napi_env, napi_value input, const char*, napi_value* value) {
  *value=input; return napi_ok;
}
napi_status napi_get_value_uint32(napi_env, napi_value input, uint32_t* value) {
  *value=static_cast<uint32_t>(input->bytes); return napi_ok;
}
napi_status napi_get_arraybuffer_info(napi_env, napi_value buffer, void** data, size_t* bytes) {
  *data=buffer->data; *bytes=buffer->capacity; return napi_ok;
}
napi_status napi_create_arraybuffer(napi_env, size_t bytes, void** data, napi_value* buffer) {
  output.assign(bytes/sizeof(float), -123.f);
  output_buffer.data=output.data(); output_buffer.capacity=bytes;
  *data=output_buffer.data; *buffer=&output_buffer; return napi_ok;
}
napi_status napi_create_typedarray(napi_env, napi_typedarray_type type, size_t length,
                                  napi_value buffer, size_t offset, napi_value* value) {
  if(type!=napi_float32_array || offset!=0) return napi_failed;
  output_view.type=type; output_view.length=length; output_view.bytes=length*4;
  output_view.data=buffer->data; output_view.backing=buffer; *value=&output_view; return napi_ok;
}
napi_status napi_is_exception_pending(napi_env, bool* value) { *value=pending; return napi_ok; }
napi_status napi_throw_error(napi_env, const char*, const char* message) {
  pending=true; error=message; return napi_ok;
}
''' + production_pcm_source() + r'''
int main(int argc, char** argv) {
  if(argc!=6) return 3;
  std::vector<char> bytes((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
  Value backing; backing.data=bytes.data(); backing.capacity=bytes.size();
  Value input; input.type=static_cast<napi_typedarray_type>(std::stoul(argv[1]));
  input.length=std::stoull(argv[2]); input.bytes=std::stoull(argv[3]); input.offset=std::stoull(argv[4]);
  if(std::stoull(argv[5])!=bytes.size()) return 4;
  input.backing=&backing;
  input.data=bytes.empty()?nullptr:bytes.data()+(input.offset<=bytes.size()?input.offset:0);
  auto result=NormalizeCommunityPcm16Window(nullptr,&input);
  if(!result) { std::cerr<<error; return 2; }
  std::cout.write(static_cast<const char*>(result->data),result->bytes);
}
''')
    subprocess.run([compiler, '-std=c++17', '-O2', str(source), '-o', str(binary)], check=True, timeout=60)
    return binary


def native_normalizer_prelude():
    # Standalone execution also works with hardened macOS Node binaries that
    # prohibit loading unsigned .node libraries. No conversion is mirrored in JS.
    return r'''
import { spawnSync as runPcmHelper } from 'node:child_process';
const pcmViewPrototype=Object.getPrototypeOf(Int16Array.prototype);
function pcmViewField(value, name) {
  return Object.getOwnPropertyDescriptor(pcmViewPrototype,name).get.call(value);
}
function normalizeCommunityPcm16Window(pcm) {
  if(!ArrayBuffer.isView(pcm) || pcm instanceof DataView) throw new TypeError('expected typed array');
  const type=pcm instanceof Int16Array?0:pcm instanceof Float32Array?1:2;
  const backing=pcmViewField(pcm,'buffer');
  const result=runPcmHelper(PCM_HELPER_BINARY,
    [String(type),String(pcmViewField(pcm,'length')),String(pcm.byteLength),
     String(pcmViewField(pcm,'byteOffset')),String(backing.byteLength)],
    {input:Buffer.from(backing),maxBuffer:2*1024*1024,timeout:10000});
  if(result.error) throw result.error;
  if(result.status!==0) throw new Error(result.stderr.toString()||'host PCM helper failed');
  const bytes=new Uint8Array(result.stdout.length);
  bytes.set(result.stdout);
  return new Float32Array(bytes.buffer);
}
'''.replace('PCM_HELPER_BINARY', json.dumps(str(native_normalizer_binary())))


def normalizer_wrapper_prelude():
    wrapper = production_normalizer_wrapper().replace(': Int16Array', '').replace(': Float32Array', '')
    return native_normalizer_prelude() + 'class CommunityDiarizationInference {\n' + wrapper + '\n}\n'
