# Amphion TTS HarmonyOS SDK

本目录承载纯血鸿蒙（HarmonyOS NEXT / OpenHarmony）原生离线 TTS SDK，独立于 ASR SDK（`asr/harmony`）。

- `sdk/`：TTS HAR（模块名 `amphion_tts`），导出 `TextToSpeechSdk`、`TextToSpeechEngine`、`TtsCreateEngineParams`、`SpeakParams` 等，接口对齐 Android TTS SDK。
- `docs/`：TTS 集成说明。

底层复用上游 `sherpa_onnx` HarmonyOS HAR 的 `OfflineTts`；native `.so` 由共享脚本 `asr/tools/04_build_harmony_so.sh`（已开启 TTS 编译）与 `asr/tools/05_package_har_libs.sh` 产出并注入 `sherpa_onnx` HAR，ASR 与 TTS 共用同一套 native 库。

## 模型资源

模型按 `rawfile/amphion-tts/<voiceId>/` 打包，默认 voiceId 为 `kokoro-zh-en`。把模型放到 `tts/models/amphion-tts/` 后运行：

```bash
bash tts/tools/harmony/pack_harmony_tts_assets.sh
```

## 与统一交付的关系

面向客户的整合 demo（同时演示 ASR + TTS）、交付文档与打包脚本统一放在仓库顶层 `harmony/`。
