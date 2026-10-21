#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <sstream>
#include <limits>
#include <vector>

namespace nmnet {
constexpr int kSampleRate=16000, kWindowSamples=320000, kHopSamples=32000;
constexpr int kFrameSamples=1280, kFrames=250, kSlots=8;

// ARM ORT's approximate Sigmoid can return -2^-24 at saturation. Canonicalize
// only representational boundary error, not an invalid model distribution.
inline float CanonicalActivityProbability(float value) {
  constexpr float tolerance=std::numeric_limits<float>::epsilon();
  if(!std::isfinite(value)||value < -tolerance||value > 1.f+tolerance) {
    std::ostringstream message;
    message << "invalid NMNet model probability: " << std::hexfloat << value;
    throw std::runtime_error(message.str());
  }
  return std::max(0.f,std::min(1.f,value));
}
struct Window {
  uint64_t chunkIndex;
  uint64_t startSample;
  int validSamples;
  bool tail;
};
class WindowScheduler {
 public:
  void Accept(uint64_t samples) {
    if(finished_)throw std::logic_error("NMNet scheduler finished");
    if(samples>UINT64_MAX-total_)throw std::overflow_error("NMNet audio length overflow");
    total_+=samples;
  }
  bool Take(Window& window) {
    if(finished_)throw std::logic_error("NMNet scheduler finished");
    if(total_<start_ || total_-start_<kWindowSamples)return false;
    window={next_++,start_,kWindowSamples,false};start_+=kHopSamples;
    return true;
  }
  bool Finish(Window& window) {
    if(finished_)throw std::logic_error("NMNet scheduler finished");
    if(total_>=start_ && total_-start_>=kWindowSamples)
      throw std::logic_error("NMNet complete windows must drain first");
    finished_=true;
    if(total_==0 || (next_>0 && total_==start_-kHopSamples+kWindowSamples))return false;
    window={next_++,start_,static_cast<int>(total_-start_),true};
    return true;
  }
 private:
  uint64_t total_=0,start_=0,next_=0;bool finished_=false;
};

// Fixed transport shape; tail validity is never inferred from amplitude.
inline std::vector<float> ValidPcm(const std::vector<float>& pcm,int validSamples) {
  if(pcm.size()!=kWindowSamples || validSamples<1 || validSamples>kWindowSamples)
    throw std::invalid_argument("NMNet requires 320000 PCM samples and validSamples in [1,320000]");
  std::vector<float> copy(kWindowSamples,0);
  for(int i=0;i<validSamples;++i) {
    if(!std::isfinite(pcm[i]))throw std::invalid_argument("non-finite NMNet PCM");
    copy[i]=pcm[i];
  }
  return copy;
}

// pyannote 3.4 ECAPA mask policy on the fixed 250-frame / 20-second grid.
// Prefer >1 clean frames (ceil(250*640/320000)); otherwise use activity.
// Never repeat short speech or select transport padding. The pinned ECAPA
// accepts >=640 real samples; shorter selections have no embedding.
inline std::vector<float> SelectSpeakerPcm(const std::vector<float>& pcm,int validSamples,
    const std::vector<float>& probabilities,int slot,double threshold=.5) {
  if(slot<0||slot>=kSlots||!std::isfinite(threshold)||threshold<=0||threshold>=1)
    throw std::invalid_argument("invalid NMNet speaker mask configuration");
  const auto cleanPcm=ValidPcm(pcm,validSamples);
  // Pinned NeMo preprocessor floors the mel hop, then feature stacking ceils /8.
  const int frames=(validSamples/160+7)/8;
  if(probabilities.size()!=static_cast<size_t>(frames*kSlots))
    throw std::invalid_argument("NMNet probabilities must contain valid frames only");
  std::vector<float> clean,active;int cleanFrames=0;
  for(size_t i=0;i<probabilities.size();++i) {
    const float p=probabilities[i];
    if(!std::isfinite(p)||p<0||p>1) {
      std::ostringstream message;
      message << "invalid NMNet activity probability: index=" << i
              << " value=" << std::hexfloat << p << " validSamples=" << validSamples;
      throw std::invalid_argument(message.str());
    }
  }
  for(int f=0;f<frames;++f) {
    int count=0;for(int s=0;s<kSlots;++s)count+=probabilities[f*kSlots+s]>threshold;
    if(probabilities[f*kSlots+slot]<=threshold)continue;
    const int begin=f*kFrameSamples,end=std::min(validSamples,begin+kFrameSamples);
    active.insert(active.end(),cleanPcm.begin()+begin,cleanPcm.begin()+end);
    if(count==1){++cleanFrames;clean.insert(clean.end(),cleanPcm.begin()+begin,cleanPcm.begin()+end);}
  }
  auto selected=cleanFrames>1?std::move(clean):std::move(active);
  if(selected.size()<640)selected.clear();
  return selected;
}
} // namespace nmnet
