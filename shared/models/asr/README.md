# Shared ASR model resources

This directory is the repository-level source of truth for ASR model files that
are packaged by more than one platform. Android Gradle tasks and HarmonyOS
Hvigor modules copy these files into their platform-specific package paths at
build time; runtime asset paths remain unchanged.

- `dingqiao/eres2net.onnx`: voiceprint embedding model.
- `dingqiao/campplus.onnx`: offline complementary diarization model; does not replace voiceprint enrollment or verification.
  Source: `asr/tools/speaker/00_download_models.sh --only campplus-zh`, original name `3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx`.
  SHA-256: `f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11`; upstream 3D-Speaker license is retained in `dingqiao/campplus.LICENSE`.
- `dingqiao/pyannote-segmentation-3.0.onnx`: offline speaker-turn segmentation model.
- `dingqiao/community1-segmentation.onnx`: Community-1 segmentation checkpoint exported to ONNX.
- `dingqiao/community1-wespeaker.onnx`: Community-1 WeSpeaker embedding checkpoint exported to ONNX.
- `dingqiao/community1-plda.bin`: generated little-endian runtime parameters for the Community-1 x-vector transform and PLDA/VBx path.
- `dingqiao/community1-plda.npz` and `community1-xvec-transform.npz`: Community-1 VBx/PLDA parameters.
- `dingqiao/pyannote-segmentation-3.0.LICENSE`: license shipped with the pyannote model.
- `police/lac/v1/lac_encoder.onnx`: Police LAC encoder model.

Do not add platform-local copies of these files. Update the shared file and its
hash/provenance metadata, then rebuild every consuming platform.
