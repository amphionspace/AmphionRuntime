#pragma once
#include "nmnet_diarization.h"
#include "nmnet_overlap.h"

namespace nmnet {
struct SessionDelta {
  uint64_t chunkIndex=0,inferenceThroughSample=0,rolesCommittedThroughSample=0;
  HistoryResult history;
  std::vector<CommittedFrames> committed;
};

// One instance belongs to one SDK session/generation. The caller serializes
// acceptance, finish and cancel. It must never feed speculative out-of-order
// results here. Public 0..maxSpeakers mapping is an adapter policy, not AHC.
class SessionState {
 public:
  SessionState():history_(.67,50,1),overlap_([this](const CommittedFrames& block){pending_.push_back(block);}){}
  SessionState(const SessionState&)=delete;
  SessionState& operator=(const SessionState&)=delete;
  SessionDelta Accept(const Window& window,const WindowEvidence& evidence) {
    if(closed_||tail_||window.chunkIndex!=next_||window.startSample!=next_*kHopSamples)
      throw std::invalid_argument("stale or out-of-order NMNet window");
    if(window.validSamples<=0||window.validSamples>kWindowSamples||
       (!window.tail&&window.validSamples!=kWindowSamples))
      throw std::invalid_argument("invalid NMNet window extent");
    const int validFrames=(window.validSamples/160+7)/8;
    if(evidence.validFrames!=validFrames||evidence.probabilities.size()!=static_cast<size_t>(validFrames*kSlots))
      throw std::invalid_argument("NMNet valid frame contract violated");
    for(float p:evidence.probabilities)if(!std::isfinite(p)||p<0||p>1)
      throw std::invalid_argument("invalid NMNet evidence");
    for(const auto& p:evidence.embeddings) {
      if(p.first<0||p.first>=kSlots||p.second.size()!=192)
        throw std::invalid_argument("NMNet embedding contract violated");
      Unit(p.second);
    }
    SessionDelta result;result.chunkIndex=next_;
    result.history=history_.Update(next_,evidence.embeddings);
    realEnd_=window.startSample+window.validSamples;
    const uint64_t startFrame=window.startSample/kFrameSamples;
    overlap_.Add(startFrame,evidence.probabilities,result.history.assignments,
                 startFrame+kHopSamples/kFrameSamples);
    ++next_;tail_=window.tail;
    result.inferenceThroughSample=realEnd_;
    result.rolesCommittedThroughSample=std::min(realEnd_,overlap_.CommittedThroughSample());
    result.committed.swap(pending_);
    return result;
  }
  SessionDelta Finish() {
    if(closed_)throw std::logic_error("NMNet session closed");
    // The adapter must drain every accepted PCM window before calling Finish.
    // A cancel instead destroys this state without publishing these blocks.
    overlap_.Finish(realEnd_);closed_=true;
    SessionDelta result;result.chunkIndex=next_;
    result.inferenceThroughSample=realEnd_;
    result.rolesCommittedThroughSample=std::min(realEnd_,overlap_.CommittedThroughSample());
    result.committed.swap(pending_);
    return result;
  }
  void Cancel() {closed_=true;pending_.clear();}
 private:
  History history_;std::vector<CommittedFrames> pending_;CausalOverlap overlap_;
  uint64_t next_=0,realEnd_=0;bool tail_=false,closed_=false;
};
} // namespace nmnet
