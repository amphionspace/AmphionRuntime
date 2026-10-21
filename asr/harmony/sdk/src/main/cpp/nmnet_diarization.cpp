#include "nmnet_diarization.h"
#include "onnxruntime_cxx_api.h"
#include <chrono>

namespace nmnet {
namespace {
using Clock=std::chrono::steady_clock;
double Elapsed(Clock::time_point begin) {
  return std::chrono::duration<double,std::milli>(Clock::now()-begin).count();
}
void Shape(const Ort::Value& value,const std::vector<int64_t>& expected,
           ONNXTensorElementDataType type=ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
  const auto info=value.GetTensorTypeAndShapeInfo();
  if(info.GetShape()!=expected || info.GetElementType()!=type)
    throw std::runtime_error("NMNet model output shape or element type mismatch");
}
void Finite(const float* data,size_t size) {
  for(size_t i=0;i<size;++i)if(!std::isfinite(data[i]))
    throw std::runtime_error("NMNet model returned non-finite output");
}
}
struct Inference::Impl {
  Ort::Env env{ORT_LOGGING_LEVEL_WARNING,"nmnet"};
  Ort::MemoryInfo memory=Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,OrtMemTypeDefault);
  std::vector<Ort::Session> sessions;
  explicit Impl(const std::array<std::vector<uint8_t>,5>& models,int threads) {
    if(threads<1||threads>4)throw std::invalid_argument("invalid NMNet worker thread count");
    Ort::SessionOptions options;
    options.SetIntraOpNumThreads(threads);options.SetInterOpNumThreads(1);
    options.AddConfigEntry("session.intra_op.allow_spinning","0");
    options.AddConfigEntry("session.inter_op.allow_spinning","0");
    for(const auto& model:models) {
      if(model.empty())throw std::invalid_argument("missing NMNet ONNX model");
      sessions.emplace_back(env,model.data(),model.size(),options);
    }
  }
};
Inference::Inference(const std::array<std::vector<uint8_t>,5>& models,int threads)
    :impl_(std::make_unique<Impl>(models,threads)) {}
Inference::~Inference()=default;

WindowEvidence Inference::Process(const std::vector<float>& pcm,int validSamples) {
  auto sanitized=ValidPcm(pcm,validSamples);
  WindowEvidence result;
  // The pinned frontend returns floor(samples / 160) mel frames. Do not run
  // all-masked attention for the zero-frame case; this is Python's masked output.
  const int64_t melFrames=validSamples/160;
  result.validFrames=static_cast<int>((melFrames+7)/8);
  if(!result.validFrames)return result;
  auto& p=*impl_;auto begin=Clock::now();
  int64_t valid=validSamples;
  std::array<int64_t,2> pcmShape{1,kWindowSamples};std::array<int64_t,1> one{1};
  std::vector<Ort::Value> input;
  input.push_back(Ort::Value::CreateTensor<float>(p.memory,sanitized.data(),sanitized.size(),pcmShape.data(),2));
  input.push_back(Ort::Value::CreateTensor<int64_t>(p.memory,&valid,1,one.data(),1));
  const char* melInputs[]={"pcm","valid_samples"};const char* melOutputs[]={"mel","lengths"};
  auto mel=p.sessions[0].Run(Ort::RunOptions{nullptr},melInputs,input.data(),2,melOutputs,2);
  Shape(mel[0],{1,128,2016});Shape(mel[1],{1},ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64);
  if(mel[1].GetTensorData<int64_t>()[0]!=melFrames)throw std::runtime_error("NMNet mel length mismatch");
  const char* nestInputs[]={"mel","lengths"};const char* nestOutputs[]={"features","valid_frames"};
  auto nest=p.sessions[1].Run(Ort::RunOptions{nullptr},nestInputs,mel.data(),2,nestOutputs,2);
  Shape(nest[0],{1,252,192});Shape(nest[1],{1},ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64);
  if(nest[1].GetTensorData<int64_t>()[0]!=result.validFrames)throw std::runtime_error("NMNet valid frame mismatch");
  const size_t elements=result.validFrames*192;
  const float* features=nest[0].GetTensorData<float>();Finite(features,elements);
  std::vector<float> prefix(features,features+elements);
  std::array<int64_t,3> featureShape{1,result.validFrames,192};
  auto prefixTensor=Ort::Value::CreateTensor<float>(p.memory,prefix.data(),prefix.size(),featureShape.data(),3);
  const char* segInputs[]={"features"};const char* segOutputs[]={"probabilities"};
  auto segmentation=p.sessions[2].Run(Ort::RunOptions{nullptr},segInputs,&prefixTensor,1,segOutputs,1);
  Shape(segmentation[0],{1,result.validFrames,kSlots});
  const float* probabilities=segmentation[0].GetTensorData<float>();
  Finite(probabilities,result.validFrames*kSlots);
  result.probabilities.assign(probabilities,probabilities+result.validFrames*kSlots);
  for(float& value:result.probabilities)value=CanonicalActivityProbability(value);
  result.segmentationMs=Elapsed(begin);begin=Clock::now();
  std::vector<int> slots;std::vector<std::vector<float>> selected;size_t maxSamples=0;
  for(int slot=0;slot<kSlots;++slot) {
    auto audio=SelectSpeakerPcm(sanitized,validSamples,result.probabilities,slot);
    if(audio.empty())continue;
    maxSamples=std::max(maxSamples,audio.size());slots.push_back(slot);selected.push_back(std::move(audio));
  }
  if(!slots.empty()) {
    const int64_t batch=static_cast<int64_t>(slots.size());
    std::vector<float> audio(batch*maxSamples,0),ratios(batch);
    for(size_t i=0;i<slots.size();++i) {
      std::copy(selected[i].begin(),selected[i].end(),audio.begin()+i*maxSamples);
      ratios[i]=static_cast<float>(selected[i].size())/maxSamples;
    }
    std::array<int64_t,2> audioShape{batch,static_cast<int64_t>(maxSamples)};
    std::array<int64_t,1> ratiosShape{batch};std::vector<Ort::Value> ecapaInputs;
    ecapaInputs.push_back(Ort::Value::CreateTensor<float>(p.memory,audio.data(),audio.size(),audioShape.data(),2));
    ecapaInputs.push_back(Ort::Value::CreateTensor<float>(p.memory,ratios.data(),ratios.size(),ratiosShape.data(),1));
    const char* featureInputs[]={"pcm","lengths"};const char* featureOutputs[]={"features"};
    auto featureBegin=Clock::now();
    auto featuresOut=p.sessions[3].Run(Ort::RunOptions{nullptr},featureInputs,ecapaInputs.data(),2,featureOutputs,1);
    result.embeddingFeaturesMs=Elapsed(featureBegin);
    Shape(featuresOut[0],{batch,static_cast<int64_t>(maxSamples/160+1),80});
    // Keep the original batched log-mel (including its normalization and
    // boundary samples). Only prune encoder context beyond the pinned graph's
    // receptive field: radius 2 + 7*(2+3+4) = 65 frames. SE and attentive pooling
    // reductions are masked to the same valid integer prefix at every block.
    const int64_t frames=maxSamples/160+1;
    const float* allFeatures=featuresOut[0].GetTensorData<float>();
    auto encoderBegin=Clock::now();
    for(size_t i=0;i<slots.size();++i) {
      const int64_t validFrames=static_cast<int64_t>(std::ceil(ratios[i]*static_cast<float>(frames)));
      const int64_t prefixFrames=std::min(frames,validFrames+65);
      std::vector<float> prefix(allFeatures+i*frames*80,allFeatures+i*frames*80+prefixFrames*80);
      // arange < ratio*T selects ceil(ratio*T) frames. Use an interior point
      // rather than an integer edge that could round upward on ARM.
      float prefixRatio=static_cast<float>((validFrames-.5)/prefixFrames);
      std::array<int64_t,3> prefixShape{1,prefixFrames,80};
      std::array<int64_t,1> singleton{1};
      std::vector<Ort::Value> encoderInputs;
      encoderInputs.push_back(Ort::Value::CreateTensor<float>(p.memory,prefix.data(),prefix.size(),prefixShape.data(),3));
      encoderInputs.push_back(Ort::Value::CreateTensor<float>(p.memory,&prefixRatio,1,singleton.data(),1));
      const char* embeddingInputs[]={"features","lengths"};const char* embeddingOutputs[]={"embeddings"};
      auto embeddings=p.sessions[4].Run(Ort::RunOptions{nullptr},embeddingInputs,encoderInputs.data(),2,embeddingOutputs,1);
      Shape(embeddings[0],{1,192});
      const float* values=embeddings[0].GetTensorData<float>();Finite(values,192);
      result.embeddings.emplace(slots[i],Unit(Vector(values,values+192)));
    }
    result.embeddingEncoderMs=Elapsed(encoderBegin);
  }
  result.embeddingMs=Elapsed(begin);
  return result;
}
} // namespace nmnet
