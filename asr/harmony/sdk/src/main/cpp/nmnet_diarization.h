#pragma once
#include "nmnet_history.h"
#include "nmnet_window.h"
#include <array>
#include <memory>

namespace nmnet {
// Relative to the platform rawfile/assets root. Order matches manifest.json.
inline constexpr const char* kModelResourceDirectory = "amphion-dingqiao/nmnet-student/v1";
inline constexpr std::array<const char*, 5> kModelFileNames = {
  "nmnet-student-mel.onnx", "nmnet-student-nest.onnx",
  "nmnet-student-segmentation.onnx", "nmnet-ecapa-mel.onnx", "nmnet-ecapa.onnx"
};
struct WindowEvidence {
  int validFrames=0;
  std::vector<float> probabilities;
  std::map<int,Vector> embeddings;
  double segmentationMs=0,embeddingMs=0,embeddingFeaturesMs=0,embeddingEncoderMs=0;
};
// Model order: student mel, NeSt, Conformer U-Net, ECAPA mel, ECAPA encoder.
// Own one instance per inference lane; Process must not run concurrently.
class Inference {
 public:
  explicit Inference(const std::array<std::vector<uint8_t>,5>& models,int threads=1);
  ~Inference();
  Inference(const Inference&)=delete;
  Inference& operator=(const Inference&)=delete;
  WindowEvidence Process(const std::vector<float>& pcm,int validSamples);
 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
} // namespace nmnet
