// DF3 DSP equations adapted from DeepFilterNet v0.5.6 (MIT); see df3.LICENSE.
#include "stream_denoisers.h"
#include "denoise_dsp.h"
#include "onnxruntime_cxx_api.h"
#include <map>
#include <numeric>
namespace amphion_denoise {
namespace {
using Complex = std::complex<float>;
class Model {
public:
  Model(const AssetReader &read, const std::string &path, int signals,
        int results)
      : signals_(signals), results_(results),
        env_(ORT_LOGGING_LEVEL_WARNING, "amphion-denoise") {
    auto bytes = read(path);
    if (bytes.empty())
      throw std::runtime_error("empty denoiser asset: " + path);
    Ort::SessionOptions o;
    o.SetIntraOpNumThreads(1);
    o.SetInterOpNumThreads(1);
    o.SetExecutionMode(ORT_SEQUENTIAL);
    o.DisableCpuMemArena();
    o.DisableMemPattern();
    session_ = Ort::Session(env_, bytes.data(), bytes.size(), o);
    Ort::AllocatorWithDefaultOptions a;
    for (size_t i = 0; i < session_.GetInputCount(); ++i) {
      names_.push_back(session_.GetInputNameAllocated(i, a).get());
      auto shape =
          session_.GetInputTypeInfo(i).GetTensorTypeAndShapeInfo().GetShape();
      size_t count = 1;
      for (auto d : shape) {
        if (d <= 0)
          throw std::runtime_error("denoiser requires fixed input dimensions");
        count *= d;
      }
      shapes_.push_back(shape);
      counts_.push_back(count);
      if (i >= static_cast<size_t>(signals))
        states_.emplace_back(count, 0.f);
    }
    for (size_t i = 0; i < session_.GetOutputCount(); ++i)
      outputs_.push_back(session_.GetOutputNameAllocated(i, a).get());
    if (outputs_.size() != static_cast<size_t>(results) + states_.size())
      throw std::runtime_error("denoiser state output mismatch");
    for (const auto &n : names_)
      name_ptrs_.push_back(n.c_str());
    for (const auto &n : outputs_)
      out_ptrs_.push_back(n.c_str());
  }
  std::vector<std::vector<float>>
  Run(const std::vector<std::vector<float>> &signals) {
    if (signals.size() != static_cast<size_t>(signals_))
      throw std::runtime_error("denoiser input count");
    auto mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    std::vector<Ort::Value> inputs;
    for (size_t i = 0; i < names_.size(); ++i) {
      const auto &data = i < static_cast<size_t>(signals_)
                             ? signals[i]
                             : states_[i - signals_];
      if (data.size() != counts_[i])
        throw std::runtime_error("denoiser tensor size: " + names_[i]);
      inputs.push_back(Ort::Value::CreateTensor<float>(
          mem, const_cast<float *>(data.data()), data.size(), shapes_[i].data(),
          shapes_[i].size()));
    }
    auto out =
        session_.Run(Ort::RunOptions{nullptr}, name_ptrs_.data(), inputs.data(),
                     inputs.size(), out_ptrs_.data(), out_ptrs_.size());
    std::vector<std::vector<float>> result;
    for (size_t i = 0; i < out.size(); ++i) {
      auto count = out[i].GetTensorTypeAndShapeInfo().GetElementCount();
      const float *data = out[i].GetTensorData<float>();
      if (i < static_cast<size_t>(results_))
        result.emplace_back(data, data + count);
      else {
        auto &state = states_[i - results_];
        if (state.size() != count)
          throw std::runtime_error("denoiser state size changed");
        std::copy_n(data, count, state.data());
      }
    }
    return result;
  }

private:
  int signals_, results_;
  Ort::Env env_;
  Ort::Session session_{nullptr};
  std::vector<std::string> names_, outputs_;
  std::vector<const char *> name_ptrs_, out_ptrs_;
  std::vector<std::vector<int64_t>> shapes_;
  std::vector<size_t> counts_;
  std::vector<std::vector<float>> states_;
};
class DeepFilterNet3 final : public StreamDenoiser {
public:
  explicit DeepFilterNet3(const AssetReader &read)
      : enc_(read, "df3_enc_stream.onnx", 2, 7),
        erb_(read, "df3_erb_dec_stream.onnx", 5, 1),
        df_(read, "df3_df_dec_stream.onnx", 2, 2), fft_(960), up_(3, 1),
        down_(1, 3), window_(960), previous_(480, 0), tail_(480, 0), mean_(32),
        unit_(96) {
    for (int i = 0; i < 960; ++i) {
      double s = std::sin(kPi * (i + .5) / 960);
      window_[i] = std::sin(.5 * kPi * s * s);
    }
    for (int i = 0; i < 32; ++i)
      mean_[i] = -60.f - 30.f * i / 31;
    for (int i = 0; i < 96; ++i)
      unit_[i] = .001f + (.0001f - .001f) * i / 95;
    float high = 9.265f * std::log1p(24000.f / (24.7f * 9.265f)),
          step = high / 32;
    int prev = 0, over = 0, sum = 0;
    for (int i = 1; i <= 32; ++i) {
      float f = 24.7f * 9.265f * (std::exp(i * step / 9.265f) - 1);
      int fb = std::lround(f / 50.f);
      int width = fb - prev - over;
      if (width < 2) {
        over = 2 - width;
        width = 2;
      } else
        over = 0;
      bands_.push_back(width);
      sum += width;
      prev = fb;
    }
    bands_.back() += 481 - sum;
    for (int i = 0; i < 5; ++i)
      history_.emplace_back(481, Complex(0, 0));
  }
  std::vector<float> Process(const std::vector<float> &input,
                             bool flush) override {
    if (ended_)
      throw std::runtime_error("DF3 input after flush");
    total_ += input.size();
    auto x = up_.Run(input, flush);
    pending_.insert(pending_.end(), x.begin(), x.end());
    std::vector<float> enhanced;
    while (pending_.size() >= 480) {
      std::vector<float> hop(pending_.begin(), pending_.begin() + 480);
      pending_.erase(pending_.begin(), pending_.begin() + 480);
      Hop(hop, enhanced);
    }
    if (flush) {
      if (!pending_.empty()) {
        pending_.resize(480, 0);
        Hop(pending_, enhanced);
        pending_.clear();
      }
      for (int i = 0; i < 3; ++i)
        Hop(std::vector<float>(480, 0), enhanced);
      ended_ = true;
    }
    size_t remaining48 = total_ * 3 - produced48_;
    if (enhanced.size() > remaining48)
      enhanced.resize(remaining48);
    produced48_ += enhanced.size();
    auto out = down_.Run(enhanced, flush);
    emitted_ += out.size();
    if (emitted_ > total_ || (flush && emitted_ != total_))
      throw std::runtime_error("DF3 output length mismatch");
    return out;
  }

private:
  void Hop(const std::vector<float> &hop, std::vector<float> &out) {
    std::vector<float> x(960);
    for (int i = 0; i < 480; ++i) {
      x[i] = previous_[i] * window_[i];
      x[i + 480] = hop[i] * window_[i + 480];
    }
    previous_ = hop;
    auto spec = fft_.Forward(x);
    for (auto &v : spec)
      v /= 960.f;
    history_.pop_front();
    history_.push_back(spec);
    std::vector<float> feat_erb(32), feat_spec(192);
    int offset = 0;
    constexpr float alpha = .990f;
    for (int b = 0; b < 32; ++b) {
      float energy = 0;
      for (int j = 0; j < bands_[b]; ++j)
        energy += std::norm(spec[offset + j]) / bands_[b];
      offset += bands_[b];
      float db = 10 * std::log10(energy + 1e-10f);
      mean_[b] = db * (1 - alpha) + mean_[b] * alpha;
      feat_erb[b] = (db - mean_[b]) / 40;
    }
    for (int i = 0; i < 96; ++i) {
      unit_[i] = std::abs(spec[i]) * (1 - alpha) + unit_[i] * alpha;
      float norm = std::sqrt(unit_[i]);
      feat_spec[i] = spec[i].real() / norm;
      feat_spec[i + 96] = spec[i].imag() / norm;
    }
    auto e = enc_.Run({feat_erb, feat_spec});
    float snr = e[6].at(0);
    auto enhanced = history_[2];
    if (snr < -15) {
      std::fill(enhanced.begin(), enhanced.end(), Complex(0, 0));
    } else if (snr <= 35) {
      auto mask = erb_.Run({e[4], e[3], e[2], e[1], e[0]})[0];
      if (mask.size() != 32)
        throw std::runtime_error("DF3 mask size");
      offset = 0;
      for (int b = 0; b < 32; ++b)
        for (int j = 0; j < bands_[b]; ++j)
          enhanced[offset++] *= mask[b];
    }
    if (snr >= -15 && snr <= 35) {
      auto coef = df_.Run({e[4], e[5]})[0];
      if (coef.size() != 960)
        throw std::runtime_error("DF3 coefficients size");
      for (int f = 0; f < 96; ++f) {
        Complex value(0, 0);
        for (int t = 0; t < 5; ++t)
          value += history_[t][f] *
                   Complex(coef[f * 10 + t * 2], coef[f * 10 + t * 2 + 1]);
        enhanced[f] = value;
      }
    }
    // Advance silence as real time too: never bypass STFT/history or discard
    // flush state.
    x = fft_.Inverse(enhanced);
    for (int i = 0; i < 480; ++i) {
      float value = tail_[i] + x[i] * 960 * window_[i];
      tail_[i] = x[i + 480] * 960 * window_[i + 480];
      if (frames_ >= 3)
        out.push_back(value);
    }
    ++frames_;
  }
  Model enc_, erb_, df_;
  Fft fft_;
  Resampler3 up_, down_;
  std::vector<float> window_, previous_, tail_, mean_, unit_, pending_;
  std::vector<int> bands_;
  std::deque<std::vector<Complex>> history_;
  size_t total_ = 0, emitted_ = 0, produced48_ = 0, frames_ = 0;
  bool ended_ = false;
};
} // namespace
std::unique_ptr<StreamDenoiser> CreateStreamDenoiser(const std::string &model,
                                                     const AssetReader &read) {
  if (model == "deepfilternet3")
    return std::make_unique<DeepFilterNet3>(read);
  throw std::runtime_error("unsupported denoiser: " + model);
}
} // namespace amphion_denoise
