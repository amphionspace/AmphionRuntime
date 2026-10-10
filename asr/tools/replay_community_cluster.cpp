// Host-only replay of exact diagnostic tensors through the production cluster.
#include "community_cluster.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

template<class T> std::vector<T> Read(std::istream& input, size_t size) {
  std::vector<T> values(size);
  input.read(reinterpret_cast<char*>(values.data()), size * sizeof(T));
  if (!input) throw std::runtime_error("truncated replay input");
  return values;
}
template<class T> void Values(const char* name, const std::vector<T>& values) {
  std::cout << ",\"" << name << "\":[";
  for (size_t i=0; i<values.size(); ++i) {
    if(i) std::cout << ',';
    if (std::isfinite(static_cast<double>(values[i]))) std::cout << values[i];
    else std::cout << "null";
  }
  std::cout << ']';
}
int main(int argc, char** argv) {
  try {
    if (argc != 3) throw std::runtime_error("usage: replay PLDA snapshot.bin");
    std::ifstream model(argv[1],std::ios::binary), input(argv[2],std::ios::binary);
    if (Read<uint32_t>(model,4) != std::vector<uint32_t>({0x434d504c,1,256,128}))
      throw std::runtime_error("invalid PLDA header");
    community::Plda p;
    p.mean1=Read<double>(model,256);p.mean2=Read<double>(model,128);
    for(int i=0;i<256;++i)p.lda.push_back(Read<double>(model,128));
    p.mu=Read<double>(model,128);
    for(int i=0;i<128;++i)p.transform.push_back(Read<double>(model,128));
    p.phi=Read<double>(model,128);
    auto header=Read<uint32_t>(input,4);
    if((header[0]!=0x43525031&&header[0]!=0x43525032) || header[1]<1 || header[1]>10000 || header[2]>100000 || header[3]<1 || header[3]>4)
      throw std::runtime_error("invalid replay header");
    int n=header[1], r=header[2], cap=header[3];
    auto begin=Read<double>(input,1)[0];auto starts=Read<double>(input,n);
    auto seg=Read<float>(input,n*589*3), emb=Read<float>(input,n*768);
    auto runs=Read<float>(input,r*256);auto ranges=Read<int32_t>(input,r*4);
    auto levels=header[0]==0x43525032?Read<float>(input,r):std::vector<float>{};
    auto c=community::Cluster(seg,emb,n,p,cap,runs,ranges,levels,community::CommunityHopSamples(starts));
    auto turns=community::Reconstruct(seg,c.hard,starts,begin,cap,c.frame_hard);
    std::cout << std::setprecision(17) << "{\"speakerCount\":" << c.centroids.size();
    Values("trainingIndices",c.trainingIndices);Values("trainingRunIndices",c.trainingRunIndices);
    Values("ahc",c.ahc);Values("priors",c.vbx.priors);Values("objectives",c.vbx.objectives);
    Values("hard",c.hard);Values("frameHard",c.frame_hard);
    Values("capacityRms",c.capacityRms);Values("retainedClusters",c.retainedClusters);
    std::cout<<",\"usedAhcFallback\":"<<(c.usedAhcFallback?"true":"false")
             <<",\"usedKMeans\":"<<(c.usedKMeans?"true":"false")
             <<",\"shortRunTrainingCount\":"<<c.shortRunTrainingCount<<",\"turns\":[";
    for(size_t i=0;i<turns.size();++i){if(i)std::cout<<',';auto& t=turns[i];std::cout<<'['<<t.begin*1000<<','<<t.end*1000<<','<<t.speaker<<']';}
    std::cout<<"]}\n";
  } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
