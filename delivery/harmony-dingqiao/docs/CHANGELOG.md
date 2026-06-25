# Changelog

## 0.1.0

- 新增纯血鸿蒙 SDK：ASR 工程 `asr/harmony`（`amphion_asr` / `amphion_police` / `amphion_dingqiao`）、TTS 工程 `tts/harmony`（`amphion_tts`）。
- 新增统一交付聚合层 `delivery/harmony-dingqiao/`：同时演示 ASR + TTS 的 `dingqiao_demo` HAP、交付文档与打包脚本。
- 新增核心 ASR ArkTS API 映射：`AmphionRuntime`、`AsrEngine`、`AsrSession`、`AsrConfig`、`AsrCallback`、`AmphionMetrics`。
- 新增鼎桥接口映射：`SpeechRecognizeSdk`、`SpeechRecognitionEngine`、`RecognitionListener`、错误码与 640 字节 PCM 帧契约。
- 新增离线 TTS ArkTS API：`TextToSpeechSdk`、`TextToSpeechEngine`、`TtsCreateEngineParams`、`SpeakParams`，底层走 `sherpa_onnx.OfflineTts`。
- TTS 支持 `SYNTHESIZE_AND_PLAY` 内置播放：`AudioRenderer` writeData 拉模型 + `CircularBuffer`，与 `onData` 流式 PCM 并行。
- 新增 HarmonyOS native 构建脚本、ASR/TTS rawfile 模型同步脚本与客户交付打包脚本。
