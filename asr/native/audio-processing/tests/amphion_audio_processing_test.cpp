#include "amphion_audio_processing.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <vector>

int main() {
  assert(amphion_agc_create(0) == nullptr);

  AmphionAgc* agc = amphion_agc_create(16000);
  assert(agc != nullptr);

  std::vector<float> silence(160, 0.0f);
  for (int frame = 0; frame < 20; ++frame) {
    assert(amphion_agc_process(agc, silence.data(), silence.size()) == 0);
  }
  for (float sample : silence) {
    assert(sample == 0.0f);
  }

  // A low-level speech-like signal must receive useful gain without clipping. This protects the
  // actual customer behavior, not only construction and framing.
  double input_energy = 0.0;
  double output_energy = 0.0;
  float peak = 0.0f;
  for (int frame = 0; frame < 300; ++frame) {
    std::vector<float> speech(160);
    for (size_t i = 0; i < speech.size(); ++i) {
      const double t = static_cast<double>(frame * 160 + i) / 16000.0;
      speech[i] = static_cast<float>(0.0015 *
          (std::sin(2.0 * M_PI * 180.0 * t) + 0.5 * std::sin(2.0 * M_PI * 620.0 * t)));
      input_energy += speech[i] * speech[i];
    }
    assert(amphion_agc_process(agc, speech.data(), speech.size()) == 0);
    for (float sample : speech) {
      output_energy += sample * sample;
      peak = std::max(peak, std::abs(sample));
    }
  }
  // The production preset includes a conservative gain floor so real low-level speech is not left
  // entirely to the adaptive estimator. Keep the effective speech-like gain near the 8 dB startup
  // target while still allowing the adaptive controller to reduce it after speech stabilizes.
  assert(output_energy > input_energy * 6.0);
  assert(peak < 1.0f);

  // An abrupt transition to a normal/loud speaker must remain finite and inside float PCM range.
  // This protects the adjacent limiter/saturation behavior when the gain floor is enabled.
  double loud_input_energy = 0.0;
  double loud_output_energy = 0.0;
  float loud_peak = 0.0f;
  for (int frame = 0; frame < 50; ++frame) {
    std::vector<float> speech(160);
    for (size_t i = 0; i < speech.size(); ++i) {
      const double t = static_cast<double>(frame * 160 + i) / 16000.0;
      speech[i] = static_cast<float>(0.45 *
          (std::sin(2.0 * M_PI * 180.0 * t) + 0.5 * std::sin(2.0 * M_PI * 620.0 * t)));
      loud_input_energy += speech[i] * speech[i];
    }
    assert(amphion_agc_process(agc, speech.data(), speech.size()) == 0);
    for (float sample : speech) {
      assert(std::isfinite(sample));
      loud_output_energy += sample * sample;
      loud_peak = std::max(loud_peak, std::abs(sample));
    }
  }
  assert(loud_output_energy > loud_input_energy * 0.25);
  assert(loud_peak <= 1.0f);

  std::vector<float> wrong_size(159, 0.0f);
  assert(amphion_agc_process(agc, wrong_size.data(), wrong_size.size()) != 0);

  std::vector<float> invalid(160, 0.0f);
  invalid[10] = NAN;
  assert(amphion_agc_process(agc, invalid.data(), invalid.size()) != 0);

  amphion_agc_destroy(agc);
  return 0;
}
