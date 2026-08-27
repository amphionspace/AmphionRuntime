# 语音识别 SDK 接口

> 交付契约提示：本文件为 Android 集成说明。跨平台接口契约以《语音识别SDK接口-交付批注版.md》为准；该文档基于《语音识别SDK接口-20260622.md》（v1.1）基线，并在增补项旁批注。

本文描述鼎桥 Android 离线语音识别 SDK 的客户集成接口。SDK 入口包名为 `com.amphion.dingqiao`，核心入口为 `SpeechRecognizeSdk`。

## 1. 最小调用顺序

```kotlin
SpeechRecognizeSdk.init(applicationContext)
SpeechRecognizeSdk.setWorkPath(filesDir.resolve("dingqiao_asr").absolutePath)
SpeechRecognizeSdk.setLogLevel(AmphionLogLevel.INFO) // 可选，在 prepareRuntime 前设置
SpeechRecognizeSdk.setLicense(licensePath, licenseCallback)
// licenseCallback.onResult 后：
SpeechRecognizeSdk.prepareRuntime(runtimeCallback)
// runtimeCallback.onReady 后（推荐异步加载模型）：
SpeechRecognizeSdk.createEngineAsync(CreateEngineParams(language = "zh-CN"), engineCallback)
// engineCallback.onSuccess 后：
val engine = readyEngine
engine.setListener(listener)
engine.startListening(StartParams(sessionId, AudioInfo()))
engine.writeAudio(sessionId, pcmFrame640Bytes)
engine.finish(sessionId)
engine.shutdown()
```

`writeAudio` 输入为 16 kHz、16 bit、单声道 PCM，每帧 640 字节，对应 20 ms 音频。调用 `finish` 表示本次会话音频输入结束，SDK 会输出最后一次 final 结果并回调 `onComplete`。

## 2. 全局接口

| 接口 | 说明 |
|------|------|
| `SpeechRecognizeSdk.init(context: Context)` | 初始化 SDK，必须在 `createEngine`、`registerVoiceprint` 前调用 |
| `SpeechRecognizeSdk.setWorkPath(path: String)` | 设置可读写工作目录，必须在 `createEngine` 前调用 |
| `SpeechRecognizeSdk.getWorkPath(): String` | 查询当前工作目录；未设置时返回空字符串 |
| `SpeechRecognizeSdk.setLogLevel(logLevel: AmphionLogLevel)` | 设置 Core Runtime 日志阈值；默认 `WARN`，排查期可在 `prepareRuntime` 前设置 `INFO`/`DEBUG` |
| `SpeechRecognizeSdk.configureDiagnostics(options: DiagnosticOptions)` | 已废弃的源码兼容入口；运行时调用不会开启采集 |
| `SpeechRecognizeSdk.exportDiagnostics(callback: DiagnosticExportCallback)` | 异步导出专用 Diagnostics AAR 采集的证据；普通 debug/release AAR 明确回调 `INTERNAL_ERROR` |
| `SpeechRecognizeSdk.setLicense(licensePath: String, callback: LicenseActivationCallback)` | 校验并缓存授权，不启动 Runtime、不加载模型 |
| `SpeechRecognizeSdk.prepareRuntime(callback: PrepareRuntimeCallback)` | 准备 Runtime 并由 SDK 预加载默认中英模型；并发调用 single-flight |
| `SpeechRecognizeSdk.getLicenseInfo(): LicenseInfo` | 查询当前已激活授权信息 |
| `SpeechRecognizeSdk.createEngine(params: CreateEngineParams): SpeechRecognitionEngine` | 同步创建识别引擎 |
| `SpeechRecognizeSdk.createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback)` | 异步复用已准备模型并创建引擎；成功回调 `onSuccess` |
| `SpeechRecognizeSdk.unloadModel()` | 卸载内存模型，保留 Runtime 与授权 |
| `SpeechRecognizeSdk.unloadRuntime()` | 卸载 Runtime 和模型，保留已验证授权 |
| `SpeechRecognizeSdk.preloadVoiceprintModel(): Boolean` | 按需预装声纹模型；普通 ASR 不隐式加载 |
| `SpeechRecognizeSdk.registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult` | 注册本地声纹 |
| `SpeechRecognizeSdk.deleteVoiceprint(voiceprintId: String): Boolean` | 删除本地声纹；成功返回 `true`，不存在时抛 `VOICEPRINT_NOT_FOUND` |
| `SpeechRecognizeSdk.deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String): String` | 计算设备 SN 授权白名单哈希 |

`setWorkPath` 指向的目录用于保存声纹 embedding，并承载 SDK 自动准备的声纹模型 `eres2net.onnx`。自 v0.2.7 起，声纹模型已内置在 `dingqiao-asr-v*.aar` 中，客户无需单独下发 `models/eres2net.onnx`。

中英 ASR 三图和标点以 Android ONNX Runtime 1.24.3 生成的 ORT 格式随 AAR
交付。首次创建完成后，同语言、兼容配置的模型由 Runtime 复用；调用
`unloadModel()` 后下一次创建重新冷加载。

`setLogLevel` 只改变 `AmphionRuntime` / `AmphionMetrics` 的日志输出阈值，不改变识别、声纹、
Speaker VAD 或回调顺序。需要包含 Runtime 初始化和模型加载日志时，必须在
`prepareRuntime` 之前设置。

Diagnostics 是编译期能力，不能由 App 在运行时开启。普通 debug/release AAR 不保留识别音频或
诊断事件；专用 diagnostics 变体会有界采集回调、会话配置和实际写入 PCM，并通过
`exportDiagnostics` 导出 summary、完整事件/回调时间线、逐 session result、实际 SDK 输入 WAV、
资源采样、native 状态、build identity 和模型 manifest。活动会话每 5 秒写入崩溃 journal，进程
重启后自动恢复并明确标记 `process-crash-recovery`。诊断包只用于问题定位，不得作为
正式生产依赖；导出失败不改变 ASR 状态或回调顺序。配置快照只记录声纹 ID 数量，不记录 ID 内容。

## 3. 引擎接口

| 接口 | 说明 |
|------|------|
| `setListener(listener: RecognitionListener?)` | 设置识别回调 |
| `startListening(params: StartParams)` | 开始一次识别会话 |
| `writeAudio(sessionId: String, audio: ByteArray)` | 写入一帧 640 字节 PCM 音频 |
| `finish(sessionId: String)` | 结束本次音频输入并等待 final/complete 回调 |
| `cancel(sessionId: String)` | 取消本次识别，不再输出 final |
| `isBusy(): Boolean` | 查询当前引擎是否有进行中的识别会话 |
| `shutdown()` | 释放引擎资源 |
| `setSpeakerVadEnabled(enabled: Boolean)` | 运行时启用或关闭目标说话人 VAD |

一个 `SpeechRecognitionEngine` 同时只处理一个活跃会话。`startListening` 成功后才能写入音频；`finish` 或 `cancel` 后如需继续识别，请重新调用 `startListening` 创建新的会话。

## 4. 参数对象

### AudioInfo

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `audioType` | `String` | `pcm` | 仅支持 `pcm` |
| `sampleRate` | `Int` | `16000` | 仅支持 16000 Hz |
| `sampleBit` | `Int` | `16` | 仅支持 16 bit |
| `soundChannel` | `Int` | `1` | 仅支持单声道 |

### CreateEngineParams

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `language` | `String` | `zh-CN` | 当前 Android 交付包仅支持 `zh-CN`、`zh-en`、`zh_en`，大小写不敏感 |
| `online` | `Int` | `1` | 当前仅支持离线模式 `DingqiaoOnlineMode.OFFLINE` |
| `extraParams` | `Map<String, Any>` | 空 | 扩展参数 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `locate` | `String` | `CN` | 兼容字段；当前仅支持中国区，不改变模型选择 |
| `recognizerMode` | `String` | `short` | `short` 保持旧版有最大单句时长的分段识别；`long` 为会议/持续转写，不做周期性 Rule3 硬切 |
| `sysGeneralLexicon` | `List<String>/String` | 空 | 系统热词；字符串可用换行/中英文逗号分隔；同时作为 LAC 人名纠正候选集 |
| `disablePrepack` | `Boolean/Number/String` | `true` | 默认跳过 ORT INT8 权重 prepack，降低冷加载时间和峰值内存；设为 `false` 可恢复吞吐优先模式 |

SDK 会自动进行保守的 WebRTC AGC2 输入电平归一化，调用方无需配置开关。该处理不会改善低 SNR 或已削波音频，调用方不要再叠加固定软件增益。

### StartParams

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sessionId` | `String` | 空（调用前必须填写） | 非空，只允许字母、数字、下划线、短横线 |
| `audioInfo` | `AudioInfo` | `AudioInfo()` | 音频格式 |
| `extraParams` | `Map<String, Any>` | 空 | 会话扩展参数 |
| `speakerDiarization` | `SpeakerDiarizationConfig?` | `null` | 非空时启用完全离线说话人分离；`maxSpeakers` 范围 1 到 4 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `recognitionMode` | `Number/String` | `1` | 仅支持 `1`（外部写入音频流）；`0`（SDK 内录音）暂不支持 |
| `recognizerMode` | `String` | engine 配置；否则普通调用为 `short`、continuous 为 `long` | 会话级覆盖：`short` 使用 `endpointMaxUtteranceMs`，`long` 只按自然静音或 `finish` 分段；显式值优先，长转写和会议仍建议显式设置 `long` |
| `vadBegin` | `Number/String` | 未启用 | 首次检测到语音前的静音超时，范围 500 到 10000 ms；仅显式传入时启用 |
| `enablePartialResult` | `Boolean` | `true` | 是否回调中间结果 |
| `enablePoliceEnhancement` | `Boolean` | `true` | 是否对 final 文本执行警务术语、车牌和派出所归一化；`false` 返回原始 ASR 文本 |
| `maxAudioDuration` | `Number/String` | 未启用 | 单会话最长音频毫秒数；仅显式传入正有限值时启用，上限 28800000；达到上限后正常自动结束 |
| `enableContinuousRecognition` | `Boolean` | `false` | 设为 `true` 时保持同一个模型会话、禁用 `maxAudioDuration` 自动结束；未显式传 `recognizerMode` 时同时使用 `long`。显式 short/long 优先，仅布尔值 `true` 生效 |
| `endpointMaxUtteranceMs` | `Number/String` | `20000` | 仅 `recognizerMode=short` 生效的单句强制 final 时长；不会结束 session。long 模式忽略该参数 |
| `vadEnd` | `Number/String` | `800` | VAD 尾静音阈值毫秒，范围 500 到 10000 |
| `sessionGeneralLexicon` | `List<String>` | 空 | V1 暂不支持；传入不会作为会话热词生效 |
| `enableVoiceprintVerification` | `Boolean` | `false` | 是否在 final 阶段返回目标声纹相似度 |
| `enableSpeakerVad` | `Boolean/String/Number` | `false` | 是否启用目标说话人离场提前 endpoint |
| `voiceprintIds` | `List<String>/String` | 空 | 声纹 ID 列表；字符串可用换行/中英文逗号分隔 |
| `speakerVadThreshold` | `Number/String` | `0.40` | 目标说话人 VAD 阈值 |
| `speakerVadWindowMs` | `Number/String` | `1000` | 目标说话人 VAD 窗长 |
| `speakerVadHopMs` | `Number/String` | `300` | 目标说话人 VAD 步长 |
| `speakerVadConsecutiveBelow` | `Number/String` | `2` | 连续低于阈值多少次触发 endpoint |

## 5. 回调

```kotlin
interface RecognitionListener {
    fun onStart(sessionId: String, eventMessage: String)
    fun onEvent(sessionId: String, eventCode: Int, eventMessage: String)
    fun onResult(sessionId: String, result: SpeechRecognitionResult)
    fun onSpeakerDiarizationUpdate(sessionId: String, update: SpeakerDiarizationUpdate) {}
    fun onSpeakerDiarizationResult(sessionId: String, result: SpeakerDiarizationResult) {}
    fun onComplete(sessionId: String, eventMessage: String)
    fun onError(sessionId: String, errorCode: Int, errorMessage: String)
}
```

| 回调 | 说明 |
|------|------|
| `onStart` | 会话启动成功 |
| `onEvent` | 语音端点、声纹 VAD 状态等事件 |
| `onResult` | 识别结果，包含 partial 与 final |
| `onSpeakerDiarizationUpdate` | 已公开 utterance 的说话人归属发生变化；通过 `utteranceId + revision` 覆盖旧显示 |
| `onSpeakerDiarizationResult` | 启用说话人分离时的唯一最终分离结果；位于最后一个 `onResult(isLast=true)` 与 `onComplete` 之间 |
| `onComplete` | 主动 `finish`、达到 `vadBegin` 首段静音阈值或达到显式 `maxAudioDuration` 上限后，识别完整结束 |
| `onError` | 发生错误 |

`SpeechRecognitionResult`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `isFinal` | `Boolean` | 是否最终结果 |
| `isLast` | `Boolean` | 是否本次会话结束（`finish` 或达到上限自动结束）对应的最后结果 |
| `result` | `String` | 识别文本；final 为警务增强后文本 |
| `beginTime` | `Int?` | 起始时间毫秒，可能为空 |
| `endTime` | `Int?` | 结束时间毫秒，可能为空 |
| `speakerSimilarity` | `Float?` | final 且启用声纹能力时返回 |
| `utteranceId` | `String?` | 启用说话人分离时 final utterance 的稳定 ID |
| `speakerIndex` | `Int` | 稳定的零基说话人序号；`-1` 表示尚未分配 |
| `secondarySpeakerIndexes` | `List<Int>` | 重叠说话时的其他说话人序号 |
| `speakerConfidence` | `Float` | `[0,1]` 归属分数，不是校准概率 |

`speakerSimilarity` 是可选值。`TargetSpeakerConfig.minSegSec` 默认并在鼎桥适配层固定为 `0`，SDK
不设置最短时长门槛；ASR 已产生非空 text/token 时，SDK 使用本句非空真实 PCM 尝试评分。短句
相似度更易波动，音频时长、业务阈值和接受策略全部由业务方判断。
没有 ASR 语音证据、没有真实 PCM 或 extractor 技术上无法产生 embedding 时仍可省略字段；SDK
不会填充假分数、复制上一句分数或补静音。非 last 的 token-only native endpoint 不形成公开
final，其 PCM 会保留到下一条公开结果。

事件码：

| 事件码 | 名称 | 说明 |
|--------|------|------|
| `1` | `SPEECH_BEGIN` | 检测到语音开始 |
| `3` | `SPEECH_END` | 检测到语音结束 |
| `20` | `SPEAKER_VAD_CHANGED` | 目标说话人 VAD 开关变化 |
| `21` | `SPEAKER_VAD_DEBUG` | 目标说话人 VAD 调试信息 |
| `22` | `SPEAKER_VAD_REJECTED` | 目标说话人 VAD 拒绝当前 final |

Speaker VAD 拒绝非目标片段时，会在 `SPEAKER_VAD_REJECTED` 事件后回调空的
`onResult(isFinal=true)`，用于结束并清除此前可能公开的 speculative partial。该结果的 `isLast`
沿用底层结束标记；`isLast=false` 时会话继续且不回调 `onComplete`，`isLast=true` 时随后恰好回调
一次 `onComplete`。

`vadBegin` 按实际写入并由 VAD 处理的 PCM 时长计算；只调用 `startListening` 而不写入音频不会计时。达到阈值且始终未检测到语音时，SDK 回调空的 `onResult(isFinal=true,isLast=true)`，随后回调 `onComplete`，不回调 `SPEECH_BEGIN`、`SPEECH_END` 或错误。一旦检测到首个真实起音，本会话不再触发 `vadBegin`，后续停顿由 `vadEnd` 处理。该行为不依赖 `enablePartialResult`。

传入可用的 `voiceprintIds` 时，鼎桥适配层的 `minSegSec=0`，不会额外延长 `vadBegin` 确认窗。纯静音和未被 VAD/ASR 确认的活动仍按配置有界结束。

### 离线说话人分离

```kotlin
engine.startListening(
    StartParams(
        sessionId = sessionId,
        audioInfo = AudioInfo(),
        extraParams = mapOf("recognizerMode" to "long"),
        speakerDiarization = SpeakerDiarizationConfig(maxSpeakers = 4),
    )
)
```

该能力使用 AAR 内置 pyannote segmentation 与 eres2net 模型，断网可用，适合会议长转写。SDK 以
10 秒窗口、2.5 秒 hop 增量推理，支持重叠说话；在线聚类产生的显示序号会在后续证据到达时通过
revision 修订。`finish` 非阻塞，SDK 等待 ASR 尾结果和分离尾结果后按固定顺序回调：唯一 last →
`onSpeakerDiarizationResult` → 唯一 complete。分离超时或模型/存储不可用时仍保持 ASR 完整结束，
最终结果通过 `degraded/degradedReason/degradedMessage` 明确降级；`cancel` 不产生 last、最终分离结果
或 complete。

## 6. 声纹

注册声纹：

```kotlin
val result = SpeechRecognizeSdk.registerVoiceprint(
    VoiceprintRegisterParams(
        samplePaths = listOf("/sdcard/sample1.wav"),
        audioInfo = AudioInfo()
    )
)
```

| 项 | 要求 |
|----|------|
| 样本格式 | 16 kHz、16 bit、单声道 PCM 或 WAV |
| 样本时长 | 每段 3 到 8 秒 |
| 样本数量 | 至少 1 段，建议多段提升稳定性 |
| 返回 | `VoiceprintRegisterResult.voiceprintId` |

删除声纹：

```kotlin
SpeechRecognizeSdk.deleteVoiceprint(voiceprintId)
```

会话中启用声纹相似度：

```kotlin
StartParams(
    sessionId = sessionId,
    audioInfo = AudioInfo(),
    extraParams = mapOf(
        "enableVoiceprintVerification" to true,
        "voiceprintIds" to listOf(voiceprintId)
    )
)
```

SDK 不在内部丢弃非目标说话人结果；已有 ASR 语音证据和非空真实 PCM 的 final 会尝试返回增强
文本与 `speakerSimilarity`，是否接受及短句阈值风险由客户业务侧判定。启用 `enableSpeakerVad`
时，SDK 可在目标说话人离场后提前切句。

## 7. 授权

正式 App 授权文件名默认为 `amphion-license.lic`。本次正式授权面向：

| 项 | 值 |
|----|----|
| 应用包名 | 可记录 com.tdtech.tiassistant，不作为授权限制 |
| 授权能力 | ASR,TTS |
| 绑定方式 | 设备 SN 白名单、到期时间；如 license 内写入签名证书 SHA-256，则同时校验证书 |

设备绑定哈希规则为 `SHA-256(normalizedSn + deviceIdSaltId)`，其中 `normalizedSn` 为 trim 后转大写。默认 `deviceIdSaltId` 为 `DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`。

Demo APK 内置 license 仅用于体验：记录包名 com.amphion.dingqiao.demo，授权能力为 ASR，不绑定 SN，不可用于正式宿主。

## 8. 错误码

| 错误码 | 名称 | 说明 |
|--------|------|------|
| `1002200001` | `CREATE_ENGINE_FAILED` | 创建引擎失败 |
| `1002200002` | `START_LISTENING_FAILED` | 启动识别失败 |
| `1002200003` | `MAX_AUDIO_DURATION` | 已废弃：达到单会话最长音频时改为自动结束识别，不再回调此错误 |
| `1002200004` | `FINISH_FAILED` | 结束识别失败 |
| `1002200005` | `CANCEL_FAILED` | 取消识别失败 |
| `1002200006` | `ENGINE_BUSY` | 引擎忙 |
| `1002200007` | `ENGINE_NOT_INITIALIZED` | SDK 未初始化 |
| `1002200008` | `ENGINE_DESTROYED` | 引擎已释放 |
| `1002200009` | `INTERNAL_ERROR` | 内部错误 |
| `1002200010` | `NOT_LISTENING` | 未处于识别中 |
| `1002200011` | `RECOGNITION_ERROR` | 识别错误 |
| `1002200012` | `NO_MIC_PERMISSION` | 兼容保留；当前不支持 SDK 内录音，因此不会主动发出 |
| `1002200020` | `VOICEPRINT_REGISTER_FAILED` | 声纹注册失败 |
| `1002200021` | `VOICEPRINT_SAMPLE_COUNT` | 声纹样本数量不足 |
| `1002200022` | `VOICEPRINT_SAMPLE_DURATION` | 声纹样本时长不符合要求 |
| `1002200024` | `VOICEPRINT_NOT_FOUND` | 声纹不存在 |
| `1002200030` | `LICENSE_FILE_UNREADABLE` | 授权文件不可读 |
| `1002200031` | `LICENSE_INVALID` | 授权无效 |
| `1002200032` | `LICENSE_EXPIRED` | 授权已过期 |
| 1002200033 | LICENSE_DEVICE_MISMATCH | 设备 SN 不在授权白名单，或 license 内写入签名证书且签名不匹配 |
| `1002200034` | `LICENSE_NOT_SET` | 未设置授权 |
| `1002200035` | `LICENSE_ACTIVATION_FAILED` | 授权激活失败 |
