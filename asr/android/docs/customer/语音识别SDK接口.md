# 语音识别 SDK 接口

本文描述鼎桥 Android 离线语音识别 SDK 的客户集成接口。SDK 入口包名为 `com.amphion.dingqiao`，核心入口为 `SpeechRecognizeSdk`。

## 1. 最小调用顺序

```kotlin
SpeechRecognizeSdk.init(applicationContext)
SpeechRecognizeSdk.setWorkPath(filesDir.resolve("dingqiao_asr").absolutePath)
SpeechRecognizeSdk.setLicense(licensePath, licenseCallback) // 正式宿主需要

val engine = SpeechRecognizeSdk.createEngine(
    CreateEngineParams(language = "zh-CN")
)
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
| `SpeechRecognizeSdk.setLicense(licensePath: String, callback: LicenseActivationCallback)` | 激活正式授权文件，正式宿主建议在 `createEngine` 前调用 |
| `SpeechRecognizeSdk.getLicenseInfo(): LicenseInfo` | 查询当前已激活授权信息 |
| `SpeechRecognizeSdk.createEngine(params: CreateEngineParams): SpeechRecognitionEngine` | 同步创建识别引擎 |
| `SpeechRecognizeSdk.createEngine(params: CreateEngineParams, callback: CreateEngineCallback)` | 异步创建识别引擎 |
| `SpeechRecognizeSdk.registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult` | 注册本地声纹 |
| `SpeechRecognizeSdk.deleteVoiceprint(voiceprintId: String)` | 删除本地声纹 |
| `SpeechRecognizeSdk.deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String): String` | 计算设备 SN 授权白名单哈希 |

`setWorkPath` 指向的目录用于保存声纹 embedding，并承载 SDK 自动准备的声纹模型 `eres2net.onnx`。自 v0.2.7 起，声纹模型已内置在 `dingqiao-asr-v*.aar` 中，客户无需单独下发 `models/eres2net.onnx`。

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
| `language` | `String` | 无 | 支持 `zh-CN`、`zh-en`、`zh_en`、`zh-yue`、`zh_yue` |
| `online` | `Int` | `1` | 当前仅支持离线模式 `DingqiaoOnlineMode.OFFLINE` |
| `extraParams` | `Map<String, Any>` | 空 | 扩展参数 |

`extraParams["sysGeneralLexicon"]` 可传入 `List<String>` 作为系统热词。SDK 会将客户热词与警务域默认热词合并后用于 ASR 解码。

### StartParams

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sessionId` | `String` | 无 | 非空，只允许字母、数字、下划线、短横线 |
| `audioInfo` | `AudioInfo` | 无 | 音频格式 |
| `extraParams` | `Map<String, Any>` | 空 | 会话扩展参数 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enablePartialResult` | `Boolean` | `true` | 是否回调中间结果 |
| `maxAudioDuration` | `Number` | `20000` | 单会话最长音频毫秒数，最小 20000 |
| `vadEnd` | `Number/String` | `800` | VAD 尾静音阈值毫秒，范围 500 到 10000 |
| `enableVoiceprintVerification` | `Boolean` | `false` | 是否在 final 阶段返回目标声纹相似度 |
| `enableSpeakerVad` | `Boolean/String/Number` | `false` | 是否启用目标说话人离场提前 endpoint |
| `voiceprintIds` | `List<String>` | 空 | 声纹 ID 列表 |
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
    fun onComplete(sessionId: String, eventMessage: String)
    fun onError(sessionId: String, errorCode: Int, errorMessage: String)
}
```

| 回调 | 说明 |
|------|------|
| `onStart` | 会话启动成功 |
| `onEvent` | 语音端点、声纹 VAD 状态等事件 |
| `onResult` | 识别结果，包含 partial 与 final |
| `onComplete` | 主动 `finish` 后识别完整结束 |
| `onError` | 发生错误 |

`SpeechRecognitionResult`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `isFinal` | `Boolean` | 是否最终结果 |
| `isLast` | `Boolean` | 是否本次 `finish` 对应的最后结果 |
| `result` | `String` | 识别文本；final 为警务增强后文本 |
| `beginTime` | `Int?` | 起始时间毫秒，可能为空 |
| `endTime` | `Int?` | 结束时间毫秒，可能为空 |
| `speakerSimilarity` | `Float?` | final 且启用声纹能力时返回 |

事件码：

| 事件码 | 名称 | 说明 |
|--------|------|------|
| `1` | `SPEECH_BEGIN` | 检测到语音开始 |
| `3` | `SPEECH_END` | 检测到语音结束 |
| `20` | `SPEAKER_VAD_CHANGED` | 目标说话人 VAD 开关变化 |
| `21` | `SPEAKER_VAD_DEBUG` | 目标说话人 VAD 调试信息 |
| `22` | `SPEAKER_VAD_REJECTED` | 目标说话人 VAD 拒绝当前 final |

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

SDK 不在内部丢弃非目标说话人结果；final 会返回增强文本与 `speakerSimilarity`，是否接受由客户业务侧判定。启用 `enableSpeakerVad` 时，SDK 可在目标说话人离场后提前切句。

## 7. 授权

正式 App 授权文件名默认为 `amphion-license.lic`。本次正式授权面向：

| 项 | 值 |
|----|----|
| 应用包名 | `com.tdtech.tiassistant` |
| 授权能力 | `ASR,TTS` |
| 绑定方式 | 包名、Release 签名证书 SHA-256、设备 SN 白名单、到期时间 |

设备绑定哈希规则为 `SHA-256(normalizedSn + deviceIdSaltId)`，其中 `normalizedSn` 为 trim 后转大写。默认 `deviceIdSaltId` 为 `DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`。

Demo APK 内置 license 仅用于体验：包名为 `com.amphion.dingqiao.demo`，授权能力为 `ASR`，不绑定 SN，不可用于正式宿主。

## 8. 错误码

| 错误码 | 名称 | 说明 |
|--------|------|------|
| `1002200001` | `CREATE_ENGINE_FAILED` | 创建引擎失败 |
| `1002200002` | `START_LISTENING_FAILED` | 启动识别失败 |
| `1002200003` | `MAX_AUDIO_DURATION` | 超过单会话最长音频 |
| `1002200004` | `FINISH_FAILED` | 结束识别失败 |
| `1002200005` | `CANCEL_FAILED` | 取消识别失败 |
| `1002200006` | `ENGINE_BUSY` | 引擎忙 |
| `1002200007` | `ENGINE_NOT_INITIALIZED` | SDK 未初始化 |
| `1002200008` | `ENGINE_DESTROYED` | 引擎已释放 |
| `1002200009` | `INTERNAL_ERROR` | 内部错误 |
| `1002200010` | `NOT_LISTENING` | 未处于识别中 |
| `1002200011` | `RECOGNITION_ERROR` | 识别错误 |
| `1002200020` | `VOICEPRINT_REGISTER_FAILED` | 声纹注册失败 |
| `1002200021` | `VOICEPRINT_SAMPLE_COUNT` | 声纹样本数量不足 |
| `1002200022` | `VOICEPRINT_SAMPLE_DURATION` | 声纹样本时长不符合要求 |
| `1002200024` | `VOICEPRINT_NOT_FOUND` | 声纹不存在 |
| `1002200030` | `LICENSE_FILE_UNREADABLE` | 授权文件不可读 |
| `1002200031` | `LICENSE_INVALID` | 授权无效 |
| `1002200032` | `LICENSE_EXPIRED` | 授权已过期 |
| `1002200033` | `LICENSE_DEVICE_MISMATCH` | 包名、签名或设备不匹配 |
| `1002200034` | `LICENSE_NOT_SET` | 未设置授权 |
| `1002200035` | `LICENSE_ACTIVATION_FAILED` | 授权激活失败 |

