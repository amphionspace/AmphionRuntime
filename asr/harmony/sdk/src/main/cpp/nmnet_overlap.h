#pragma once
#include "nmnet_window.h"
#include <functional>
#include <map>

namespace nmnet {
struct Turn { uint64_t beginSample,endSample; int speaker; };
struct CommittedFrames {
  uint64_t startFrame;
  std::vector<bool> covered;
  std::map<int,std::vector<float>> probabilities;
};
class CausalOverlap {
 public:
  using Callback=std::function<void(const CommittedFrames&)>;
  explicit CausalOverlap(Callback callback={},float threshold=.5f)
      :callback_(std::move(callback)),threshold_(threshold) {
    if(!std::isfinite(threshold)||threshold<=0||threshold>=1)
      throw std::invalid_argument("invalid activity threshold");
  }
  void Add(uint64_t startFrame,const std::vector<float>& probabilities,
      const std::map<int,int>& assignments,uint64_t commitUntil) {
    if(finished_||startFrame<base_||probabilities.size()%kSlots)
      throw std::invalid_argument("cannot revise NMNet committed frames");
    const size_t frames=probabilities.size()/kSlots;
    if(frames>kFrames || startFrame-base_>kFrames || commitUntil<base_)
      throw std::invalid_argument("invalid NMNet overlap range");
    for(float p:probabilities)if(!std::isfinite(p)||p<0||p>1)
      throw std::invalid_argument("invalid NMNet probability");
    std::map<int,std::vector<float>> local;
    for(const auto& p:assignments) {
      if(p.first<0||p.first>=kSlots||p.second<0)
        throw std::invalid_argument("invalid NMNet assignment");
      auto& values=local[p.second];values.resize(frames,0);
      for(size_t f=0;f<frames;++f)values[f]=std::max(values[f],probabilities[f*kSlots+p.first]);
    }
    const size_t offset=static_cast<size_t>(startFrame-base_),length=offset+frames;
    if(length>weights_.size()) {
      weights_.resize(length,0);
      for(auto& p:values_)p.second.resize(length,0);
    }
    for(const auto& p:local) {
      auto& values=values_[p.first];values.resize(weights_.size(),0);
      for(size_t f=0;f<frames;++f)values[offset+f]+=p.second[f];
    }
    for(size_t f=0;f<frames;++f)weights_[offset+f]+=1;
    Commit(std::min(commitUntil,base_+weights_.size()));
  }
  std::vector<Turn> Finish(uint64_t realEndSample) {
    if(finished_)throw std::logic_error("NMNet overlap already finished");
    Commit(base_+weights_.size());
    for(const auto& p:open_)turns_.push_back({p.second*kFrameSamples,base_*kFrameSamples,p.first});
    open_.clear();finished_=true;
    auto result=turns_;
    for(auto& t:result) {t.beginSample=std::min(t.beginSample,realEndSample);t.endSample=std::min(t.endSample,realEndSample);}
    result.erase(std::remove_if(result.begin(),result.end(),[](const Turn& t){return t.beginSample>=t.endSample;}),result.end());
    std::sort(result.begin(),result.end(),[](const Turn& a,const Turn& b){
      if(a.beginSample!=b.beginSample)return a.beginSample<b.beginSample;
      if(a.endSample!=b.endSample)return a.endSample<b.endSample;
      return a.speaker<b.speaker;
    });
    return result;
  }
  uint64_t CommittedThroughSample() const { return base_*kFrameSamples; }
 private:
  void Commit(uint64_t end) {
    const size_t count=static_cast<size_t>(end-base_);
    if(!count)return;
    CommittedFrames block;block.startFrame=base_;block.covered.resize(count);
    for(size_t f=0;f<count;++f)block.covered[f]=weights_[f]>0;
    auto speakers=values_;
    for(const auto& p:open_)if(!speakers.count(p.first))speakers[p.first].resize(weights_.size(),0);
    for(const auto& p:speakers) {
      auto& probabilities=block.probabilities[p.first];probabilities.resize(count);
      for(size_t f=0;f<count;++f) {
        float value=p.second[f]/std::max(weights_[f],1.f);probabilities[f]=value;
        const bool active=value>threshold_,previous=open_.count(p.first)!=0;
        if(active&&!previous)open_[p.first]=base_+f;
        else if(!active&&previous) {
          turns_.push_back({open_[p.first]*kFrameSamples,(base_+f)*kFrameSamples,p.first});
          open_.erase(p.first);
        }
      }
    }
    weights_.erase(weights_.begin(),weights_.begin()+count);
    for(auto it=values_.begin();it!=values_.end();) {
      auto& values=it->second;values.erase(values.begin(),values.begin()+count);
      if(std::none_of(values.begin(),values.end(),[](float p){return p!=0;}))it=values_.erase(it);
      else ++it;
    }
    base_=end;
    // Dispatch only after state is committed. Callback data owns its buffers.
    if(callback_)callback_(block);
  }
  Callback callback_;float threshold_;uint64_t base_=0;bool finished_=false;
  std::vector<float> weights_;std::map<int,std::vector<float>> values_;
  std::map<int,uint64_t> open_;std::vector<Turn> turns_;
};
} // namespace nmnet
