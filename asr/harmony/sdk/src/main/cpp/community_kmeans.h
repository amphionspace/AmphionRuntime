#pragma once
#include <algorithm>
#include <cmath>
#include <limits>
#include <random>
#include <vector>

namespace community {
// sklearn KMeans(init=k-means++, n_init=3, random_state=42, algorithm=lloyd).
// This is the official speaker-count cap branch, not an identity threshold.
inline std::vector<int> KMeans(const std::vector<std::vector<double>>& input, int k) {
  using Row = std::vector<float>;
  using Rows = std::vector<Row>;
  const int n = input.size(), dim = input[0].size();
  Rows x(n, Row(dim));
  Row mean(dim);
  for (int i=0; i<n; ++i) {
    double norm=0; for (double v: input[i]) norm+=v*v;
    norm=std::sqrt(norm);
    for (int d=0; d<dim; ++d) { x[i][d]=input[i][d]/norm; mean[d]+=x[i][d]; }
  }
  for (auto& v:mean) v/=n;
  float variance=0;
  for (int d=0; d<dim; ++d) {
    float sum=0;
    for (int i=0; i<n; ++i) { x[i][d]-=mean[d]; sum+=x[i][d]*x[i][d]; }
    variance+=sum/n;
  }
  const double tolerance=variance/dim*1e-4;
  auto distance = [&](const Row& a,const Row& b) {
    double sum=0; for (int d=0; d<dim; ++d) {double v=double(a[d])-b[d];sum+=v*v;}
    return static_cast<float>(sum);
  };
  std::mt19937 random(42);
  auto uniform = [&]() { uint32_t a=random()>>5,b=random()>>6;return (a*67108864.+b)/9007199254740992.; };
  auto assign = [&](const Rows& centers) {
    std::vector<int> labels(n);
    for(int i=0;i<n;++i){float best=std::numeric_limits<float>::infinity();
      for(int c=0;c<k;++c){float value=distance(x[i],centers[c]);if(value<best){best=value;labels[i]=c;}}}
    return labels;
  };
  std::vector<int> best;
  double bestInertia=std::numeric_limits<double>::infinity();
  for(int restart=0;restart<3;++restart){
    Rows centers;centers.push_back(x[std::min(n-1,static_cast<int>(uniform()*n))]);
    Row closest(n);for(int i=0;i<n;++i)closest[i]=distance(x[i],centers[0]);
    const int trials=2+static_cast<int>(std::log(k));
    for(int c=1;c<k;++c){
      float potential=0;for(float v:closest)potential+=v;
      float chosenPotential=std::numeric_limits<float>::infinity();Row chosenDistances;int chosen=0;
      std::vector<int> candidates;
      for(int trial=0;trial<trials;++trial){double target=uniform()*potential,sum=0;int i=0;
        while(i<n-1&&(sum+closest[i])<target)sum+=closest[i++];candidates.push_back(i);}
      for(int candidate:candidates){Row values(n);float sum=0;
        for(int i=0;i<n;++i){values[i]=std::min(closest[i],distance(x[i],x[candidate]));sum+=values[i];}
        if(sum<chosenPotential){chosenPotential=sum;chosenDistances=values;chosen=candidate;}}
      centers.push_back(x[chosen]);closest=std::move(chosenDistances);
    }
    std::vector<int> old(n,-1),labels;
    bool strict=false;
    for(int iteration=0;iteration<300;++iteration){
      labels=assign(centers);Rows next(k,Row(dim));std::vector<int> count(k);
      for(int i=0;i<n;++i){++count[labels[i]];for(int d=0;d<dim;++d)next[labels[i]][d]+=x[i][d];}
      std::vector<bool> moved(n,false);
      for(int c=0;c<k;++c)if(count[c]==0){
        int farthest=-1;float farthestDistance=0;
        for(int i=0;i<n;++i)if(!moved[i]){float v=distance(x[i],centers[labels[i]]);if(v>farthestDistance){farthest=i;farthestDistance=v;}}
        if(farthest<0)continue;
        moved[farthest]=true;int oldCluster=labels[farthest];--count[oldCluster];count[c]=1;
        for(int d=0;d<dim;++d){next[oldCluster][d]-=x[farthest][d];next[c][d]=x[farthest][d];}
      }
      int largest=std::max_element(count.begin(),count.end())-count.begin();
      for(int c=0;c<k;++c)if(count[c])for(auto&v:next[c])v/=count[c];
      for(int c=0;c<k;++c)if(!count[c])next[c]=next[largest];
      float shift=0;for(int c=0;c<k;++c)shift+=distance(centers[c],next[c]);
      centers=std::move(next);
      if(labels==old){strict=true;break;}
      if(shift<=tolerance)break;
      old=labels;
    }
    if(!strict)labels=assign(centers);
    double inertia=0;for(int i=0;i<n;++i)inertia+=distance(x[i],centers[labels[i]]);
    bool same=!best.empty();std::vector<int> mapping(k,-1);
    for(int i=0;i<n&&same;++i){int&label=mapping[labels[i]];if(label<0)label=best[i];else if(label!=best[i])same=false;}
    if(best.empty()||(inertia<bestInertia&&!same)){best=labels;bestInertia=inertia;}
  }
  return best;
}
}
