#pragma once
#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdint>
#include <deque>
#include <stdexcept>
#include <vector>

namespace amphion_denoise {
constexpr double kPi = 3.14159265358979323846;
// Mixed-radix FFT, preallocated scratch. Supports both 512 and 960 without DFT
// O(N^2).
class Fft {
public:
  explicit Fft(int n) : n_(n), roots_(n), input_(n), output_(n), scratch_(n) {
    for (int i = 0; i < n; ++i)
      roots_[i] = std::polar(1.0, -2 * kPi * i / n);
  }
  std::vector<std::complex<float>> Forward(const std::vector<float> &x) {
    if (x.size() != static_cast<size_t>(n_))
      throw std::runtime_error("FFT input size");
    for (int i = 0; i < n_; ++i)
      input_[i] = x[i];
    Transform(input_.data(), 1, n_, output_.data(), false);
    std::vector<std::complex<float>> y(n_ / 2 + 1);
    for (size_t i = 0; i < y.size(); ++i)
      y[i] = static_cast<std::complex<float>>(output_[i]);
    return y;
  }
  std::vector<float> Inverse(const std::vector<std::complex<float>> &x) {
    if (x.size() != static_cast<size_t>(n_ / 2 + 1))
      throw std::runtime_error("IFFT input size");
    for (int i = 0; i <= n_ / 2; ++i)
      input_[i] = x[i];
    input_[0].imag(0);
    input_[n_ / 2].imag(0);
    for (int i = 1; i < n_ / 2; ++i)
      input_[n_ - i] = std::conj(input_[i]);
    Transform(input_.data(), 1, n_, output_.data(), true);
    std::vector<float> y(n_);
    for (int i = 0; i < n_; ++i)
      y[i] = output_[i].real() / n_;
    return y;
  }

private:
  void Transform(const std::complex<double> *in, int stride, int n,
                 std::complex<double> *out, bool inverse) {
    if (n == 1) {
      out[0] = *in;
      return;
    }
    int radix = 2;
    while (n % radix)
      ++radix;
    int m = n / radix;
    for (int j = 0; j < radix; ++j)
      Transform(in + j * stride, stride * radix, m, out + j * m, inverse);
    for (int k = 0; k < n; ++k) {
      std::complex<double> v = 0.;
      for (int j = 0; j < radix; ++j) {
        auto w = roots_[(j * k * (n_ / n)) % n_];
        if (inverse)
          w = std::conj(w);
        v += out[j * m + k % m] * w;
      }
      scratch_[k] = v;
    }
    std::copy_n(scratch_.begin(), n, out);
  }
  int n_;
  std::vector<std::complex<double>> roots_, input_, output_, scratch_;
};

// Centered 61-tap Kaiser FIR, equivalent filter to scipy resample_poly 3:1 /
// 1:3. Waits for future filter support, removes its delay, and retains only
// required samples.
class Resampler3 {
public:
  Resampler3(int up, int down) : up_(up), down_(down), h_(61) {
    double sum = 0;
    for (int i = 0; i < 61; ++i) {
      double t = (i - 30) / 3.;
      double sinc = t == 0 ? 1. : std::sin(kPi * t) / (kPi * t);
      double w =
          Bessel(5 *
                 std::sqrt(std::max(0., 1. - std::pow((i - 30) / 30., 2)))) /
          Bessel(5);
      h_[i] = sinc * w / 3.;
      sum += h_[i];
    }
    for (auto &h : h_)
      h *= up / sum;
  }
  std::vector<float> Run(const std::vector<float> &x, bool flush = false) {
    buffer_.insert(buffer_.end(), x.begin(), x.end());
    received_ += x.size();
    int64_t limit = flush ? (received_ * up_ + down_ - 1) / down_ : INT64_MAX;
    std::vector<float> out;
    while (emitted_ < limit) {
      int64_t center = 30 + emitted_ * down_;
      if (!flush && center / up_ >= received_)
        break;
      double v = 0;
      int64_t lo = std::max<int64_t>(0, (center - 60 + up_ - 1) / up_),
              hi = std::min<int64_t>(received_ - 1, center / up_);
      for (int64_t i = lo; i <= hi; ++i) {
        int tap = static_cast<int>(center - i * up_);
        if (tap >= 0 && tap < 61) {
          if (i < base_)
            throw std::runtime_error("resampler history underflow");
          v += buffer_[i - base_] * h_[tap];
        }
      }
      out.push_back(static_cast<float>(v));
      ++emitted_;
    }
    int64_t needed =
        std::max<int64_t>(0, (30 + emitted_ * down_ - 60 + up_ - 1) / up_);
    while (base_ < needed && !buffer_.empty()) {
      buffer_.pop_front();
      ++base_;
    }
    return out;
  }

private:
  static double Bessel(double x) {
    double sum = 1, term = 1;
    for (int k = 1; k < 40; ++k) {
      term *= x * x / (4 * k * k);
      sum += term;
      if (term < 1e-16 * sum)
        break;
    }
    return sum;
  }
  int up_, down_;
  int64_t received_ = 0, emitted_ = 0, base_ = 0;
  std::vector<double> h_;
  std::deque<float> buffer_;
};
} // namespace amphion_denoise
