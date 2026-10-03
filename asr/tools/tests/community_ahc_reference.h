#pragma once
#include "community_cluster.h"

// Frozen before pair memoization; independent of the production Ahc function.
// Source header SHA256: d46da6f5e2808efd5d8a1518844f605a1e1ab85661fe4f96366e83101156db27
// Function block SHA256: e808630974af012aa3e67b7bda50466b8a79874b6c0767322fc84b1a99f102ad
namespace community_ahc_reference {
using community::Vec;
using community::Matrix;
using community::CancellationToken;
using community::CheckCancellation;
// Centroid linkage followed by distance fcluster; the subtree maximum handles
// inversions in centroid linkage exactly as scipy's distance criterion does.
inline std::vector<int> Ahc(const Matrix& x, const CancellationToken* cancellation);
inline std::vector<int> Ahc(const Matrix& x) { return Ahc(x, nullptr); }
inline std::vector<int> Ahc(const Matrix& x, const CancellationToken* cancellation) {
  int n=x.size();Matrix centers(2*n-1);std::vector<int> count(2*n-1,1),left(2*n-1,-1),right(2*n-1,-1);
  std::vector<bool> alive(2*n-1,false);Vec height(2*n-1);
  for(int i=0;i<n;++i){
    CheckCancellation(cancellation);
    centers[i]=x[i];double norm=0;for(auto v:x[i])norm+=v*v;norm=std::sqrt(norm);for(auto&v:centers[i])v/=norm;alive[i]=true;}
  auto distance=[&](int a,int b){
    CheckCancellation(cancellation);
    double d=0;for(size_t j=0;j<x[0].size();++j){double v=centers[a][j]-centers[b][j];d+=v*v;}return std::sqrt(d);};
  using Pair=std::tuple<double,int,int>;
  // Each row keeps a lower bound for its nearest active higher-ID neighbor.
  // Removing that neighbor can only increase the bound. A newly merged center
  // is checked immediately, including centroid-linkage distance inversions.
  const double infinity=std::numeric_limits<double>::infinity();
  std::vector<Pair> nearest(2*n-1,Pair{infinity,0,-1});
  auto refresh=[&](int a,int limit){
    CheckCancellation(cancellation);
    Pair best{infinity,a,-1};
    for(int b=a+1;b<limit;++b)if(alive[b])best=std::min(best,Pair{distance(a,b),a,b});
    nearest[a]=best;
  };
  for(int a=0;a<n;++a){
    CheckCancellation(cancellation);
    refresh(a,n);
  }
  for(int node=n;node<2*n-1;++node){
    CheckCancellation(cancellation);
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
  std::function<void(int,int)> assign=[&](int node,int label){
    CheckCancellation(cancellation);
    if(node<n){labels[node]=label;return;}
    assign(left[node],label);
    assign(right[node],label);
  };
  std::function<void(int)> cut=[&](int node){
    CheckCancellation(cancellation);
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
}  // namespace community_ahc_reference
