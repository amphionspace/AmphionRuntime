# Changelog

## 0.2.8 - 2026-07-18（新声学模型适配与交付校验）

- 声纹严格有效语音不足 `minSegSec`，但 ASR 已确认非空 text/token 且当前句真实 PCM 达到门槛时，
  改用当前句 PCM 计算 `speakerSimilarity`；严格评分仍为主路径，短句、纯静音和空 terminal final
  不填充或复制分数。
- `maxAudioDuration` 移除 20000 ms 最小钳制；显式正有限值按调用值生效，`8000` 即在写入约
  8000 ms PCM 后自动结束，仍保留 28800000 ms 上限。
- 新增 `voiceprint-fallback` cold/warm 真机门禁、8 秒 burst/paced 精确帧数门禁，以及本次问题的
  根因复盘和发布测试流程。
- 适配 0718 新声学模型的警务术语后处理，补充易混词归一化以及“情指行”“登录”语境护栏，
  并同步 Harmony 与 Android 行为。
- Speaker VAD 默认参数延续 0.2.7：阈值 `0.35`、窗口 `1500 ms`、步长 `500 ms`。
- 中英 joiner 使用 FP32 `joiner.onnx` 生成运行时 ORT；交付校验固定 ONNX 源模型身份并核对
  运行时清单，避免转换产物差异影响版本确认。

## 0.2.6 - 2026-07-16（端点回调内结束兼容）

- 修复调用方在 `SPEECH_END`（`eventCode=3`）回调内同步调用 `finish()` 时，SDK 先返回带文本的
  `isLast=false` final、随后又返回空 `isLast=true` final 的兼容性回退。
- 当该端点回调只请求结束且没有更早排队的音频时，当前带文本 final 直接成为本 session 唯一的
  `isLast=true` 结果，随后仍只回调一次 `onComplete`。
- 保留回调重入隔离与 FIFO 顺序；`writeAudio -> finish` 已排队时不会跳过待处理音频，也不使用全局
  `finishRequested` 把较早的异步 final 误标为 last。

## 0.2.5 - 2026-07-16（生命周期回归防护与交付证据）

- 修复 `onStart` 会话发布门禁的跨 session 代次隔离，旧 session 的迟到 started 信号不能解锁新 session。
- 将同一 generation 校验扩展到全部 native 回调，并在客户 listener 返回后复检；回调内 cancel/restart 时，旧 final/error/stopped 不再污染新 session。
- `maxAudioDuration` 改为仅在显式传入有限值时启用；缺省或非法值不再隐式触发 20 秒自动结束。
- 增加 `speaker-vad-onstart`、`numeric-edge` 和 `max-duration` 真机门禁，覆盖声纹运行期开关、非法数值参数和显式最大时长自动结束。
- 增加历史生命周期问题闭环说明、客户脱敏验证摘要和机器可读证据，并在组包与 CI 中执行脱敏检查。
- 发布包、`amphion_dingqiao` HAR、核心 ASR/Police HAR 和 Demo HAP 的版本统一为 0.2.5。

## 0.1.0 - hotfix 2026-07-15（声纹与首段超时组合边界）

- 修复底层 session 构造同步触发 `onStart` 时，鼎桥适配层尚未发布 session，调用方在 `onStart` 内冲刷录音缓存会收到 `1002200010 NOT_LISTENING`、导致首次识别失败的问题。
- `onStart` 现在只在 session 已保存且目标说话人配置完成后对外发送；新增 32/88 帧回调内同步写入门禁，并保留 `onStart` 内取消能力。
- 修复 `vadBegin=1000` 下 VAD/流式 ASR 暂未暴露起音、停止刷新却已有文本时，真实首句被错误标成 `isLast=true` 的竞态。
- 声纹校验或 Speaker VAD 开启时，纯静音仍按 `vadBegin` 结束；初始窗内存在连续未决声学活动时才使用一次默认 1.5 秒确认窗，窗末只接受近期语音型活动或 ASR text/token，避免旧脉冲永久解除计时。
- 声学 backstop 使用固定 20 ms 窗、连续活动、能量变化和过零率联合判定；不依赖调用方分帧，不把稳态高能非语音永久当作 speech，也不伪造 speech 事件。
- Core SDK 在首段计时 armed 时按固定 20 ms slice 推进 ASR/VAD 决策，避免大块输入中 deadline 之后的音频回看并改变之前的超时结果。
- 增加 `voiceprint-vad-begin` 与 `voiceprint-vad-begin-idle` 真机模式，分别验证真实语音在显式 `finish` 前无 `isLast`，以及纯静音/稳态高能非语音仍有界自动结束。
- 明确 `vadBegin` 上限是 10000 ms，调用方传入 60000 ms 并不代表等待 60 秒。

## 0.1.0 - hotfix 2026-07-14（跨端参数与 VAD 前端点）

- Android 与 Harmony 补齐 `vadBegin`：仅显式传入时启用，按底层实际处理的 PCM 时长计时，真实起音优先于阈值边界。
- 首段持续静音达到阈值后正常返回一个空的 last final 和一次 `onComplete`，不发送 speech 事件或错误；结束后可立即启动下一会话。
- 补齐 `recognitionMode`、`recognizerMode`、`locate`、`maxAudioDuration` 上限和 `NO_MIC_PERMISSION=1002200012` 兼容契约；`sessionGeneralLexicon` 仍明确为 V1 不支持。
- 增加 USB 真机 `vad-begin` 模式，使用真实 WAV 验证起音事件，并在 SDK 自测中覆盖持续静音自动结束。

## 0.1.0 — hotfix 2026-07-13（License / Runtime / Model 生命周期）

- `setLicense` 只执行离线授权校验与缓存，不再隐式拉起 Runtime。
- 新增 `prepareRuntime` / `unloadRuntime` 和 `unloadModel`，形成 License、Runtime、Model 三层控制；`unloadRuntime` 保留已验证授权，模型未卸载时跟随释放。
- `createEngineAsync` / `createEngine` 在模型未加载时加载，同语言、同配置已加载时复用。
- 新增 HarmonyOS 客户接口文档和十轮全流程耗时、SDK 净内存报告及甲方简版摘要，并纳入客户交付包。

## 0.1.0 - hotfix 2026-07-13（声纹模型与生命周期）

- 声纹模型内置到 `amphion_dingqiao.har` 并由 SDK 直接加载，Demo 和宿主不再导入模型。
- 声纹注册与 Android 对齐：至少 1 条 3~8 秒样本，不限制样本数量上限。
- 明确生命周期：`prepareRuntime()` 不读取声纹模型；`unloadModel()` 确定性卸载内存 extractor，但保留 HAR 模型和已注册 embedding。
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
