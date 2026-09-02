#pragma once

#include <algorithm>
#include <vector>

struct StreamingFinalConditionPlan {
  bool use_chunk_condition = false;
  int condition_frames = 0;
};

inline StreamingFinalConditionPlan BuildStreamingFinalConditionPlan(
    bool zero_pad_with_chunk_condition,
    int window_frames,
    int pre_lookahead_len) {
  const int safe_window_frames = std::max(0, window_frames);
  const int safe_pre_lookahead_len = std::max(0, pre_lookahead_len);
  return {
      zero_pad_with_chunk_condition,
      safe_window_frames + (zero_pad_with_chunk_condition ? safe_pre_lookahead_len : 0)};
}

inline void PadStreamingFinalConditionFrames(
    std::vector<float>* frames,
    bool zero_pad_with_chunk_condition,
    int pre_lookahead_len,
    int channels) {
  if (!zero_pad_with_chunk_condition || frames == nullptr) {
    return;
  }
  const int trailing_frames = std::max(0, pre_lookahead_len);
  const int safe_channels = std::max(0, channels);
  frames->resize(frames->size() + static_cast<size_t>(trailing_frames * safe_channels), 0.0f);
}
