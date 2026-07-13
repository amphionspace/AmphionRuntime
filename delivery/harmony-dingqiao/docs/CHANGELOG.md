# Changelog

## 0.1.0 - hotfix 2026-07-13（声纹模型与生命周期）

- 声纹模型内置到 `amphion_dingqiao.har`，由 SDK 自动准备到 `setWorkPath`，Demo 和宿主不再导入模型。
- 声纹注册与 Android 对齐：至少 1 条 3~8 秒样本，不限制样本数量上限。
- 明确生命周期：`prepareRuntime()` 只准备磁盘资源，不加载声纹 extractor；`unloadModel()` 卸载内存 extractor，但保留模型文件和已注册 embedding。
- 普通 final 声纹校验改为 N-API 后台加载 extractor，ASR 启动、音频写入和中间结果不等待；只有 final 必要时等待。Speaker VAD 因流式打分仍在冷启动时同步加载。

## 0.1.0 — hotfix 2026-07-12（Harmony ASR 冷加载）

- `zhen` encoder/INT8 decoder/joiner 与标点模型在构建期转换为 ARM CPU ORT 格式，运行时关闭重复图优化并直接使用 rawfile 映射模型字节。
- recognizer 与标点异步并行加载；transducer Session 采用 encoder 关键 lane 与 decoder/joiner 辅助 lane，相同配置使用 single-flight 与进程内 pool。
- 鼎桥配置使用 4 个 ORT worker，并跳过收益不足的 800 ms eager warmup。
- 新增独立进程 `createEngineAsync` 加载基准，固定设备构建、模型源哈希、HAP/native hash、线程数、预热样本和标点状态。
- 真机 `zhen` 冷加载 p50 从 3884.5 ms 降至 774.5 ms，p95 为 810.25 ms；pool hit 为 0–1 ms。48 轮真实音频回归通过。

## 0.1.0 — hotfix 2026-07-10（授权、模型与真机验收）

- `SpeechRecognizeSdk.init` 支持宿主注入 `deviceIdProvider`；普通 Demo 使用 ODID，特权宿主保留硬件 SN 路径。
- 模型打包和 signed HAP 增加强制 manifest 路径、大小、SHA-256 校验。
- signed HAP 增加 profile、bundle/module 和预期证书链校验；客户包支持显式 `--asr-only` 模式，并在仅依赖自包含 ASR HAR 的干净宿主中执行编译验收。
- Sherpa Harmony NAPI 捕获 recognizer 创建异常并转成 ArkTS 错误，避免无效 ONNX 导致 `SIGABRT`。
- 新增一键预检和 USB 真机 smoke，完成标准为页面进入“引擎就绪”。

## 0.1.0 — hotfix 2026-07-08（声纹 ASR 崩溃）

- 修复：开启「声纹校验」启动识别时 native abort 崩溃。`amphion_asr` 的 `Runtime.ets`
  `createSpeakerExtractor` 对绝对路径模型（`${workPath}/eres2net.onnx`）不再传 `resourceManager`，
  避免 sherpa 走 rawfile-only 加载器打不开文件系统绝对路径而崩溃；与 `SpeakerEnroller` 的
  `startsWith('/')` 判定对齐。注册路径本就正确，故此前「注册成功、识别崩溃」。
- 说明：`eres2net.onnx` 为合法 ONNX（非 `.pth`），无需重导；模型文件不变。

## 0.1.0

- 新增纯血鸿蒙 SDK：ASR 工程 `asr/harmony`（`amphion_asr` / `amphion_police` / `amphion_dingqiao`）、TTS 工程 `tts/harmony`（`amphion_tts`）。
- 新增统一交付聚合层 `delivery/harmony-dingqiao/`：同时演示 ASR + TTS 的 `dingqiao_demo` HAP、交付文档与打包脚本。
- 新增核心 ASR ArkTS API 映射：`AmphionRuntime`、`AsrEngine`、`AsrSession`、`AsrConfig`、`AsrCallback`、`AmphionMetrics`。
- 新增鼎桥接口映射：`SpeechRecognizeSdk`、`SpeechRecognitionEngine`、`RecognitionListener`、错误码与 640 字节 PCM 帧契约。
- 新增离线 TTS ArkTS API：`TextToSpeechSdk`、`TextToSpeechEngine`、`TtsCreateEngineParams`、`SpeakParams`，底层走 `sherpa_onnx.OfflineTts`。
- TTS 支持 `SYNTHESIZE_AND_PLAY` 内置播放：`AudioRenderer` writeData 拉模型 + `CircularBuffer`，与 `onData` 流式 PCM 并行。
- 新增 HarmonyOS native 构建脚本、ASR/TTS rawfile 模型同步脚本与客户交付打包脚本。
