#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <limits>
#include <stdexcept>
#include <vector>

namespace community {
// Kaldi fbank defaults used by the locked Community-1 WeSpeaker model.
// Window/mel constants are exported from the same torchaudio implementation.
inline std::vector<float> Fbank(const std::vector<float>& pcm,
                              const std::vector<float>& constants) {
  if (pcm.size()!=160000 || constants.size()!=400+80*257)
    throw std::runtime_error("invalid Community-1 feature input");
  constexpr int frames=998, fft_size=512;
  std::vector<float> features(frames*80);
  std::array<std::complex<double>,fft_size> fft;
  std::array<float,400> samples;
  // Fixed mel filters have zero weight outside their support. Keep the
  // contributing-bin order while avoiding redundant spectrum products.
  std::array<int,80> firstBin, endBin;
  for (int m=0;m<80;++m) {
    int first=0,end=257;
    while(first<end && constants[400+m*257+first]==0.f)++first;
    while(end>first && constants[400+m*257+end-1]==0.f)--end;
    firstBin[m]=first;endBin[m]=end;
  }
  for (int f=0;f<frames;++f) {
    // Accumulate in double before rounding to float to avoid platform-specific
    // reduction order; parity is checked against official fbank and embeddings.
    double sum=0;
    for (int j=0;j<400;++j) {samples[j]=pcm[f*160+j]*32768.f;sum+=samples[j];}
    float mean=static_cast<float>(sum/400);
    for (auto& v:samples) v-=mean;
    for (int j=0;j<400;++j) fft[j]=(samples[j]-.97f*samples[j==0?0:j-1])*constants[j];
    for (int j=400;j<512;++j) fft[j]=0;
    for (int i=1,j=0;i<512;++i) {
      int bit=256;for(;j&bit;bit>>=1)j^=bit;j^=bit;
      if(i<j)std::swap(fft[i],fft[j]);
    }
    for(int n=2;n<=512;n*=2) {
      std::complex<double> wn=std::polar(1.,-2.*std::acos(-1.)/n);
      for(int i=0;i<512;i+=n) {
        std::complex<double>w=1.;
        for(int j=0;j<n/2;++j) {
          auto u=fft[i+j],v=fft[i+j+n/2]*w;
          fft[i+j]=u+v;fft[i+j+n/2]=u-v;w*=wn;
        }
      }
    }
    for(int m=0;m<80;++m) {
      double energy=0;
      for(int j=firstBin[m];j<endBin[m];++j) energy+=std::norm(fft[j])*constants[400+m*257+j];
      features[f*80+m]=std::log(std::max(static_cast<float>(energy),std::numeric_limits<float>::epsilon()));
    }
  }
  for(int m=0;m<80;++m) {
    double mean=0;for(int f=0;f<frames;++f)mean+=features[f*80+m];
    const float value=static_cast<float>(mean/frames);
    for(int f=0;f<frames;++f)features[f*80+m]-=value;
  }
  return features;
}
}
