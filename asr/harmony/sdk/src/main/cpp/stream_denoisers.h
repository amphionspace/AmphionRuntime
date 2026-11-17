#pragma once
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>
namespace amphion_denoise {
using AssetReader = std::function<std::vector<uint8_t>(const std::string &)>;
class StreamDenoiser {
public:
  virtual ~StreamDenoiser() = default;
  virtual std::vector<float> Process(const std::vector<float> &input,
                                     bool flush) = 0;
};
std::unique_ptr<StreamDenoiser> CreateStreamDenoiser(const std::string &model,
                                                     const AssetReader &read);
} // namespace amphion_denoise
