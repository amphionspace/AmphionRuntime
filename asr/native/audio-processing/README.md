# ASR audio processing

This module builds the per-session WebRTC AGC2 preprocessing backend used by Android and Harmony
ASR SDKs. Every session uses the same conservative preset, so callers do not choose an AGC mode.
The processor uses a 4 dB fixed digital floor plus AGC2's speech-probability-driven adaptive gain:
6 dB headroom, 20 dB maximum adaptive gain, 4 dB initial adaptive gain, 6 dB/s maximum gain change
and -50 dBFS maximum output noise level.

AGC normalizes the ASR input level; it does not improve SNR, remove noise, repair clipping or change
the raw PCM used by Silero VAD, initial-silence tracking, speaker VAD and voiceprint scoring.

Build with `asr/tools/03_build_agc_native.sh host|android-arm64-v8a|ohos-arm64-v8a`, then use the
existing AAR/HAR packaging scripts. WebRTC Audio Processing 2.1 is pinned by source hash in the
Meson wrap. Its BSD license is reproduced in `LICENSES/WEBRTC_AUDIO_PROCESSING.txt`; its Abseil
dependency is Apache-2.0, the same license text provided by the repository root `LICENSE`.
