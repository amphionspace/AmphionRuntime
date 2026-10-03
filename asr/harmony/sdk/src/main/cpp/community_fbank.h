#pragma once
#include "community_cancel.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace community {
// The raw per-frame log-mel values are independent of the window-wide mean.
// Keeping one normal-window overlap lets the next 1 s hop reuse 898 of 998
// frames while preserving the exact per-window normalization below.
struct FbankCache {
  static constexpr int kFrames = 998;
  static constexpr int kMels = 80;
  static constexpr int kHopSamples = 16000;
  static constexpr int kOverlapSamples = 144000;
  bool valid = false;
  int64_t window_start_sample = 0;
  std::vector<float> raw_features;
  std::vector<float> overlap_pcm;

  void Clear() noexcept {
    valid = false;
    window_start_sample = 0;
    raw_features.clear();
    overlap_pcm.clear();
  }
};

// Kaldi fbank defaults used by the locked Community-1 WeSpeaker model.
// Window/mel constants are exported from the same torchaudio implementation.
inline std::vector<float> Fbank(const std::vector<float>& pcm,
                                const std::vector<float>& constants,
                                const CancellationToken* cancellation = nullptr,
                                FbankCache* cache = nullptr,
                                int64_t window_start_sample = 0) {
  if (pcm.size() != 160000 || constants.size() != 400 + 80 * 257)
    throw std::runtime_error("invalid Community-1 feature input");
  constexpr int frames = FbankCache::kFrames, fft_size = 512;
  std::vector<float> raw(frames * FbankCache::kMels);
  std::array<std::complex<double>, fft_size> fft;
  std::array<float, 400> samples;
  // Fixed mel filters have zero weight outside their support. Keep the
  // contributing-bin order while avoiding redundant spectrum products.
  std::array<int, FbankCache::kMels> firstBin, endBin;
  for (int m = 0; m < FbankCache::kMels; ++m) {
    CheckCancellation(cancellation);
    int first = 0, end = 257;
    while (first < end && constants[400 + m * 257 + first] == 0.f) ++first;
    while (end > first && constants[400 + m * 257 + end - 1] == 0.f) --end;
    firstBin[m] = first;
    endBin[m] = end;
  }

  bool reused = cache != nullptr && cache->valid &&
      cache->window_start_sample <= std::numeric_limits<int64_t>::max() - FbankCache::kHopSamples &&
      cache->window_start_sample + FbankCache::kHopSamples == window_start_sample &&
      cache->raw_features.size() == raw.size() &&
      cache->overlap_pcm.size() == FbankCache::kOverlapSamples;
  if (reused) {
    // A cache hit is valid only when the PCM overlap is byte-for-byte the same.
    // This protects against a reused sample index after a stream reset or spool
    // replacement while retaining the normal adjacent-window fast path.
    for (int i = 0; i < FbankCache::kOverlapSamples; ++i) {
      if ((i & 4095) == 0) CheckCancellation(cancellation);
      if (pcm[i] != cache->overlap_pcm[i]) {
        reused = false;
        break;
      }
    }
  }

  auto computeFrame = [&](int frame) {
    CheckCancellation(cancellation);
    double sum = 0;
    for (int j = 0; j < 400; ++j) {
      samples[j] = pcm[frame * 160 + j] * 32768.f;
      sum += samples[j];
    }
    float mean = static_cast<float>(sum / 400);
    for (auto& value : samples) value -= mean;
    for (int j = 0; j < 400; ++j)
      fft[j] = (samples[j] - .97f * samples[j == 0 ? 0 : j - 1]) * constants[j];
    for (int j = 400; j < 512; ++j) fft[j] = 0;
    for (int i = 1, j = 0; i < 512; ++i) {
      int bit = 256;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) std::swap(fft[i], fft[j]);
    }
    for (int n = 2; n <= 512; n *= 2) {
      std::complex<double> wn = std::polar(1., -2. * std::acos(-1.) / n);
      for (int i = 0; i < 512; i += n) {
        std::complex<double> w = 1.;
        for (int j = 0; j < n / 2; ++j) {
          auto u = fft[i + j], v = fft[i + j + n / 2] * w;
          fft[i + j] = u + v;
          fft[i + j + n / 2] = u - v;
          w *= wn;
        }
      }
    }
    for (int m = 0; m < FbankCache::kMels; ++m) {
      double energy = 0;
      for (int j = firstBin[m]; j < endBin[m]; ++j)
        energy += std::norm(fft[j]) * constants[400 + m * 257 + j];
      raw[frame * FbankCache::kMels + m] =
          std::log(std::max(static_cast<float>(energy), std::numeric_limits<float>::epsilon()));
    }
  };

  if (reused) {
    for (int frame = 0; frame < 898; ++frame) {
      if ((frame & 63) == 0) CheckCancellation(cancellation);
      std::copy(cache->raw_features.begin() + (frame + 100) * FbankCache::kMels,
                cache->raw_features.begin() + (frame + 101) * FbankCache::kMels,
                raw.begin() + frame * FbankCache::kMels);
    }
    for (int frame = 898; frame < frames; ++frame) computeFrame(frame);
  } else {
    for (int frame = 0; frame < frames; ++frame) computeFrame(frame);
  }

  // Keep the unnormalized tensor only after all frame calculations succeeded.
  // Cancellation during normalization therefore cannot publish a partial cache.
  std::vector<float> raw_for_cache;
  if (cache != nullptr) raw_for_cache = raw;
  for (int m = 0; m < FbankCache::kMels; ++m) {
    CheckCancellation(cancellation);
    double mean = 0;
    for (int f = 0; f < frames; ++f) {
      if ((f & 63) == 0) CheckCancellation(cancellation);
      mean += raw[f * FbankCache::kMels + m];
    }
    const float value = static_cast<float>(mean / frames);
    for (int f = 0; f < frames; ++f) {
      if ((f & 63) == 0) CheckCancellation(cancellation);
      raw[f * FbankCache::kMels + m] -= value;
    }
  }
  if (cache != nullptr) {
    std::vector<float> next_overlap(pcm.begin() + FbankCache::kHopSamples, pcm.end());
    cache->raw_features.swap(raw_for_cache);
    cache->overlap_pcm.swap(next_overlap);
    cache->window_start_sample = window_start_sample;
    cache->valid = true;
  }
  return raw;
}
}
