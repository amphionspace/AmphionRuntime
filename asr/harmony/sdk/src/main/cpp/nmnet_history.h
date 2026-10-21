#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <map>
#include <numeric>
#include <stdexcept>
#include <vector>

// Session-owned state. Call Update in chunk order, never in worker completion order.
namespace nmnet {
using Vector = std::vector<double>;
struct Entry { Vector total; uint64_t count; int speaker; };
struct HistoryResult {
  std::map<int, int> assignments;
  uint64_t chunks = 0, represented = 0;
  size_t anchors = 0, recent = 0;
  bool compressed = false;
};
inline double Norm(const Vector& v) {
  double sum = 0;
  for (double x : v) sum += x*x;
  return std::sqrt(sum);
}
inline Vector Unit(Vector v) {
  const double norm = Norm(v);
  if (v.empty() || !std::isfinite(norm) || norm <= 0)
    throw std::invalid_argument("invalid NMNet embedding");
  for (double& x : v) x /= norm;
  return v;
}
inline void Add(Vector& a, const Vector& b) {
  if (a.size() != b.size()) throw std::invalid_argument("embedding dimension mismatch");
  for (size_t i=0;i<a.size();++i) a[i]+=b[i];
}
inline double CosineDistance(const Vector& a, const Vector& b) {
  double dot=0;
  for(size_t i=0;i<a.size();++i) dot+=a[i]*b[i];
  return 1-dot/(Norm(a)*Norm(b));
}

// Centroid linkage counts representative leaves, NOT their historical support.
// fcluster(distance) compares the maximum height in each subtree, including
// inversions. A threshold-only greedy early stop is not equivalent.
inline std::vector<int> CentroidLabels(const std::vector<Vector>& vectors, double threshold) {
  const size_t n=vectors.size();
  if (!n) return {};
  struct Node { Vector center; size_t count; int left=-1,right=-1; double height=0; bool live=true; };
  std::vector<Node> nodes;
  nodes.reserve(2*n-1);
  for (const auto& v:vectors) nodes.push_back({v,1});
  const size_t width=2*n-1;
  std::vector<double> distances(width*width,0);
  const auto distance=[&](size_t a,size_t b)->double& {return distances[a*width+b];};
  for(size_t i=0;i<n;++i)for(size_t j=i+1;j<n;++j) {
    double d=0;for(size_t k=0;k<vectors[i].size();++k) {
      const double delta=vectors[i][k]-vectors[j][k];d+=delta*delta;
    }
    distance(i,j)=distance(j,i)=d;
  }
  for(size_t step=1;step<n;++step) {
    double best=std::numeric_limits<double>::infinity(); int a=-1,b=-1;
    for(size_t i=0;i<nodes.size();++i) if(nodes[i].live)
      for(size_t j=i+1;j<nodes.size();++j) if(nodes[j].live) {
        const double d=distance(i,j);
        if(d<best) {best=d;a=static_cast<int>(i);b=static_cast<int>(j);}
      }
    const size_t count=nodes[a].count+nodes[b].count;
    Vector center(nodes[a].center.size());
    for(size_t k=0;k<center.size();++k)
      center[k]=(nodes[a].center[k]*nodes[a].count+nodes[b].center[k]*nodes[b].count)/count;
    const double height=std::max({std::sqrt(best),nodes[a].height,nodes[b].height});
    nodes[a].live=nodes[b].live=false;
    const double alpha=static_cast<double>(nodes[a].count)/count;
    const double beta=static_cast<double>(nodes[b].count)/count;
    for(size_t i=0;i<nodes.size();++i)if(nodes[i].live) {
      const double d=std::max(0.,alpha*distance(a,i)+beta*distance(b,i)-alpha*beta*best);
      distance(i,nodes.size())=distance(nodes.size(),i)=d;
    }
    nodes.push_back({std::move(center),count,a,b,height,true});
  }
  std::vector<int> labels(n,-1);int next=0;
  const auto paint=[&](auto&& self,int id,int label)->void {
    if(nodes[id].left<0) labels[id]=label;
    else {self(self,nodes[id].left,label);self(self,nodes[id].right,label);}
  };
  const auto cut=[&](auto&& self,int id)->void {
    if(nodes[id].left<0 || nodes[id].height<=threshold) paint(paint,id,next++);
    else {self(self,nodes[id].left);self(self,nodes[id].right);}
  };
  cut(cut,static_cast<int>(nodes.size()-1));
  return labels;
}

class History {
 public:
  explicit History(double threshold=.67, uint64_t compressEvery=50, uint64_t minSupport=4)
      :threshold_(threshold),compressEvery_(compressEvery),minSupport_(minSupport) {
    if(!std::isfinite(threshold)||threshold<=0||threshold>2||!compressEvery||!minSupport)
      throw std::invalid_argument("invalid NMNet history configuration");
  }
  HistoryResult Update(uint64_t chunkIndex,const std::map<int,Vector>& embeddings) {
    if(chunkIndex!=chunks_) throw std::invalid_argument("NMNet chunks must be accepted exactly once in order");
    // Validate before mutating session state.
    std::vector<Entry> current;
    size_t dimension=dimension_;
    for(const auto& pair:embeddings) {
      if(pair.first<0||pair.first>=8) throw std::invalid_argument("invalid NMNet slot");
      auto v=Unit(pair.second);
      if(!dimension) dimension=v.size();
      if(v.size()!=dimension) throw std::invalid_argument("embedding dimension mismatch");
      current.push_back({std::move(v),1,-1});
    }
    std::vector<Entry> entries=anchors_;
    entries.insert(entries.end(),recent_.begin(),recent_.end());
    const size_t old=entries.size();
    entries.insert(entries.end(),current.begin(),current.end());
    HistoryResult result;
    int nextSpeaker=nextSpeaker_;
    if(!current.empty()) {
      std::vector<Vector> x;for(const auto& e:entries)x.push_back(Unit(e.total));
      auto labels=CentroidLabels(x,threshold_);
      std::map<int,uint64_t> support;std::map<int,Vector> centers;
      for(size_t i=0;i<entries.size();++i) {
        support[labels[i]]+=entries[i].count;
        if(!centers.count(labels[i]))centers[labels[i]]=entries[i].total;
        else Add(centers[labels[i]],entries[i].total);
      }
      std::vector<int> large;uint64_t largest=0;
      for(const auto& p:support) {largest=std::max(largest,p.second);if(p.second>=minSupport_)large.push_back(p.first);}
      if(large.empty())for(const auto& p:support)if(p.second==largest)large.push_back(p.first);
      std::map<int,int> remap;
      for(const auto& p:support) {
        int choice=p.first;
        if(std::find(large.begin(),large.end(),choice)==large.end()) {
          double best=std::numeric_limits<double>::infinity();
          for(int l:large) {double d=CosineDistance(centers[p.first],centers[l]);if(d<best){best=d;choice=l;}}
        }
        remap[p.first]=choice;
      }
      for(int& l:labels)l=remap[l];
      std::map<int,int> chosen;size_t j=0;
      for(const auto& p:embeddings) {
        const int group=labels[old+j];
        if(!chosen.count(group)) {
          std::map<int,uint64_t> votes;
          for(size_t i=0;i<old;++i)if(labels[i]==group)votes[entries[i].speaker]+=entries[i].count;
          int speaker=-1;uint64_t best=0;
          for(const auto& v:votes)if(v.second>best){speaker=v.first;best=v.second;}
          if(speaker<0)speaker=nextSpeaker++;
          chosen[group]=speaker;
        }
        current[j].speaker=chosen[group];result.assignments[p.first]=chosen[group];++j;
      }
    }
    recent_.insert(recent_.end(),current.begin(),current.end());
    dimension_=dimension;nextSpeaker_=nextSpeaker;++chunks_;
    result.compressed=chunks_%compressEvery_==0;
    if(result.compressed) {
      std::map<int,Entry> merged;
      auto merge=[&](const Entry& e) {
        auto found=merged.find(e.speaker);
        if(found==merged.end())merged.emplace(e.speaker,e);
        else {Add(found->second.total,e.total);found->second.count+=e.count;}
      };
      for(const auto& e:anchors_)merge(e);
      for(const auto& e:recent_)merge(e);
      anchors_.clear();for(const auto& p:merged)anchors_.push_back(p.second);
      recent_.clear();
    }
    result.chunks=chunks_;result.anchors=anchors_.size();result.recent=recent_.size();
    for(const auto& e:anchors_)result.represented+=e.count;
    for(const auto& e:recent_)result.represented+=e.count;
    return result;
  }
 private:
  double threshold_;uint64_t compressEvery_,minSupport_,chunks_=0;
  size_t dimension_=0;int nextSpeaker_=0;
  std::vector<Entry> anchors_,recent_;
};
}  // namespace nmnet
