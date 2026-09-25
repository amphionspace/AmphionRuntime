"""Portable clustering regressions; all vectors are synthetic, never voiceprints."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / 'asr/harmony/sdk/src/main/cpp'


class HarmonyCommunityNativeTest(unittest.TestCase):
    def test_native_input_copy_uses_real_view_bounds(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        source_text = (CPP / 'community_diarization.cpp').read_text()
        copy_array = source_text[source_text.index('template <typename T>'):
                                 source_text.index('\nstruct Window')]
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
  auto turns=community::Reconstruct(segments,unknown.hard,1);
  assert(turns.size()==2);
  for(const auto& turn:turns)assert(turn.speaker==-1);
  assert(turns[0].begin<turns[1].end && turns[1].begin<turns[0].end);
  auto silence=community::Cluster(std::vector<float>(589*3),unavailable,1,p,4);
  assert(community::Reconstruct(std::vector<float>(589*3),silence.hard,1).empty());
  // A later call with real enrollment evidence still names that voice.
  std::vector<float> speech(589*3),valid(768);
  for(int frame=100;frame<300;++frame)speech[frame*3+2]=1;
  valid[512]=1;
  auto known=community::Cluster(speech,valid,1,p,4);
  assert(known.trainingIndices.size()==1 && known.trainingIndices[0]==2);
  assert(known.centroids.size()==1 && known.centroids[0][0]==1);
  auto named=community::Reconstruct(speech,known.hard,1);
  assert(named.size()==1 && named[0].speaker==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'unknown.cpp'
            binary = Path(directory) / 'unknown'
            source.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

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
  assert(community::Reconstruct(std::vector<float>(589*3),silence.hard,1).empty());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'regression.cpp'
            binary=Path(directory)/'regression'
            source.write_text(program)
            subprocess.run([compiler,'-std=c++17','-O2','-I',str(CPP),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
