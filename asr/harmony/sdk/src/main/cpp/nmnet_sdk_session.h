#pragma once
#include "nmnet_session.h"
#include <mutex>
#include <sstream>

namespace nmnet {
// Stable session-local IDs. Zero capacity is unbounded; explicit caps stay anonymous on overflow.
class PublicProjection {
 public:
  explicit PublicProjection(int capacity):capacity_(capacity) {
    if(capacity<0)throw std::invalid_argument("maxSpeakers must be >= 0 (0: unlimited)");
  }
  std::string Json(const SessionDelta& delta,double segmentationMs=0,double embeddingMs=0,double embeddingFeaturesMs=0,double embeddingEncoderMs=0) {
    std::ostringstream out;out.precision(15);
    out<<"{\"inferenceThroughSample\":"<<delta.inferenceThroughSample
       <<",\"rolesCommittedThroughSample\":"<<delta.rolesCommittedThroughSample
       <<",\"segmentationMs\":"<<segmentationMs<<",\"embeddingMs\":"<<embeddingMs
       <<",\"embeddingFeaturesMs\":"<<embeddingFeaturesMs<<",\"embeddingEncoderMs\":"<<embeddingEncoderMs
       <<",\"encoderBackend\":\"cpu\",\"turns\":[";
    struct Span {uint64_t begin,end;int id;};
    std::vector<Span> spans;
    std::map<int,size_t> last;
    for(const auto& block:delta.committed) {
      // Allocate by first audible frame, not by unordered cluster creation.
      for(size_t f=0;f<block.covered.size();++f) {
        const auto begin=(block.startFrame+f)*kFrameSamples;
        const auto end=std::min(begin+kFrameSamples,delta.inferenceThroughSample);
        if(!block.covered[f]||begin>=end)continue;
        for(const auto& track:block.probabilities) {
          if(track.second[f]<=.5f)continue;
          if(!ids_.count(track.first)) {
            ids_[track.first]=(capacity_==0||next_<capacity_)?next_++:-1;
          }
          const auto previous=last.find(track.first);
          if(previous!=last.end()&&spans[previous->second].end==begin) {
            spans[previous->second].end=end;
          }else {
            last[track.first]=spans.size();
            spans.push_back({begin,end,ids_[track.first]});
          }
        }
      }
    }
    bool first=true;
    for(const auto& span:spans) {
      if(!first)out<<',';first=false;
      out<<'['<<span.begin/16.0<<','<<span.end/16.0<<','<<span.id<<']';
    }
    out<<"],\"speakerCount\":"<<next_<<",\"historyChunks\":"<<delta.history.chunks
       <<",\"historyCompressed\":"<<(delta.history.compressed?"true":"false")<<'}';
    return out.str();
  }
 private:
  int capacity_,next_=0;std::map<int,int> ids_;
};
class SdkSession {
 public:
  SdkSession(const std::array<std::vector<uint8_t>,5>& models,int capacity)
      :projection_(capacity),inference_(models,4){}
  std::string Process(const std::vector<float>& pcm,int validSamples,uint64_t index) {
    std::unique_lock<std::mutex> lock(mutex_,std::try_to_lock);
    if(!lock.owns_lock())throw std::runtime_error("concurrent NMNet session operation");
    if(closed_||index!=next_)throw std::runtime_error("stale NMNet session/window");
    auto evidence=inference_.Process(pcm,validSamples);
    auto delta=state_.Accept({index,index*kHopSamples,validSamples,validSamples<kWindowSamples},evidence);
    ++next_;
    return projection_.Json(delta,evidence.segmentationMs,evidence.embeddingMs,evidence.embeddingFeaturesMs,evidence.embeddingEncoderMs);
  }
  std::string Finish() {
    std::unique_lock<std::mutex> lock(mutex_,std::try_to_lock);
    if(!lock.owns_lock()||closed_)throw std::runtime_error("NMNet finish requires an idle open session");
    closed_=true;return projection_.Json(state_.Finish());
  }
 private:
  std::mutex mutex_;PublicProjection projection_;Inference inference_;SessionState state_;
  uint64_t next_=0;bool closed_=false;
};
} // namespace nmnet
