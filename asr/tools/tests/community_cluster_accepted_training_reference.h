#pragma once
#include "community_cluster.h"

// Frozen complete Cluster before accepted-training labels were retained.
// Source header SHA256: 1c07657d4e3347301f33342e5f7ca03b4a1decce0a887ae7db635e0dcdb6a982
// Cluster block SHA256: 6cbdfb4caab3aea86aa657396920aae600e2d12b37c42dcc55221fb63314a46d
// Helpers/types (including byte-identical Ahc, PLDA, VBx and KMeans) are shared;
// the entire Cluster control flow below is independent of production Cluster.
// The older reference::Cluster/Reconstruct and community_ahc_reference::Ahc
// remain a separate oracle for arithmetic, every result field and turn bits.
namespace accepted_training_reference {
using community::Vec; using community::Matrix; using community::Plda;
using community::ClusterResult; using community::CancellationToken;
using community::CheckCancellation; using community::Ahc;
using community::Vbx; using community::KMeans;
inline ClusterResult Cluster(const std::vector<float>& segments,const std::vector<float>& embeddings,int windows,const Plda& plda,int maxSpeakers=4,
                            const std::vector<float>& runEmbeddings={},const std::vector<int32_t>& runRanges={},
                            const std::vector<float>& runRms={},
                             const CancellationToken* cancellation = nullptr) {
  constexpr int frames=589,local=3,dim=256;
  if(segments.size()!=windows*frames*local||embeddings.size()!=windows*local*dim)throw std::runtime_error("invalid cluster shapes");
  CheckCancellation(cancellation);
  ClusterResult result;Matrix train;std::vector<int> activity(windows*local);
  for(int w=0;w<windows;++w){
    CheckCancellation(cancellation);
    for(int f=0;f<frames;++f){
      for(int k=0;k<local;++k) activity[w*local+k]+=segments[(w*frames+f)*local+k];
    }
  }
  const bool runMode=!runRanges.empty()&&runRanges.size()%4==0&&runEmbeddings.size()==(runRanges.size()/4)*dim;
  if(!runRms.empty()&&(!runMode||runRms.size()!=runRanges.size()/4||
     !std::all_of(runRms.begin(),runRms.end(),[](float v){return std::isfinite(v)&&v>=0;})))
    throw std::runtime_error("invalid Community run level evidence");
  std::vector<int> runWindow,runChannel,runBegin,runEnd;
  std::vector<bool> shortCandidate;
  std::vector<Vec> shortCandidateVectors;
  if(runMode){
    for(size_t i=0;i<runRanges.size();i+=4){
      CheckCancellation(cancellation);
      int w=runRanges[i],k=runRanges[i+1],b=runRanges[i+2],e=runRanges[i+3];
      if(w<0||w>=windows||k<0||k>=local||b<0||e<=b||e>frames)
        throw std::runtime_error("invalid Community run range");
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
    auto groupCount=[&](const Matrix& values){
      CheckCancellation(cancellation);
      if(values.empty())return 0;
      auto labels=Ahc(values,cancellation);return *std::max_element(labels.begin(),labels.end())+1;
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
    for(int w=0;w<windows;++w){
      int clean[local]={};
      for(int f=0;f<frames;++f){
        int count=0;
        for(int k=0;k<local;++k) count+=segments[(w*frames+f)*local+k];
        for(int k=0;k<local;++k)if(count==1&&segments[(w*frames+f)*local+k])clean[k]++;
      }
      for(int k=0;k<local;++k){
        int i=w*local+k;
        Vec emb(embeddings.begin()+i*dim,embeddings.begin()+(i+1)*dim);
        if(clean[k]>=.2*frames&&std::all_of(emb.begin(),emb.end(),[](double x){return std::isfinite(x);})){result.trainingIndices.push_back(i);train.push_back(std::move(emb));}
      }
    }
  }
  if(train.empty()){result.hard=std::vector<int>(windows*local,-2);return result;}
  // A single enrollment still goes through the same constrained assignment.
  // Other active local tracks must not inherit its identity unconditionally.
  if(train.size()==1)result.centroids=Matrix(1,train[0]);
  else {
    result.ahc=Ahc(train,cancellation);result.features=plda.Apply(train,cancellation);result.vbx=Vbx(result.features,plda.phi,result.ahc,cancellation);
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
    auto labels=KMeans(train,maxSpeakers,cancellation);
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
    // Both cap branches above leave at most maxSpeakers <= 4 centroids. The
    // all-zero RMS case returns with k == 0 before reaching this fixed storage.
    if(k>4)throw std::runtime_error("Community clustering exceeds assignment capacity");
    using OptionRows=std::array<std::array<double,4>,local>;
    using CandidateRows=std::array<bool,local>;
    const double negativeInfinity=-std::numeric_limits<double>::infinity();
    auto resetOptions=[&](OptionRows& options,CandidateRows& candidate){
      for(int row=0;row<local;++row){options[row].fill(negativeInfinity);candidate[row]=false;}
    };
    auto finiteRow=[&](const std::array<double,4>& values){
      for(int c=0;c<k;++c)if(std::isfinite(values[c]))return true;
      return false;
    };
    auto assign=[&](const OptionRows& options,const CandidateRows& candidate,int initialUsed){
      std::array<int,local> current{},best{};current.fill(-2);best.fill(-2);double bestScore=negativeInfinity;
      auto visit=[&](auto&& self,int row,int used,double score)->void{
        if(row==local){if(score>bestScore){bestScore=score;best=current;}return;}
        if(!candidate[row]){current[row]=-2;self(self,row+1,used,score);return;}
        bool assigned=false;for(int c=0;c<k;++c)if(!(used&(1<<c))&&std::isfinite(options[row][c])){assigned=true;current[row]=c;self(self,row+1,used|(1<<c),score+options[row][c]);}
        current[row]=-2;if(!assigned)self(self,row+1,used,score);
      };visit(visit,0,initialUsed,0.);
      return best;
    };
    std::vector<int> evidenceVotes(windows*local*k);
    for(int w=0;w<windows;++w)for(int f=0;f<frames;++f){
      OptionRows options,fallback;CandidateRows candidate,fallbackCandidate;resetOptions(options,candidate);resetOptions(fallback,fallbackCandidate);
      for(int ch=0;ch<local;++ch)if(segments[(w*frames+f)*local+ch]){
        const int run=runFor[(w*frames+f)*local+ch];
        if(run>=0){
          if(eligible[run]){for(int c=0;c<k;++c)options[ch][c]=runScores[run][c];candidate[ch]=finiteRow(options[ch]);}
        } else if(!hasRun[w*local+ch]){
          for(int c=0;c<k;++c)options[ch][c]=scores[w*local+ch][c];candidate[ch]=finiteRow(options[ch]);
        }
      }
      const auto best=assign(options,candidate,0);
      int used=0;
      for(int ch=0;ch<local;++ch)if(candidate[ch]){
        result.frame_hard[(w*frames+f)*local+ch]=best[ch];
        if(best[ch]>=0){used|=1<<best[ch];evidenceVotes[(w*local+ch)*k+best[ch]] += 1;}
      }
      // Speech without assignable run evidence (overlap, short or unadmitted
      // runs) falls back to its channel's full-window vector against the same
      // centroids. It only takes identities still free at this frame, so run
      // evidence is never displaced; overflow voices score -inf and stay anonymous.
      bool anyFallback=false;
      for(int ch=0;ch<local;++ch)if(segments[(w*frames+f)*local+ch]&&!candidate[ch]){
        for(int c=0;c<k;++c)fallback[ch][c]=scores[w*local+ch][c];
        fallbackCandidate[ch]=finiteRow(fallback[ch]);anyFallback=anyFallback||fallbackCandidate[ch];
      }
      if(anyFallback){
        const auto extra=assign(fallback,fallbackCandidate,used);
        for(int ch=0;ch<local;++ch)if(fallbackCandidate[ch])result.frame_hard[(w*frames+f)*local+ch]=extra[ch];
      }
    }
    // Window identities (and the public registry) keep using run evidence only.
    result.hard.assign(windows*local,-2);
    for(int w=0;w<windows;++w)for(int ch=0;ch<local;++ch){
      const int* votes=evidenceVotes.data()+(w*local+ch)*k;int best=0;
      for(int c=1;c<k;++c)if(votes[c]>votes[best])best=c;
      if(votes[best]>0)result.hard[w*local+ch]=best;
    }
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
}  // namespace accepted_training_reference
