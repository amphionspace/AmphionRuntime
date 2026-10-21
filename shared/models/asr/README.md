# Shared ASR model resources

This directory is the repository-level source of truth for ASR model files that
are packaged by more than one platform. Android Gradle tasks and HarmonyOS
Hvigor modules copy these files into their platform-specific package paths at
build time; runtime asset paths remain unchanged.

- `dingqiao/nmnet-student/v1/`: five student/ECAPA ONNX graphs, fixed native order
  and SHA-256 in `manifest.json`. Restore using `node asr/tools/nmnet_model_resources.cjs
  restore diarization/nmnet_v015_conformer/outputs/sdk-export-v8` from the repository
  root. Both platform builds invoke this shared Node.js synchronizer and fail on
  missing or corrupted graphs. Android requires Node.js on PATH (or
  `NMNET_BUILD_NODE` pointing to its executable). Resources are packaged at
  `amphion-dingqiao/nmnet-student/v1`. See the bundled NOTICE for source and release
  prerequisites. This resource addition does not change public backend routing.

- `dingqiao/eres2net.onnx`: voiceprint embedding model.
- `dingqiao/campplus.onnx`: offline complementary diarization model; does not replace voiceprint enrollment or verification.
  Source: `asr/tools/speaker/00_download_models.sh --only campplus-zh`, original name `3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx`.
  SHA-256: `f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11`; upstream 3D-Speaker license is retained in `dingqiao/campplus.LICENSE`.
- `dingqiao/pyannote-segmentation-3.0.onnx`: offline speaker-turn segmentation model.
- `dingqiao/pyannote-segmentation-3.0.LICENSE`: license shipped with the pyannote model.
- `police/lac/v1/lac_encoder.onnx`: Police LAC encoder model.

Do not add platform-local copies of these files. Update the shared file and its
hash/provenance metadata, then rebuild every consuming platform.
