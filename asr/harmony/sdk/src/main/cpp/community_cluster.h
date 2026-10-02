#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <tuple>
#include <vector>
#include "community_kmeans.h"

namespace community {
using Vec=std::vector<double>;
using Matrix=std::vector<Vec>;
struct Plda {
  Vec mean1,mean2,mu,phi;
  Matrix lda,transform;
  Matrix Apply(const Matrix& input) const {
    Matrix result;
    for(const auto& row:input) {
      Vec x(row.size());double norm=0;
      for(size_t d=0;d<x.size();++d){x[d]=row[d]-mean1[d];norm+=x[d]*x[d];}
      norm=std::sqrt(x.size()/norm);for(auto& v:x)v*=norm;
      Vec y(mean2.size());norm=0;
      for(size_t d=0;d<y.size();++d){y[d]=-mean2[d];for(size_t j=0;j<x.size();++j)y[d]+=x[j]*lda[j][d];norm+=y[d]*y[d];}
      norm=std::sqrt(y.size()/norm);for(size_t d=0;d<y.size();++d)y[d]=y[d]*norm-mu[d];
      Vec z(phi.size());for(size_t d=0;d<z.size();++d)for(size_t j=0;j<y.size();++j)z[d]+=y[j]*transform[d][j];
      result.push_back(std::move(z));
    }
    return result;
  }
};
// Centroid linkage followed by distance fcluster; the subtree maximum handles
// inversions in centroid linkage exactly as scipy's distance criterion does.
inline std::vector<int> Ahc(const Matrix& x) {
  int n=x.size();Matrix centers(2*n-1);std::vector<int> count(2*n-1,1),left(2*n-1,-1),right(2*n-1,-1);
  std::vector<bool> alive(2*n-1,false);Vec height(2*n-1);
  for(int i=0;i<n;++i){centers[i]=x[i];double norm=0;for(auto v:x[i])norm+=v*v;norm=std::sqrt(norm);for(auto&v:centers[i])v/=norm;alive[i]=true;}
  auto distance=[&](int a,int b){double d=0;for(size_t j=0;j<x[0].size();++j){double v=centers[a][j]-centers[b][j];d+=v*v;}return std::sqrt(d);};
  using Pair=std::tuple<double,int,int>;
  // Each row keeps a lower bound for its nearest active higher-ID neighbor.
  // Removing that neighbor can only increase the bound. A newly merged center
  // is checked immediately, including centroid-linkage distance inversions.
  const double infinity=std::numeric_limits<double>::infinity();
  std::vector<Pair> nearest(2*n-1,Pair{infinity,0,-1});
  auto refresh=[&](int a,int limit){
    Pair best{infinity,a,-1};
    for(int b=a+1;b<limit;++b)if(alive[b])best=std::min(best,Pair{distance(a,b),a,b});
    nearest[a]=best;
  };
  for(int a=0;a<n;++a)refresh(a,n);
  for(int node=n;node<2*n-1;++node){
    Pair closest;
    for(;;){
      closest=Pair{infinity,0,-1};
      for(int a=0;a<node;++a)if(alive[a])closest=std::min(closest,nearest[a]);
      int a=std::get<1>(closest),b=std::get<2>(closest);
      if(b<0)throw std::runtime_error("Community clustering has no finite distance");
      if(alive[b])break;
      refresh(a,node);
    }
    auto [d,a,b]=closest;alive[a]=alive[b]=false;alive[node]=true;
    left[node]=a;right[node]=b;count[node]=count[a]+count[b];height[node]=std::max({d,height[a],height[b]});
    centers[node].resize(x[0].size());for(size_t j=0;j<x[0].size();++j)centers[node][j]=(centers[a][j]*count[a]+centers[b][j]*count[b])/count[node];
    for(int c=0;c<node;++c)if(alive[c])nearest[c]=std::min(nearest[c],Pair{distance(c,node),c,node});
    nearest[node]=Pair{infinity,node,-1};
  }
  std::vector<int> labels(n,-1);int next=0;
  std::function<void(int,int)> assign=[&](int node,int label){if(node<n){labels[node]=label;return;}assign(left[node],label);assign(right[node],label);};
  std::function<void(int)> cut=[&](int node){
    if(node<n||height[node]<=.6){assign(node,next++);return;}
    // scipy visits both internal children before numbering singleton leaves.
    // Preserve this order because equal reconstruction scores use cluster order.
    if(left[node]>=n)cut(left[node]);
    if(right[node]>=n)cut(right[node]);
    if(left[node]<n)cut(left[node]);
    if(right[node]<n)cut(right[node]);
  };
  cut(2*n-2);return labels;
}
struct VbxResult { Matrix q;Vec priors;Vec objectives; };
inline VbxResult Vbx(const Matrix& x,const Vec& phi,const std::vector<int>& initial) {
  const int n=x.size(),d=phi.size(),k=*std::max_element(initial.begin(),initial.end())+1;
  constexpr double fa=.07,fb=.8;const double smooth=std::exp(7.);
  VbxResult result;auto& q=result.q;auto& prior=result.priors;
  q=Matrix(n,Vec(k,1./(smooth+k-1)));prior=Vec(k,1./k);
  Matrix rho=x;Vec g(n);for(int i=0;i<n;++i){q[i][initial[i]]=smooth/(smooth+k-1);double s=0;for(int j=0;j<d;++j){rho[i][j]*=std::sqrt(phi[j]);s+=x[i][j]*x[i][j];}g[i]=-.5*(s+d*std::log(2*std::acos(-1.)));}
  for(int iteration=0;iteration<20;++iteration){
    Matrix inv(k,Vec(d)),alpha(k,Vec(d));Vec sums(k),penalty(k);
    for(int i=0;i<n;++i)for(int c=0;c<k;++c){sums[c]+=q[i][c];for(int j=0;j<d;++j)alpha[c][j]+=q[i][c]*rho[i][j];}
    double objective=0;
    for(int c=0;c<k;++c)for(int j=0;j<d;++j){inv[c][j]=1./(1+fa/fb*sums[c]*phi[j]);alpha[c][j]*=fa/fb*inv[c][j];double aa=alpha[c][j]*alpha[c][j];penalty[c]+=.5*(inv[c][j]+aa)*phi[j];objective+=fb*.5*(std::log(inv[c][j])-inv[c][j]-aa+1);}
    Vec newPrior(k);
    for(int i=0;i<n;++i){
      Vec logits(k);double maximum=-std::numeric_limits<double>::infinity();
      for(int c=0;c<k;++c){double dot=0;for(int j=0;j<d;++j)dot+=rho[i][j]*alpha[c][j];logits[c]=fa*(dot-penalty[c]+g[i])+std::log(prior[c]+1e-8);maximum=std::max(maximum,logits[c]);}
      double sum=0;for(auto v:logits)sum+=std::exp(v-maximum);double logSum=maximum+std::log(sum);objective+=logSum;
      for(int c=0;c<k;++c){q[i][c]=std::exp(logits[c]-logSum);newPrior[c]+=q[i][c];}
    }
    double priorSum=std::accumulate(newPrior.begin(),newPrior.end(),0.);for(int c=0;c<k;++c)prior[c]=newPrior[c]/priorSum;
    result.objectives.push_back(objective);
    if(iteration>0&&objective-result.objectives[iteration-1]<1e-4)break;
  }
  return result;
}
struct ClusterResult {
  std::vector<int> trainingIndices,ahc,hard;
  std::vector<int> trainingRunIndices,frame_hard;
  Matrix features,centroids,scores;
  Vec capacityRms;
  std::vector<int> retainedClusters;
  bool usedKMeans = false;
  bool usedAhcFallback = false;
  int shortRunTrainingCount = 0;
  VbxResult vbx;
};
struct Turn { double begin,end; int speaker; };
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
  if(result.centroids.size()>static_cast<size_t>(maxSpeakers)&&!runRms.empty()&&!result.usedAhcFallback) {
    // Over capacity, first fold VBx identities that are acoustically the same person
    // (one speaker split across two clusters) so a duplicate cannot take a slot from
    // a quieter real speaker. Only near-identical centroids qualify; capacity alone
    // never merges people.
    constexpr double kDuplicateIdentityCosine=.6;
    auto rebuild=[&]{
      result.centroids.clear();
      for(size_t c=0;c<result.vbx.priors.size();++c)if(result.vbx.priors[c]>1e-7){
        Vec centroid(dim);double sum=0;
        for(size_t i=0;i<train.size();++i){double q=result.vbx.q[i][c];sum+=q;for(int j=0;j<dim;++j)centroid[j]+=q*train[i][j];}
        for(auto&v:centroid)v/=sum;result.centroids.push_back(std::move(centroid));
      }
    };
    auto cosine=[](const Vec& a,const Vec& b){double d=0,x=0,y=0;for(size_t j=0;j<a.size();++j){d+=a[j]*b[j];x+=a[j]*a[j];y+=b[j]*b[j];}return d/std::sqrt(x*y);};
    while(result.centroids.size()>static_cast<size_t>(maxSpeakers)){
      std::vector<int> columns;
      for(size_t c=0;c<result.vbx.priors.size();++c)if(result.vbx.priors[c]>1e-7)columns.push_back(c);
      // Compare identities by the vectors they actually own (argmax posterior), so soft
      // VBx responsibilities cannot make two different speakers look alike.
      Matrix owned(columns.size(),Vec(dim));std::vector<int> members(columns.size());
      for(size_t i=0;i<train.size();++i){
        size_t best=0;for(size_t c=1;c<columns.size();++c)if(result.vbx.q[i][columns[c]]>result.vbx.q[i][columns[best]])best=c;
        ++members[best];for(int j=0;j<dim;++j)owned[best][j]+=train[i][j];
      }
      int bestA=-1,bestB=-1;double best=kDuplicateIdentityCosine;
      for(size_t a=0;a<columns.size();++a)for(size_t b=a+1;b<columns.size();++b){
        if(!members[a]||!members[b])continue;
        const double value=cosine(owned[a],owned[b]);
        if(std::isfinite(value)&&value>=best){best=value;bestA=columns[a];bestB=columns[b];}
      }
      if(bestA<0)break;
      for(auto& row:result.vbx.q){row[bestA]+=row[bestB];row[bestB]=0;}
      result.vbx.priors[bestA]+=result.vbx.priors[bestB];result.vbx.priors[bestB]=0;
      rebuild();
    }
  }
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
