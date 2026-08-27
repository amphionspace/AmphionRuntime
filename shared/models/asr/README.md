# Shared ASR model resources

This directory is the repository-level source of truth for ASR model files that
are packaged by more than one platform. Android Gradle tasks and HarmonyOS
Hvigor modules copy these files into their platform-specific package paths at
build time; runtime asset paths remain unchanged.

- `dingqiao/eres2net.onnx`: voiceprint embedding model.
- `dingqiao/pyannote-segmentation-3.0.onnx`: offline speaker-turn segmentation model.
- `dingqiao/pyannote-segmentation-3.0.LICENSE`: license shipped with the pyannote model.
- `police/lac/v1/lac_encoder.onnx`: Police LAC encoder model.

Do not add platform-local copies of these files. Update the shared file and its
hash/provenance metadata, then rebuild every consuming platform.
