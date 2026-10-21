"""Compare session-owned C++ history with the pinned Python candidate."""
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'diarization/conformer18/models/history_clustering.py'


class NativeHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binary = pathlib.Path(cls.temp.name) / 'history.exe'
        source = pathlib.Path(cls.temp.name) / 'main.cpp'
        source.write_text(r'''
#include "nmnet_history.h"
#include <iostream>
int main() {
  int n,dim,minimum,period;std::cin>>n>>dim>>minimum>>period;
  nmnet::History history(.67,period,minimum);
  for(int i=0;i<n;++i) {
    int slots;std::cin>>slots;std::map<int,nmnet::Vector> values;
    for(int j=0;j<slots;++j) {
      int slot;std::cin>>slot;nmnet::Vector v(dim);
      for(double& x:v)std::cin>>x;values[slot]=v;
    }
    auto result=history.Update(i,values);
    std::cout<<result.chunks<<" "<<result.compressed<<" "<<result.represented<<" "
             <<result.anchors<<" "<<result.recent;
    for(auto p:result.assignments)std::cout<<" "<<p.first<<":"<<p.second;
    std::cout<<"\n";
  }
  try { history.Update(n+1,{});return 3; } catch(const std::invalid_argument&) {}
  return 0;
}
''')
        compiler = shutil.which('g++')
        if not compiler:
            raise RuntimeError('g++ required for native parity gate')
        subprocess.run([compiler, '-std=c++17', '-O2', '-static',
                        '-I'+str(ROOT/'asr/harmony/sdk/src/main/cpp'),
                        str(source), '-o', str(cls.binary)], check=True, capture_output=True)
        spec = importlib.util.spec_from_file_location('nmnet_history_reference', SOURCE)
        cls.ref = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.ref
        spec.loader.exec_module(cls.ref)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def compare(self, chunks, minimum=4, period=50):
        dim = next(len(v) for c in chunks for v in c.values())
        lines = [f'{len(chunks)} {dim} {minimum} {period}']
        reference = self.ref.HistoryClustering(min_cluster_size=minimum, compress_every=period)
        expected=[]
        for chunk in chunks:
            lines.append(str(len(chunk)))
            for slot, vector in sorted(chunk.items()):
                lines.append(str(slot)+' '+' '.join(format(float(x),'.17g') for x in vector))
            assigned, info=reference.update(chunk)
            expected.append(' '.join(map(str,[info['chunk'],int(info['compressed']),
                info['represented_embeddings'],info['anchors'],info['recent_embeddings']]))+
                ''.join(f' {s}:{p}' for s,p in sorted(assigned.items())))
        actual=subprocess.run([str(self.binary)],input='\n'.join(lines)+'\n',text=True,
                              capture_output=True,check=True).stdout.splitlines()
        self.assertEqual(actual,expected)

    def test_two_compression_boundaries_and_silence(self):
        rng=np.random.default_rng(3407)
        basis=np.eye(16)[:4]
        chunks=[{j:basis[j]+rng.normal(0,.005,16) for j in range(4)}
                if i%13 else {} for i in range(103)]
        self.compare(chunks)

    def test_late_speaker_and_small_cluster(self):
        a,b,c=np.eye(3)
        self.compare([{0:a,1:b}]*50+[{0:c},{0:a},{0:b}]*20)
        self.compare([{0:a}]*51+[{0:b}]*51,minimum=1)

    def test_random_distances(self):
        rng=np.random.default_rng(12)
        for _ in range(8):
            self.compare([{j:rng.normal(size=8) for j in range(3)} for i in range(15)],minimum=1,period=7)

    def test_fixed_window_validity_and_committed_overlap(self):
        source=pathlib.Path(self.temp.name)/'window.cpp'
        binary=pathlib.Path(self.temp.name)/'window.exe'
        source.write_text(r'''
#include "nmnet_window.h"
#include "nmnet_overlap.h"
#include "nmnet_session.h"
#include <cassert>
#include <limits>
std::vector<nmnet::Window> schedule(int length,int block) {
  nmnet::WindowScheduler scheduler;std::vector<nmnet::Window> out;nmnet::Window w;
  for(int i=0;i<length;i+=block){scheduler.Accept(std::min(block,length-i));while(scheduler.Take(w))out.push_back(w);}
  if(scheduler.Finish(w))out.push_back(w);return out;
}
int main(){
  assert(nmnet::CanonicalActivityProbability(-0x1p-24f)==0.f);
  assert(nmnet::CanonicalActivityProbability(1.f+std::numeric_limits<float>::epsilon())==1.f);
  for(float value:{0.f,.25f,.5f,.9f,1.f})assert(nmnet::CanonicalActivityProbability(value)==value);
  for(float value:{-1e-5f,1.00001f,std::numeric_limits<float>::quiet_NaN(),
                   std::numeric_limits<float>::infinity()}) {
    bool rejected=false;
    try { nmnet::CanonicalActivityProbability(value); } catch(const std::runtime_error&) {rejected=true;}
    assert(rejected);
  }
  for(int length:{1,8000,320000,320001,352000,352001,1920000}) {
    auto a=schedule(length,length),b=schedule(length,317);
    assert(a.size()==b.size());
    for(size_t i=0;i<a.size();++i){assert(a[i].startSample==b[i].startSample);assert(a[i].validSamples==b[i].validSamples);}
    assert(a.back().startSample+a.back().validSamples==static_cast<unsigned>(length));
  }
  assert(schedule(352000,100).size()==2);
  assert(schedule(352001,100).size()==3);
  std::vector<float> pcm(nmnet::kWindowSamples,std::numeric_limits<float>::quiet_NaN());
  for(int i=0;i<8001;++i)pcm[i]=float(i+1);
  auto sanitized=nmnet::ValidPcm(pcm,8001);assert(sanitized[8001]==0);
  std::vector<float> probabilities(7*8,0);for(int f=0;f<7;++f)probabilities[f*8]=.9f;
  auto selected=nmnet::SelectSpeakerPcm(pcm,8001,probabilities,0);
  assert(selected.size()==8001 && selected.back()==8001);
  assert(nmnet::SelectSpeakerPcm(pcm,1,{},0).empty());
  auto tiny=nmnet::SelectSpeakerPcm(pcm,160,std::vector<float>{1,0,0,0,0,0,0,0},0);
  assert(tiny.empty());
  auto partial=nmnet::SelectSpeakerPcm(pcm,1281,std::vector<float>{1,0,0,0,0,0,0,0},0);
  assert(partial.size()==1280 && partial.back()==1280);
  // One clean frame falls back to all activity; two clean frames exclude overlap.
  for(int f=0;f<7;++f)probabilities[f*8+1]=1;
  assert(nmnet::SelectSpeakerPcm(pcm,8001,probabilities,0).size()==8001);
  probabilities[1]=0; // one clean frame: keep all activity
  assert(nmnet::SelectSpeakerPcm(pcm,8001,probabilities,0).size()==8001);
  probabilities[9]=0; // two clean frames: keep exactly 160 ms, never repeat
  assert(nmnet::SelectSpeakerPcm(pcm,8001,probabilities,0).size()==2560);
  std::vector<nmnet::CommittedFrames> blocks;
  nmnet::CausalOverlap overlap([&](const auto& block){blocks.push_back(block);});
  std::vector<float> p(250*8,0);for(int f=0;f<250;++f)p[f*8]=.8f;
  overlap.Add(0,p,{{0,0}},25);auto first=blocks[0].probabilities[0];
  for(int f=0;f<250;++f)p[f*8]=.6f;
  overlap.Add(25,p,{{0,1}},50);
  assert(blocks[0].probabilities[0]==first);
  assert(std::abs(blocks[1].probabilities[0][0]-.4f)<1e-6);
  auto turns=overlap.Finish(352000);assert(overlap.CommittedThroughSample()==352000);
  assert(turns.size()==2 && turns[0].beginSample==0 && turns[0].endSample==32000);
  assert(turns[1].beginSample==320000 && turns[1].endSample==352000);
  try {overlap.Add(0,p,{{0,0}},25);return 4;}catch(const std::invalid_argument&){}
  nmnet::SessionState session;
  nmnet::WindowEvidence evidence;evidence.validFrames=250;evidence.probabilities.assign(250*8,0);
  evidence.embeddings[0]=nmnet::Vector(192,0);evidence.embeddings[0][0]=1;
  for(int f=0;f<250;++f)evidence.probabilities[f*8]=.9f;
  auto delta=session.Accept({0,0,320000,false},evidence);
  assert(delta.inferenceThroughSample==320000 && delta.rolesCommittedThroughSample==32000);
  try {session.Accept({2,64000,320000,false},evidence);return 5;}catch(const std::invalid_argument&){}
  auto frozen=delta.committed[0].probabilities;
  auto next=session.Accept({1,32000,320000,false},evidence);
  assert(next.history.represented==2 && delta.committed[0].probabilities==frozen);
  assert(session.Finish().rolesCommittedThroughSample==352000);
  try {session.Accept({2,64000,320000,false},evidence);return 6;}catch(const std::invalid_argument&){}
  nmnet::SessionState cancelled;cancelled.Cancel();
  try {cancelled.Finish();return 7;}catch(const std::logic_error&){}
  // A newly observed speaker must not be absorbed into established history.
  // Exercise the actual SDK session default, not an explicitly configured History.
  nmnet::SessionState minOne;
  int established=-1;
  for(int i=0;i<51;++i) {
    auto d=minOne.Accept({static_cast<uint64_t>(i),static_cast<uint64_t>(i)*32000,320000,false},evidence);
    established=d.history.assignments.at(0);
  }
  evidence.embeddings[0][0]=0;evidence.embeddings[0][1]=1;
  auto newcomer=minOne.Accept({51,51*32000,320000,false},evidence);
  assert(newcomer.history.assignments.at(0)!=established);
}
''')
        subprocess.run([shutil.which('g++'),'-std=c++17','-O2','-static',
                        '-I'+str(ROOT/'asr/harmony/sdk/src/main/cpp'),str(source),'-o',str(binary)],
                       check=True,capture_output=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__=='__main__':
    unittest.main()
