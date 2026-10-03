"""Bitwise regressions for Community assignment/voting; synthetic inputs only.

REFERENCE freezes Cluster/Reconstruct from 39e0263362ccde613d0068dc412d322a753d5461.
The unchanged PLDA/VBx/KMeans helpers are shared. AHC is independently frozen
in community_ahc_reference.h; run validation, clean run selection, assignment,
voting and reconstruction are also independent of production.
No test reads Git HEAD or rewrites production code.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / 'asr/harmony/sdk/src/main/cpp'

REFERENCE = r'''
namespace reference {
using community::Vec; using community::Matrix; using community::Plda;
using community::ClusterResult; using community::Turn;
using community_ahc_reference::Ahc; using community::Vbx; using community::KMeans;
inline std::vector<Turn> Reconstruct(const std::vector<float>& segments,
                                    const std::vector<int>& hard,
                                    const std::vector<double>& windowStartSamples,
                                    double beginSample,int maxSpeakers=4,
                                    const std::vector<int>& frameHard={}) {
  constexpr int local=3,frames=589;
  constexpr double step=270./16000.,halfFrame=991./32000.;
  const int windows=windowStartSamples.size();
  if(windows==0 || segments.size()!=static_cast<size_t>(windows*frames*local) ||
      hard.size()!=static_cast<size_t>(windows*local) ||
      (!frameHard.empty() && frameHard.size()!=static_cast<size_t>(windows*frames*local)) ||
      !std::isfinite(beginSample) || beginSample<0) throw std::runtime_error("invalid reconstruction input");
  double endSample=beginSample;
  for(double sample:windowStartSamples){
    if(!std::isfinite(sample) || sample<0 || sample!=std::floor(sample))
      throw std::runtime_error("invalid window start sample");
    endSample=std::max(endSample,sample+160000);
  }
  // Keep the session frame grid after pruning. Historical identity anchors
  // participate in clustering, but do not allocate or repaint past audio.
  const int64_t firstFrame=static_cast<int64_t>(std::floor(beginSample/270.));
  const int total=static_cast<int>(std::nearbyint(endSample/270.)-firstFrame)+1;
  int knownClusters=std::max(0,*std::max_element(hard.begin(),hard.end())+1);
  if(!frameHard.empty())knownClusters=std::max(knownClusters,*std::max_element(frameHard.begin(),frameHard.end())+1);
  Matrix activation(total,Vec(knownClusters));Vec counts(total),weights(total);
  for(int w=0;w<windows;++w){
    const int64_t start=static_cast<int64_t>(std::nearbyint(windowStartSamples[w]/270.))-firstFrame;
    for(int f=0;f<frames;++f){
      const int64_t t=start+f;if(t<0 || t>=total)continue;
      Vec active(knownClusters);int n=0;
      for(int k=0;k<local;++k){float value=segments[(w*frames+f)*local+k];n+=value;int label=frameHard.empty()?hard[w*local+k]:frameHard[(w*frames+f)*local+k];if(label>=0)active[label]=std::max(active[label],static_cast<double>(value));}
      counts[t]+=n;weights[t]+=1;
      for(int k=0;k<knownClusters;++k)activation[t][k]+=active[k];
    }
  }
  // Voice count is evidence of speech, not of a particular identity. Reserve
  // anonymous tracks even when the global registry already has enough named
  // voices: none of those voices may have acoustic support at this frame.
  int anonymousTracks=0;
  for(int t=0;t<total;++t){
    counts[t]=weights[t]>0?std::min(static_cast<int>(std::nearbyint(counts[t]/weights[t])),maxSpeakers):0;
    anonymousTracks=std::max(anonymousTracks,static_cast<int>(counts[t]));
  }
  const int clusters=knownClusters+anonymousTracks;
  for(auto& row:activation)row.resize(clusters);
  std::vector<Turn> turns;std::vector<int> start(clusters,-1);
  for(int t=0;t<total;++t){
    int count=static_cast<int>(counts[t]);std::vector<int> order(clusters);std::iota(order.begin(),order.end(),0);
    std::stable_sort(order.begin(),order.end(),[&](int a,int b){return activation[t][a]>activation[t][b];});
    std::vector<bool> on(clusters,false);int anonymous=knownClusters;
    for(int j=0;j<count;++j){
      const int candidate=order[j];
      if(candidate<knownClusters && activation[t][candidate]>0)on[candidate]=true;
      else on[anonymous++]=true;
    }
    for(int k=0;k<clusters;++k){
      if(on[k]&&start[k]<0)start[k]=t;
      if(!on[k]&&start[k]>=0){turns.push_back({(firstFrame+start[k])*step+halfFrame,(firstFrame+t)*step+halfFrame,k<knownClusters?k:-1});start[k]=-1;}
    }
  }
  for(int k=0;k<clusters;++k)if(start[k]>=0)turns.push_back({(firstFrame+start[k])*step+halfFrame,(firstFrame+total-1)*step+halfFrame,k<knownClusters?k:-1});
  return turns;
}
inline ClusterResult Cluster(const std::vector<float>& segments,const std::vector<float>& embeddings,int windows,const Plda& plda,int maxSpeakers=4,
                            const std::vector<float>& runEmbeddings={},const std::vector<int32_t>& runRanges={},
                            const std::vector<float>& runRms={}) {
  constexpr int frames=589,local=3,dim=256;
  if(segments.size()!=windows*frames*local||embeddings.size()!=windows*local*dim)throw std::runtime_error("invalid cluster shapes");
  ClusterResult result;Matrix train;std::vector<int> activity(windows*local);
  for(int w=0;w<windows;++w){for(int f=0;f<frames;++f){int count=0;for(int k=0;k<local;++k)count+=segments[(w*frames+f)*local+k];for(int k=0;k<local;++k){int on=segments[(w*frames+f)*local+k];activity[w*local+k]+=on;}}
  }
  const bool runMode=!runRanges.empty()&&runRanges.size()%4==0&&runEmbeddings.size()==(runRanges.size()/4)*dim;
  if(!runRms.empty()&&(!runMode||runRms.size()!=runRanges.size()/4||
     !std::all_of(runRms.begin(),runRms.end(),[](float v){return std::isfinite(v)&&v>=0;})))
    throw std::runtime_error("invalid Community run level evidence");
  std::vector<int> runWindow,runChannel,runBegin,runEnd;
  std::vector<bool> shortCandidate;
  std::vector<Vec> shortCandidateVectors;
  if(runMode){
    for(size_t i=0;i<runRanges.size();i+=4){int w=runRanges[i],k=runRanges[i+1],b=runRanges[i+2],e=runRanges[i+3];
      if(w<0||w>=windows||k<0||k>=local||b<0||e<=b||e>frames)throw std::runtime_error("invalid Community run range");
      runWindow.push_back(w);runChannel.push_back(k);runBegin.push_back(b);runEnd.push_back(e);
    }
    std::vector<int> cleanRunCount(windows*local);
    std::vector<bool> clean(runWindow.size(),false);
    for(size_t r=0;r<runWindow.size();++r){
      bool pure=true;
      for(int f=runBegin[r];f<runEnd[r];++f){
        int count=0;for(int ch=0;ch<local;++ch)count+=segments[(runWindow[r]*frames+f)*local+ch];
        if(!segments[(runWindow[r]*frames+f)*local+runChannel[r]]||count!=1){pure=false;break;}
      }
      clean[r]=pure;if(pure)++cleanRunCount[runWindow[r]*local+runChannel[r]];
    }
    shortCandidate.assign(runWindow.size(),false);shortCandidateVectors.resize(runWindow.size());
    for(size_t r=0;r<runWindow.size();++r){
      Vec emb(runEmbeddings.begin()+r*dim,runEmbeddings.begin()+(r+1)*dim);
      const bool finiteRun=std::all_of(emb.begin(),emb.end(),[](double x){return std::isfinite(x);});
      const int length=runEnd[r]-runBegin[r];
      if(length>=.2*frames&&finiteRun){
        result.trainingRunIndices.push_back(r);train.push_back(std::move(emb));continue;
      }
      // A short run normally has no independent enrollment vector. When it is
      // the only clean run on its channel, the existing masked full-window
      // embedding is still an unambiguous piece of acoustic evidence. Keep it
      // as a candidate; the AHC capacity check below decides whether it can
      // create a new identity. Mixed or overlapping channels remain unknown.
      const int fullIndex=runWindow[r]*local+runChannel[r];
      Vec full(embeddings.begin()+fullIndex*dim,embeddings.begin()+(fullIndex+1)*dim);
      double norm=0;for(double value:full)norm+=value*value;
      // Process uses the clean mask only above two clean frames. Otherwise
      // its full-window vector also pools any overlap on this channel.
      const bool ownsFullMask=length>2||activity[fullIndex]==length;
      if(length<.2*frames&&clean[r]&&cleanRunCount[fullIndex]==1&&ownsFullMask&&
         std::all_of(full.begin(),full.end(),[](double x){return std::isfinite(x);})&&norm>1e-12){
        shortCandidate[r]=true;shortCandidateVectors[r]=std::move(full);
      }
    }
    // Add only a candidate that creates one new AHC group while the public
    // speaker cap still has room. This admits an otherwise unrepresented
    // short voice without forcing a count or allowing duplicate short tails
    // to manufacture identities.
    auto groupCount=[](const Matrix& values){
      if(values.empty())return 0;
      auto labels=Ahc(values);return *std::max_element(labels.begin(),labels.end())+1;
    };
    int groups=groupCount(train);
    if(groups>0){
      // Admission requires exactly one additional group within the cap. Once
      // full, no later candidate can change train or groups; avoid refitting
      // the same history for every remaining, necessarily rejected short run.
      for(size_t r=0;r<shortCandidate.size()&&groups<maxSpeakers;++r)if(shortCandidate[r]){
        Matrix proposed=train;proposed.push_back(shortCandidateVectors[r]);
        const int next=groupCount(proposed);
        if(next==groups+1&&next<=maxSpeakers){
          train.push_back(std::move(shortCandidateVectors[r]));
          result.trainingRunIndices.push_back(static_cast<int>(r));
          ++result.shortRunTrainingCount;groups=next;
        }
      }
    }
  } else {
    for(int w=0;w<windows;++w){int clean[local]={};for(int f=0;f<frames;++f){int count=0;for(int k=0;k<local;++k)count+=segments[(w*frames+f)*local+k];for(int k=0;k<local;++k)if(count==1&&segments[(w*frames+f)*local+k])clean[k]++;}
      for(int k=0;k<local;++k){int i=w*local+k;Vec emb(embeddings.begin()+i*dim,embeddings.begin()+(i+1)*dim);if(clean[k]>=.2*frames&&std::all_of(emb.begin(),emb.end(),[](double x){return std::isfinite(x);})){result.trainingIndices.push_back(i);train.push_back(std::move(emb));}}
    }
  }
  if(train.empty()){result.hard=std::vector<int>(windows*local,-2);return result;}
  // A single enrollment still goes through the same constrained assignment.
  // Other active local tracks must not inherit its identity unconditionally.
  if(train.size()==1)result.centroids=Matrix(1,train[0]);
  else {
    result.ahc=Ahc(train);result.features=plda.Apply(train);result.vbx=Vbx(result.features,plda.phi,result.ahc);
    for(size_t c=0;c<result.vbx.priors.size();++c)if(result.vbx.priors[c]>1e-7){Vec centroid(dim);double sum=0;for(size_t i=0;i<train.size();++i){double q=result.vbx.q[i][c];sum+=q;for(int j=0;j<dim;++j)centroid[j]+=q*train[i][j];}for(auto&v:centroid)v/=sum;result.centroids.push_back(std::move(centroid));}
  }
  if(runMode&&result.shortRunTrainingCount>0&&!result.ahc.empty()&&
     result.ahc.size()&&*std::max_element(result.ahc.begin(),result.ahc.end())+1<=maxSpeakers&&
     result.centroids.size()<static_cast<size_t>(*std::max_element(result.ahc.begin(),result.ahc.end())+1)){
    const int groups=*std::max_element(result.ahc.begin(),result.ahc.end())+1;
    // Short-run admission must not undo VBx merges among the long runs.
    // Only a missing short group can be recovered: the supported long-run
    // partition must already agree with VBx, independent of label numbering.
    std::vector<int> ahcToVbx(groups,-1),vbxToAhc(result.vbx.priors.size(),-1);
    bool sameLongPartition=true;
    const size_t longCount=train.size()-result.shortRunTrainingCount;
    for(size_t i=0;i<longCount;++i){
      const int a=result.ahc[i];
      const auto& q=result.vbx.q[i];
      const int v=std::max_element(q.begin(),q.end())-q.begin();
      if(result.vbx.priors[v]<=1e-7 || (ahcToVbx[a]>=0&&ahcToVbx[a]!=v) ||
         (vbxToAhc[v]>=0&&vbxToAhc[v]!=a)){sameLongPartition=false;break;}
      ahcToVbx[a]=v;vbxToAhc[v]=a;
    }
    if(sameLongPartition){
      result.centroids.assign(groups,Vec(dim));std::vector<int> counts(groups);
      for(size_t i=0;i<train.size();++i){const int c=result.ahc[i];if(c<0||c>=groups)continue;++counts[c];for(int j=0;j<dim;++j)result.centroids[c][j]+=train[i][j];}
      for(int c=0;c<groups;++c)for(int j=0;j<dim;++j)result.centroids[c][j]/=std::max(1,counts[c]);
      result.usedAhcFallback=true;
    }
  }
  if(maxSpeakers<1||maxSpeakers>4)throw std::runtime_error("invalid speaker cap");
  Matrix uncappedCentroids;
  if(result.centroids.size()>static_cast<size_t>(maxSpeakers)&&!runRms.empty()) {
    // Capacity is not evidence that two people are the same. Retain existing
    // VBx identities using the clean PCM level belonging to their training
    // runs; apply no level gate when all inferred identities fit the capacity.
    std::vector<int> columns;
    for(size_t c=0;c<result.vbx.priors.size();++c)if(result.vbx.priors[c]>1e-7)columns.push_back(c);
    result.capacityRms.assign(columns.size(),0.);Vec weights(columns.size());
    for(size_t i=0;i<train.size();++i){
      const int r=result.trainingRunIndices[i];const double level=runRms[r];
      for(size_t c=0;c<columns.size();++c){
        const double weight=result.vbx.q[i][columns[c]]*(runEnd[r]-runBegin[r]);
        result.capacityRms[c]+=weight*level*level;weights[c]+=weight;
      }
    }
    for(size_t c=0;c<columns.size();++c)result.capacityRms[c]=weights[c]>0?std::sqrt(result.capacityRms[c]/weights[c]):0.;
    const double maximum=*std::max_element(result.capacityRms.begin(),result.capacityRms.end());
    for(size_t c=0;c<columns.size();++c)if(result.capacityRms[c]>0&&result.capacityRms[c]>=maximum*.5)
      result.retainedClusters.push_back(static_cast<int>(c));
    std::stable_sort(result.retainedClusters.begin(),result.retainedClusters.end(),[&](int a,int b){return result.capacityRms[a]>result.capacityRms[b];});
    if(result.retainedClusters.size()>static_cast<size_t>(maxSpeakers))result.retainedClusters.resize(maxSpeakers);
    std::sort(result.retainedClusters.begin(),result.retainedClusters.end());
    uncappedCentroids=std::move(result.centroids);
    result.centroids.clear();
    for(int c:result.retainedClusters)result.centroids.push_back(uncappedCentroids[c]);
  } else if(result.centroids.size()>static_cast<size_t>(maxSpeakers)) {
    // Legacy whole-window callers do not yet carry clean-run PCM levels.
    auto labels=KMeans(train,maxSpeakers);
    result.centroids=Matrix(maxSpeakers,Vec(dim));
    for(int c=0;c<maxSpeakers;++c){std::vector<float> mean(dim);int count=0;
      for(size_t i=0;i<train.size();++i)if(labels[i]==c){++count;for(int j=0;j<dim;++j)mean[j]+=static_cast<float>(train[i][j]);}
      for(int j=0;j<dim;++j)result.centroids[c][j]=mean[j]/count;
    }
    result.usedKMeans=true;
  }
  const int k=result.centroids.size();
  if(k==0&&!uncappedCentroids.empty()){
    result.hard.assign(windows*local,-2);result.frame_hard.assign(windows*frames*local,-2);return result;
  }
  if(k<1)throw std::runtime_error("Community clustering has no centroid");
  auto scoreVector=[&](const Vec& vector){
    const Matrix& centers=uncappedCentroids.empty()?result.centroids:uncappedCentroids;
    Vec all(centers.size());int best=-1;
    for(size_t c=0;c<centers.size();++c){double dot=0,a=0,b=0;for(int j=0;j<dim;++j){double v=vector[j],u=centers[c][j];dot+=v*u;a+=v*v;b+=u*u;}all[c]=1+dot/std::sqrt(a*b);
      if(std::isfinite(all[c])&&(best<0||all[c]>all[best]))best=c;
    }
    if(uncappedCentroids.empty())return all;
    Vec kept(k,-std::numeric_limits<double>::infinity());
    // An overflow voice must stay anonymous, never inherit its second-best
    // foreground identity just because its own centroid was not retained.
    if(std::find(result.retainedClusters.begin(),result.retainedClusters.end(),best)!=result.retainedClusters.end())
      for(int c=0;c<k;++c)kept[c]=all[result.retainedClusters[c]];
    return kept;
  };
  Matrix scores(windows*local,Vec(k));double minimum=std::numeric_limits<double>::infinity();
  for(int i=0;i<windows*local;++i){scores[i]=scoreVector(Vec(embeddings.begin()+i*dim,embeddings.begin()+(i+1)*dim));for(double score:scores[i])if(std::isfinite(score))minimum=std::min(minimum,score);}
  result.scores=scores;
  if(runMode) {
    const int runCount=static_cast<int>(runWindow.size());
    std::vector<bool> eligible(runCount,false);
    std::vector<int> runFor(windows*frames*local,-1);
    std::vector<bool> hasRun(windows*local,false);
    Matrix runScores(runCount,Vec(k,-std::numeric_limits<double>::infinity()));
    auto runValue=[&](int r,int j)->double{
      if(shortCandidate[r]&&std::find(result.trainingRunIndices.begin(),result.trainingRunIndices.end(),r)!=result.trainingRunIndices.end())
        return embeddings[(runWindow[r]*local+runChannel[r])*dim+j];
      return runEmbeddings[r*dim+j];
    };
    for(int r=0;r<runCount;++r){
      const bool fullCandidate=shortCandidate[r]&&std::find(result.trainingRunIndices.begin(),result.trainingRunIndices.end(),r)!=result.trainingRunIndices.end();
      eligible[r]=fullCandidate||(runEnd[r]-runBegin[r]>=.2*frames&&std::all_of(runEmbeddings.begin()+r*dim,runEmbeddings.begin()+(r+1)*dim,[](float x){return std::isfinite(x);}));
      hasRun[runWindow[r]*local+runChannel[r]]=true;
      for(int f=runBegin[r];f<runEnd[r];++f)runFor[(runWindow[r]*frames+f)*local+runChannel[r]]=r;
      if(!eligible[r])continue;
      Vec vector(dim);for(int j=0;j<dim;++j)vector[j]=runValue(r,j);
      auto values=scoreVector(vector);
      for(int c=0;c<k;++c)if(std::isfinite(values[c]))runScores[r][c]=values[c];
    }
    result.frame_hard.assign(windows*frames*local,-2);
    std::vector<int> evidenceHard(windows*frames*local,-2);
    auto finite=[](const std::vector<double>& values){return std::any_of(values.begin(),values.end(),[](double v){return std::isfinite(v);});};
    auto assign=[&](const std::vector<std::vector<double>>& options,const std::vector<bool>& candidate,int initialUsed){
      std::vector<int> current(local,-2),best(local,-2);double bestScore=-std::numeric_limits<double>::infinity();
      std::function<void(int,int,double)> visit=[&](int row,int used,double score){
        if(row==local){if(score>bestScore){bestScore=score;best=current;}return;}
        if(!candidate[row]){current[row]=-2;visit(row+1,used,score);return;}
        bool assigned=false;for(int c=0;c<k;++c)if(!(used&(1<<c))&&std::isfinite(options[row][c])){assigned=true;current[row]=c;visit(row+1,used|(1<<c),score+options[row][c]);}
        current[row]=-2;if(!assigned)visit(row+1,used,score);
      };visit(0,initialUsed,0.);
      return best;
    };
    for(int w=0;w<windows;++w)for(int f=0;f<frames;++f){
      std::vector<std::vector<double>> options(local, std::vector<double>(k,-std::numeric_limits<double>::infinity()));
      std::vector<bool> candidate(local,false);
      for(int ch=0;ch<local;++ch)if(segments[(w*frames+f)*local+ch]){
        const int run=runFor[(w*frames+f)*local+ch];
        if(run>=0){if(eligible[run]){options[ch]=runScores[run];candidate[ch]=finite(options[ch]);}}
        else if(!hasRun[w*local+ch]){options[ch]=scores[w*local+ch];candidate[ch]=finite(options[ch]);}
      }
      const auto best=assign(options,candidate,0);
      int used=0;
      for(int ch=0;ch<local;++ch)if(candidate[ch]){
        evidenceHard[(w*frames+f)*local+ch]=result.frame_hard[(w*frames+f)*local+ch]=best[ch];
        if(best[ch]>=0)used|=1<<best[ch];
      }
      // Speech without assignable run evidence (overlap, short or unadmitted
      // runs) falls back to its channel's full-window vector against the same
      // centroids. It only takes identities still free at this frame, so run
      // evidence is never displaced; overflow voices score -inf and stay anonymous.
      std::vector<std::vector<double>> fallback(local, std::vector<double>(k,-std::numeric_limits<double>::infinity()));
      std::vector<bool> fallbackCandidate(local,false);bool anyFallback=false;
      for(int ch=0;ch<local;++ch)if(segments[(w*frames+f)*local+ch]&&!candidate[ch]){
        fallback[ch]=scores[w*local+ch];fallbackCandidate[ch]=finite(fallback[ch]);anyFallback=anyFallback||fallbackCandidate[ch];
      }
      if(anyFallback){
        const auto extra=assign(fallback,fallbackCandidate,used);
        for(int ch=0;ch<local;++ch)if(fallbackCandidate[ch])result.frame_hard[(w*frames+f)*local+ch]=extra[ch];
      }
    }
    // Window identities (and the public registry) keep using run evidence only.
    result.hard.assign(windows*local,-2);
    for(int w=0;w<windows;++w)for(int ch=0;ch<local;++ch){std::vector<int> votes(k);for(int f=0;f<frames;++f){int label=evidenceHard[(w*frames+f)*local+ch];if(label>=0)votes[label]++;}int best=0;for(int c=1;c<k;++c)if(votes[c]>votes[best])best=c;if(votes[best]>0)result.hard[w*local+ch]=best;}
    return result;
  }
  if(result.usedKMeans) {
    // The upstream cap branch explicitly disables constrained assignment.
    result.hard=std::vector<int>(windows*local,-2);
    for(int i=0;i<windows*local;++i)if(activity[i]){
      int best=0;
      for(int c=0;c<k;++c){if(!std::isfinite(scores[i][c])){best=c;break;}if(scores[i][c]>scores[i][best])best=c;}
      result.hard[i]=best;
    }
    return result;
  }
  // Silent tracks must rank below every active track, including when their
  // embeddings are zero/NaN. A tie can otherwise consume the only identity.
  double inactive=minimum-1.;
  for(int i=0;i<windows*local;++i)for(auto& score:scores[i]){if(!activity[i])score=inactive;else if(!std::isfinite(score))score=minimum;}
  result.hard=std::vector<int>(windows*local,-2);
  for(int w=0;w<windows;++w){
    std::vector<int> current(local,-2),best(local,-2);double bestScore=-std::numeric_limits<double>::infinity();
    std::function<void(int,int,int,double)> visit=[&](int row,int used,int assigned,double score){
      if(row==local){if(assigned==std::min(local,k)&&score>bestScore){bestScore=score;best=current;}return;}
      for(int c=0;c<k;++c)if(!(used&(1<<c))){current[row]=c;visit(row+1,used|(1<<c),assigned+1,score+scores[w*local+row][c]);}
      current[row]=-2;if(k<local)visit(row+1,used,assigned,score);
    };visit(0,0,0,0.);
    for(int j=0;j<local;++j)if(activity[w*local+j])result.hard[w*local+j]=best[j];
  }
  return result;
}
}
'''

HARNESS = r'''

#include <chrono>
#include <cstring>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <random>
#include <string>

constexpr int frames=589, local=3, dim=256;
const float missing=std::numeric_limits<float>::quiet_NaN();
std::string context;
int comparisons=0;
void Require(bool condition,const std::string& detail) {
  if(!condition)throw std::runtime_error(context+": "+detail);
}
template<class T> void Equal(const T& actual,const T& expected,const std::string& field) {
  Require(actual==expected,field);
}
void Equal(double actual,double expected,const std::string& field) {
  uint64_t a,b;std::memcpy(&a,&actual,sizeof(a));std::memcpy(&b,&expected,sizeof(b));
  if(a!=b) {
    std::ostringstream message;
    message<<field<<" double bits "<<std::hex<<a<<" != "<<b;
    Require(false,message.str());
  }
}
template<class T> void Equal(const std::vector<T>& actual,const std::vector<T>& expected,const std::string& field) {
  Equal(actual.size(),expected.size(),field+".size");
  for(size_t i=0;i<actual.size();++i)Equal(actual[i],expected[i],field+"["+std::to_string(i)+"]");
}
template<class A,class B> void EqualResult(const A& a,const B& b) {
#define FIELD(name) Equal(a.name,b.name,#name)
  FIELD(trainingIndices);FIELD(ahc);FIELD(hard);FIELD(trainingRunIndices);FIELD(frame_hard);
  FIELD(features);FIELD(centroids);FIELD(scores);FIELD(capacityRms);FIELD(retainedClusters);
  FIELD(usedKMeans);FIELD(usedAhcFallback);FIELD(shortRunTrainingCount);
  FIELD(vbx.q);FIELD(vbx.priors);FIELD(vbx.objectives);
#undef FIELD
}
template<class A,class B> void EqualTurns(const A& a,const B& b,const std::string& field) {
  Equal(a.size(),b.size(),field+".size");
  for(size_t i=0;i<a.size();++i) {
    const auto key=field+"["+std::to_string(i)+"]";
    Equal(a[i].begin,b[i].begin,key+".begin");
    Equal(a[i].end,b[i].end,key+".end");
    Equal(a[i].speaker,b[i].speaker,key+".speaker");
  }
}
template<class T> T MakePlda(double phi=1.) {
  T p;p.mean1.assign(dim,0.);p.mean2.assign(128,0.);p.mu.assign(128,0.);p.phi.assign(128,phi);
  p.lda.assign(dim,std::vector<double>(128));p.transform.assign(128,std::vector<double>(128));
  for(int d=0;d<128;++d){p.lda[d][d]=1.;p.transform[d][d]=1.;}
  return p;
}
std::vector<float> Axis(int axis) {
  std::vector<float> result(dim);result[axis]=1.;return result;
}
struct Input {
  int windows,cap=4;
  double phi=1.,begin=0.;
  std::vector<float> segments,embeddings,runs,rms;
  std::vector<int32_t> ranges;
  std::vector<double> starts;
  explicit Input(int n):windows(n),segments(n*frames*local),embeddings(n*local*dim,missing),starts(n) {
    for(int w=0;w<n;++w)starts[w]=w*16000.; // Preserve the production one-second hop.
  }
  void Speech(int w,int ch,int b,int e) {
    for(int f=b;f<e;++f)segments[(w*frames+f)*local+ch]=1.;
  }
  void Full(int w,int ch,const std::vector<float>& vector) {
    std::copy(vector.begin(),vector.end(),embeddings.begin()+(w*local+ch)*dim);
  }
  void Run(int w,int ch,int b,int e,const std::vector<float>& vector) {
    ranges.insert(ranges.end(),{w,ch,b,e});runs.insert(runs.end(),vector.begin(),vector.end());
  }
  void Voice(int w,int ch,int b,int e,int axis) {
    Speech(w,ch,b,e);Full(w,ch,Axis(axis));Run(w,ch,b,e,Axis(axis));
  }
};
community::ClusterResult Check(const Input& x,const std::string& name) {
  context=name;
  const auto expected=reference::Cluster(x.segments,x.embeddings,x.windows,MakePlda<reference::Plda>(x.phi),x.cap,x.runs,x.ranges,x.rms);
  const auto actual=community::Cluster(x.segments,x.embeddings,x.windows,MakePlda<community::Plda>(x.phi),x.cap,x.runs,x.ranges,x.rms);
  EqualResult(actual,expected);
  // Compare both public reconstruction paths, including exact turn ordering.
  if(x.windows>0)for(bool frame:{false,true}) {
    auto oldTurns=reference::Reconstruct(x.segments,expected.hard,x.starts,x.begin,x.cap,frame?expected.frame_hard:std::vector<int>{});
    auto newTurns=community::Reconstruct(x.segments,actual.hard,x.starts,x.begin,x.cap,frame?actual.frame_hard:std::vector<int>{});
    EqualTurns(newTurns,oldTurns,frame?"frameTurns":"windowTurns");
  }
  Require(actual.centroids.size()<=static_cast<size_t>(x.cap),"centroids exceed cap");
  ++comparisons;return actual;
}
Input SixVoices(bool runMode=true) {
  Input x(24);
  for(int w=0;w<x.windows;++w) {
    if(runMode)x.Voice(w,0,0,frames,w%6);
    else for(int ch=0;ch<local;++ch){x.Speech(w,ch,ch*180,(ch+1)*180);x.Full(w,ch,Axis(w%6));}
  }
  return x;
}
void Assignment() {
  for(int cap=1;cap<=4;++cap) {
    Input x(5);x.cap=cap;
    for(int w=0;w<cap;++w)x.Voice(w,0,0,150,w);
    // All active channels tie against all enrolled identities. There are more
    // candidates than identities at cap=1/2, exercising the no-free-ID branch.
    for(int ch=0;ch<local;++ch){x.Speech(4,ch,250,400);x.Full(4,ch,Axis(10));}
    auto result=Check(x,"ties-overlap-cap-"+std::to_string(cap));
    Require(result.centroids.size()==static_cast<size_t>(cap),"fixture must exercise this k");
    for(int ch=0;ch<local;++ch)Require(result.frame_hard[(4*frames+260)*local+ch]==(ch<cap?ch:-2),"tie order changed");
  }
  Input multiple(2);
  multiple.Voice(0,0,10,150,0);multiple.Voice(0,0,310,450,1);
  multiple.Voice(0,1,100,280,2);multiple.Voice(1,0,0,150,0);
  multiple.Voice(1,1,180,330,1);multiple.Voice(1,2,360,510,2);
  // Unenrollable partial run plus overlap falls back, without contributing a vote.
  multiple.Speech(0,2,120,160);multiple.Full(0,2,Axis(0));
  multiple.Run(0,2,120,135,std::vector<float>(dim,missing));
  auto multi=Check(multiple,"multiple-runs-and-fallback");
  Require(multi.hard[2]==-2&&multi.frame_hard[155*local+2]>=0,"fallback must not vote");
  // The two equally long runs vote for different IDs: lower ID wins.
  const int a=multi.frame_hard[20*local],b=multi.frame_hard[320*local];
  Require(a>=0&&b>=0&&a!=b&&multi.hard[0]==std::min(a,b),"equal evidence votes");
  multiple.starts={16000.*3600,0};multiple.begin=16000.*3600;
  Check(multiple,"pruned-historical-window-and-unordered-starts");
  multiple.starts={0,0};multiple.begin=0;
  Check(multiple,"duplicate-window-starts");
}
void Contracts() {
  Input x(2);
  x.Voice(0,0,0,frames,0);x.Full(1,0,Axis(1));x.Speech(1,0,0,frames);
  // Individually valid ranges are allowed to be partial, unordered, duplicated
  // or overlapping. runFor uses the last listed range covering a frame.
  x.Run(1,0,350,520,Axis(1));x.Run(1,0,10,200,Axis(2));
  auto unordered=Check(x,"unordered-partial-runs");
  Require(unordered.frame_hard[(frames+30)*local]!=unordered.frame_hard[(frames+400)*local],"unordered identities");
  x.Run(1,0,10,200,Axis(3));
  auto duplicate=Check(x,"duplicate-ranges-last-wins");
  Require(duplicate.frame_hard[(frames+30)*local]>=0,"duplicate range accepted");
  x.Run(1,0,120,400,Axis(1));
  Check(x,"overlapping-ranges-last-wins");
  std::reverse(x.starts.begin(),x.starts.end());
  Check(x,"unordered-starts-and-ranges");
  // Partial metadata is the old whole-window interface, when no RMS is supplied.
  x.ranges.push_back(0);x.runs.clear();Check(x,"incomplete-range-shape-legacy-fallback");
  x.ranges={0,0,0,frames};Check(x,"incomplete-run-vectors-legacy-fallback");
  Input silentRange(1);silentRange.Speech(0,0,300,500);silentRange.Full(0,0,Axis(0));
  silentRange.Run(0,0,0,150,Axis(1));
  Check(silentRange,"range-need-not-cover-all-active-frames");
}
void ShortRuns() {
  for(int n:{1,2,3,80,117,118})for(bool overlap:{false,true})for(int cap:{1,4}) {
    Input x(2);x.cap=cap;x.Voice(0,0,0,150,0);
    x.Speech(1,0,0,n);x.Full(1,0,Axis(1));
    x.Run(1,0,0,n,n<118?std::vector<float>(dim,missing):Axis(1));
    if(overlap) {
      x.Speech(1,0,n,n+22);x.Speech(1,1,n,n+22);x.Full(1,1,Axis(0));
      x.Run(1,1,n,n+22,std::vector<float>(dim,missing));
    }
    auto r=Check(x,"short-"+std::to_string(n)+"-overlap-"+std::to_string(overlap)+"-cap-"+std::to_string(cap));
    if(n<=2&&cap==4)Require(r.shortRunTrainingCount==(overlap?0:1),"one/two-frame mask ownership");
  }
  Input repeated(2);repeated.Voice(0,0,0,150,0);
  repeated.Voice(1,0,0,20,1);repeated.Run(1,0,0,20,Axis(1));
  auto duplicate=Check(repeated,"duplicate-short-clean-runs");
  Require(duplicate.shortRunTrainingCount==0,"duplicate short ranges are not independent admission");
  repeated.ranges.resize(8);repeated.runs.resize(2*dim);
  repeated.Voice(1,0,200,220,2);Check(repeated,"two-short-clean-runs-on-one-channel");
  Input empty(1);empty.Voice(0,0,10,11,0);
  auto none=Check(empty,"no-long-training-short-only");
  Require(none.centroids.empty()&&none.frame_hard.empty(),"no-training path");
  Input merged(6);merged.phi=10.;
  for(int w=0;w<6;++w)merged.Voice(w,0,0,w==5?68:200,w<4?0:w-3);
  auto same=Check(merged,"short-admission-does-not-split-long-vbx-partition");
  Require(same.shortRunTrainingCount==1&&same.centroids.size()==1&&!same.usedAhcFallback,"long partition remains merged");
  Input recovered(6);recovered.phi=10.;
  for(int w=0;w<6;++w)recovered.Voice(w,0,0,w==5?68:200,w==5?1:0);
  auto restored=Check(recovered,"short-ahc-fallback-with-unchanged-long-partition");
  Require(restored.usedAhcFallback&&restored.centroids.size()==2,"short AHC recovery branch");
}
void Capacity() {
  for(int cap=1;cap<=4;++cap) {
    auto x=SixVoices();x.cap=cap;
    auto kmeans=Check(x,"run-kmeans-cap-"+std::to_string(cap));
    Require(kmeans.usedKMeans&&kmeans.centroids.size()==static_cast<size_t>(cap),"run kmeans cap branch");
    for(int w=0;w<x.windows;++w)x.rms.push_back(w%6<4?.7f+.1f*(w%6):.1f);
    auto capped=Check(x,"background-overflow-cap-"+std::to_string(cap));
    Require(!capped.usedKMeans&&capped.capacityRms.size()==6,"uncapped k must exceed four");
    for(int w=0;w<x.windows;++w)if(w%6>=4)Require(capped.hard[w*local]==-2,"overflow stays anonymous");
    std::fill(x.rms.begin(),x.rms.end(),0.);
    auto zero=Check(x,"zero-rms-k-zero-cap-"+std::to_string(cap));
    Require(zero.centroids.empty()&&zero.frame_hard.size()==x.segments.size(),"zero k returns before assignment");
    Require(std::all_of(zero.frame_hard.begin(),zero.frame_hard.end(),[](int v){return v==-2;}),"zero k stays anonymous");
    auto legacy=SixVoices(false);legacy.cap=cap;
    auto old=Check(legacy,"whole-window-kmeans-cap-"+std::to_string(cap));
    Require(old.usedKMeans&&old.frame_hard.empty(),"whole-window interface branch");
  }
  Input silence(1);Check(silence,"silence-no-training");
  Input empty(0);Check(empty,"zero-windows-cluster-only");
  Input one(1);one.Speech(0,2,0,150);one.Full(0,2,Axis(0));
  Check(one,"whole-window-single-enrollment");
  one.Speech(0,0,200,220);one.Full(0,0,Axis(1));
  Check(one,"whole-window-short-unenrolled");
  Input invalid(1);invalid.Voice(0,0,0,150,0);
  for(int cap:{0,5}) {
    invalid.cap=cap;context="invalid-cap-"+std::to_string(cap);
    bool oldThrows=false,newThrows=false;
    try{reference::Cluster(invalid.segments,invalid.embeddings,1,MakePlda<reference::Plda>(),cap,invalid.runs,invalid.ranges);}
    catch(const std::runtime_error&){oldThrows=true;}
    try{community::Cluster(invalid.segments,invalid.embeddings,1,MakePlda<community::Plda>(),cap,invalid.runs,invalid.ranges);}
    catch(const std::runtime_error&){newThrows=true;}
    Require(oldThrows&&newThrows,"cap rejected before fixed storage");
  }
}
void Generated() {
  std::mt19937 rng(0x430a13);
  for(int sample=0;sample<64;++sample) {
    Input base(1+rng()%5);
    for(int w=0;w<base.windows;++w)for(int ch=0;ch<local;++ch) {
      const int axis=rng()%6;
      auto full=Axis(axis);
      if(sample%3==0)for(int d=0;d<16;++d)full[d]+=(static_cast<int>(rng()%65)-32)*0.0009765625f;
      base.Full(w,ch,full);
      for(int r=0;r<1+sample%3;++r) {
        int b=rng()%440,e=std::min(frames,b+1+static_cast<int>(rng()%230));
        base.Speech(w,ch,b,e);
        if(rng()%4)base.Run(w,ch,b,e,rng()%5?full:std::vector<float>(dim,missing));
      }
    }
    // Deliberately add a repeat, preserving last-write semantics in runFor.
    if(sample%4==0&&!base.ranges.empty()) {
      auto range=std::vector<int32_t>(base.ranges.begin(),base.ranges.begin()+4);
      base.ranges.insert(base.ranges.end(),range.begin(),range.end());
      auto copy=std::vector<float>(base.runs.begin(),base.runs.begin()+dim);
      base.runs.insert(base.runs.end(),copy.begin(),copy.end());
    }
    if(sample%5==0)for(size_t r=0;r<base.ranges.size()/4;++r)base.rms.push_back((1+rng()%10)*.125f);
    if(sample%7==0){base.ranges.clear();base.runs.clear();base.rms.clear();}
    for(int cap=1;cap<=4;++cap){base.cap=cap;Check(base,"generated-"+std::to_string(sample)+"-cap-"+std::to_string(cap));}
  }
}
Input BenchmarkInput(int n) {
  Input x(n);
  for(int w=0;w<n;++w) {
    x.Voice(w,0,0,w<4?150:60,w%4);
    x.Speech(w,0,150,frames);
    for(int ch=1;ch<local;++ch){x.Speech(w,ch,150,frames);x.Full(w,ch,Axis((w+ch)%4));}
  }
  return x;
}
volatile size_t benchmarkSink=0;
void Benchmark() {
  std::cout<<"windows,stage,implementation,sample,cpu_ms,wall_ms\n"<<std::fixed<<std::setprecision(6);
  for(int n:{32,128,512}) {
    auto x=BenchmarkInput(n);Check(x,"benchmark-input-"+std::to_string(n));
    auto p=MakePlda<community::Plda>();auto q=MakePlda<reference::Plda>();
    for(bool turns:{false,true})for(int sample=-1;sample<7;++sample)for(int order=0;order<2;++order) {
      bool old=(order==(sample&1));
      auto wall=std::chrono::steady_clock::now();auto cpu=std::clock();
      if(old) {
        auto result=reference::Cluster(x.segments,x.embeddings,n,q,4,x.runs,x.ranges);
        benchmarkSink+=result.frame_hard.size()+result.hard.size();
        if(turns)benchmarkSink+=reference::Reconstruct(x.segments,result.hard,x.starts,0,4,result.frame_hard).size();
      } else {
        auto result=community::Cluster(x.segments,x.embeddings,n,p,4,x.runs,x.ranges);
        benchmarkSink+=result.frame_hard.size()+result.hard.size();
        if(turns)benchmarkSink+=community::Reconstruct(x.segments,result.hard,x.starts,0,4,result.frame_hard).size();
      }
      double cpuMs=(std::clock()-cpu)*1000./CLOCKS_PER_SEC;
      double wallMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-wall).count();
      if(sample>=0)std::cout<<n<<","<<(turns?"cluster+turns":"cluster")<<","<<(old?"reference":"current")<<","<<sample<<","<<cpuMs<<","<<wallMs<<"\n";
    }
  }
}
int main(int argc,char** argv) {
  try {
    const std::string mode=argc>1?argv[1]:"all";
    if(mode=="all"||mode=="assignment")Assignment();
    if(mode=="all"||mode=="contracts")Contracts();
    if(mode=="all"||mode=="short")ShortRuns();
    if(mode=="all"||mode=="capacity")Capacity();
    if(mode=="all"||mode=="generated")Generated();
    if(mode=="benchmark")Benchmark();
    else std::cout<<"PASS "<<mode<<": "<<comparisons<<" complete ClusterResult and bitwise turn comparisons\n";
    return 0;
  } catch(const std::exception& error) {
    std::cerr<<context<<": "<<error.what()<<"\n";return 1;
  }
}
'''


def source(reference=REFERENCE):
    oracle = Path(__file__).with_name('community_ahc_reference.h').as_posix()
    return ('#include "community_cluster.h"\n#include <sstream>\n' +
            f'#include "{oracle}"\n' + reference + HARNESS)


class HarmonyCommunityClusterParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            raise unittest.SkipTest('C++17 compiler unavailable')
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        cpp = directory / 'parity.cpp'
        cls.binary = directory / 'parity'
        cpp.write_text(source())
        subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(CPP),
                        str(cpp), '-o', str(cls.binary)], check=True, timeout=60)

    def run_case(self, mode):
        completed = subprocess.run([str(self.binary), mode], text=True,
                                   capture_output=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('PASS ' + mode, completed.stdout)

    def test_caps_ties_overlap_multirun_and_reconstruction(self):
        self.run_case('assignment')

    def test_partial_unordered_duplicate_and_overlapping_legacy_ranges(self):
        self.run_case('contracts')

    def test_short_clean_mask_ownership_and_admission(self):
        self.run_case('short')

    def test_background_overflow_zero_centroids_and_whole_window_api(self):
        self.run_case('capacity')

    def test_seeded_mixed_inputs_match_all_fields_and_double_bits(self):
        self.run_case('generated')


if __name__ == '__main__':
    unittest.main()
