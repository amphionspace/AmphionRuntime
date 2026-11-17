#include "stream_denoisers.h"
#include "denoise_dsp.h"
#include <fstream>
#include <iostream>
#include <chrono>
#include <iterator>
#include <random>
#include <cstring>
using namespace amphion_denoise;
std::vector<uint8_t> Read(const std::string& path){std::ifstream f(path,std::ios::binary);if(!f)throw std::runtime_error("read "+path);return {std::istreambuf_iterator<char>(f),{}};}
int main(int argc,char**argv){try{
 if(argc==2&&std::string(argv[1])=="dsp"){
  for(int n:{512,960}){Fft f(n);std::vector<float>x(n);for(int i=0;i<n;++i)x[i]=.1f*std::sin(i*.135f)+.05f*std::cos(i*.912f);auto y=f.Inverse(f.Forward(x));float err=0;for(int i=0;i<n;++i)err=std::max(err,std::abs(x[i]-y[i]));if(err>1e-6)throw std::runtime_error("FFT roundtrip");std::cout<<"FFT "<<n<<" error="<<err<<"\n";}return 0;}
 if(argc!=7)throw std::runtime_error("model-dir model input-f32 output-f32 chunk mode");
 std::string dir=argv[1],mode=argv[6];auto raw=Read(argv[3]);std::vector<float>x(raw.size()/4);std::memcpy(x.data(),raw.data(),raw.size());std::vector<float>y;int chunk=std::stoi(argv[5]);
 std::unique_ptr<StreamDenoiser> model;if(mode=="model")model=CreateStreamDenoiser(argv[2],[&](const std::string& path){return Read(dir+"/"+path);});
 Resampler3 r(std::string(argv[2])=="up"?3:1,std::string(argv[2])=="up"?1:3);auto start=std::chrono::steady_clock::now();
 for(size_t pos=0;pos<x.size();pos+=chunk){std::vector<float>part(x.begin()+pos,x.begin()+std::min(x.size(),pos+chunk));auto o=mode=="model"?model->Process(part,false):r.Run(part);y.insert(y.end(),o.begin(),o.end());}
 auto tail=mode=="model"?model->Process({},true):r.Run({},true);y.insert(y.end(),tail.begin(),tail.end());for(float v:y)if(!std::isfinite(v))throw std::runtime_error("nonfinite output");std::ofstream f(argv[4],std::ios::binary);f.write(reinterpret_cast<const char*>(y.data()),y.size()*4);std::cout<<"input="<<x.size()<<" output="<<y.size()<<" seconds="<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<"\n";
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
