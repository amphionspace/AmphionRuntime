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
  Matrix features,centroids,scores;
  bool usedKMeans = false;
  VbxResult vbx;
};
struct Turn { double begin,end; int speaker; };
inline std::vector<Turn> Reconstruct(const std::vector<float>& segments,
                                    const std::vector<int>& hard,int windows) {
  constexpr int local=3,frames=589;
  constexpr double step=270./16000.,halfFrame=991./32000.;
  const int knownClusters=*std::max_element(hard.begin(),hard.end())+1;
  const bool unknown=knownClusters<=0;
  // Without enrollment, retain anonymous speech and simultaneous-voice counts.
  const int clusters=unknown?local:knownClusters;
  const int total=static_cast<int>(std::nearbyint((10.+windows-1)/step))+1;
  Matrix activation(total,Vec(clusters));Vec counts(total),weights(total);
  for(int w=0;w<windows;++w){
    int start=std::nearbyint(w/step);
    for(int f=0;f<frames;++f){
      Vec active(clusters);int n=0;
      for(int k=0;k<local;++k){float value=segments[(w*frames+f)*local+k];n+=value;int label=hard[w*local+k];if(label>=0)active[label]=std::max(active[label],static_cast<double>(value));}
      int t=start+f;counts[t]+=n;weights[t]+=1;
      for(int k=0;k<clusters;++k)activation[t][k]+=active[k];
    }
  }
  std::vector<Turn> turns;std::vector<int> start(clusters,-1);
  for(int t=0;t<total;++t){
    int count=weights[t]>0?static_cast<int>(std::nearbyint(counts[t]/weights[t])):0;
    count=std::min(count,clusters);std::vector<int> order(clusters);std::iota(order.begin(),order.end(),0);
    std::stable_sort(order.begin(),order.end(),[&](int a,int b){return activation[t][a]>activation[t][b];});
    std::vector<bool> on(clusters,false);for(int j=0;j<count;++j)on[order[j]]=true;
    for(int k=0;k<clusters;++k){
      if(on[k]&&start[k]<0)start[k]=t;
      if(!on[k]&&start[k]>=0){turns.push_back({start[k]*step+halfFrame,t*step+halfFrame,unknown?-1:k});start[k]=-1;}
    }
  }
  for(int k=0;k<clusters;++k)if(start[k]>=0)turns.push_back({start[k]*step+halfFrame,(total-1)*step+halfFrame,unknown?-1:k});
  return turns;
}
inline ClusterResult Cluster(const std::vector<float>& segments,const std::vector<float>& embeddings,int windows,const Plda& plda,int maxSpeakers=4) {
  constexpr int frames=589,local=3,dim=256;
  if(segments.size()!=windows*frames*local||embeddings.size()!=windows*local*dim)throw std::runtime_error("invalid cluster shapes");
  ClusterResult result;Matrix train;std::vector<int> activity(windows*local);
  for(int w=0;w<windows;++w){int clean[local]={};for(int f=0;f<frames;++f){int count=0;for(int k=0;k<local;++k)count+=segments[(w*frames+f)*local+k];for(int k=0;k<local;++k){int on=segments[(w*frames+f)*local+k];activity[w*local+k]+=on;if(count==1)clean[k]+=on;}}
    for(int k=0;k<local;++k){int i=w*local+k;Vec emb(embeddings.begin()+i*dim,embeddings.begin()+(i+1)*dim);if(clean[k]>=.2*frames&&std::all_of(emb.begin(),emb.end(),[](double x){return std::isfinite(x);})){result.trainingIndices.push_back(i);train.push_back(std::move(emb));}}
  }
  if(train.empty()){result.hard=std::vector<int>(windows*local,-2);return result;}
  if(train.size()==1){result.centroids=Matrix(1,train[0]);result.hard=std::vector<int>(windows*local,0);for(int i=0;i<windows*local;++i)if(!activity[i])result.hard[i]=-2;return result;}
  result.ahc=Ahc(train);result.features=plda.Apply(train);result.vbx=Vbx(result.features,plda.phi,result.ahc);
  for(size_t c=0;c<result.vbx.priors.size();++c)if(result.vbx.priors[c]>1e-7){Vec centroid(dim);double sum=0;for(size_t i=0;i<train.size();++i){double q=result.vbx.q[i][c];sum+=q;for(int j=0;j<dim;++j)centroid[j]+=q*train[i][j];}for(auto&v:centroid)v/=sum;result.centroids.push_back(std::move(centroid));}
  if(maxSpeakers<1||maxSpeakers>4)throw std::runtime_error("invalid speaker cap");
  if(result.centroids.size()>static_cast<size_t>(maxSpeakers)) {
    auto labels=KMeans(train,maxSpeakers);
    result.centroids=Matrix(maxSpeakers,Vec(dim));
    for(int c=0;c<maxSpeakers;++c){std::vector<float> mean(dim);int count=0;
      for(size_t i=0;i<train.size();++i)if(labels[i]==c){++count;for(int j=0;j<dim;++j)mean[j]+=static_cast<float>(train[i][j]);}
      for(int j=0;j<dim;++j)result.centroids[c][j]=mean[j]/count;
    }
    result.usedKMeans=true;
  }
  const int k=result.centroids.size();
  if(k<1)throw std::runtime_error("Community clustering has no centroid");
  Matrix scores(windows*local,Vec(k));double minimum=std::numeric_limits<double>::infinity();bool anyNan=false;
  for(int i=0;i<windows*local;++i)for(int c=0;c<k;++c){double dot=0,a=0,b=0;for(int j=0;j<dim;++j){double v=embeddings[i*dim+j],u=result.centroids[c][j];dot+=v*u;a+=v*v;b+=u*u;}double score=1+dot/std::sqrt(a*b);scores[i][c]=score;if(std::isfinite(score))minimum=std::min(minimum,score);else anyNan=true;}
  result.scores=scores;
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
  double inactive=anyNan?minimum:minimum-1.;
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
