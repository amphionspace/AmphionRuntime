# 语音识别 SDK 接口

> 交付契约提示：本文件为 Android 集成说明。跨平台接口契约以《语音识别SDK接口-交付批注版.md》为准；该文档基于《语音识别SDK接口-20260622.md》（v1.1）基线，并在增补项旁批注。

本文描述鼎桥 Android 离线语音识别 SDK 的客户集成接口。SDK 入口包名为 `com.amphion.dingqiao`，核心入口为 `SpeechRecognizeSdk`。

## 1. 最小调用顺序

```kotlin
SpeechRecognizeSdk.init(applicationContext)
SpeechRecognizeSdk.setWorkPath(filesDir.resolve("dingqiao_asr").absolutePath)
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
| `SpeechRecognizeSdk.setLicense(licensePath: String, callback: LicenseActivationCallback)` | 校验并缓存授权，不启动 Runtime、不加载模型 |
| `SpeechRecognizeSdk.prepareRuntime(callback: PrepareRuntimeCallback)` | 准备 Runtime 并由 SDK 预加载默认中英模型；并发调用 single-flight |
| `SpeechRecognizeSdk.getLicenseInfo(): LicenseInfo` | 查询当前已激活授权信息 |
| `SpeechRecognizeSdk.createEngine(params: CreateEngineParams): SpeechRecognitionEngine` | 同步创建识别引擎 |
| `SpeechRecognizeSdk.createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback)` | 异步复用已准备模型并创建引擎；成功回调 `onSuccess` |
| `SpeechRecognizeSdk.unloadModel()` | 卸载内存模型，保留 Runtime 与授权 |
| `SpeechRecognizeSdk.unloadRuntime()` | 卸载 Runtime 和模型，保留已验证授权 |
| `SpeechRecognizeSdk.preloadVoiceprintModel(): Boolean` | 按需预装声纹模型；普通 ASR 不隐式加载 |
| `SpeechRecognizeSdk.registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult` | 注册本地声纹 |
| `SpeechRecognizeSdk.deleteVoiceprint(voiceprintId: String)` | 删除本地声纹 |
| `SpeechRecognizeSdk.deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String): String` | 计算设备 SN 授权白名单哈希 |

`setWorkPath` 指向的目录用于保存声纹 embedding，并承载 SDK 自动准备的声纹模型 `eres2net.onnx`。自 v0.2.7 起，声纹模型已内置在 `dingqiao-asr-v*.aar` 中，客户无需单独下发 `models/eres2net.onnx`。

中英 ASR 三图和标点以 Android ONNX Runtime 1.24.3 生成的 ORT 格式随 AAR
交付。首次创建完成后，同语言、兼容配置的模型由 Runtime 复用；调用
`unloadModel()` 后下一次创建重新冷加载。

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
| `language` | `String` | 无 | 当前 Android 交付包仅支持 `zh-CN`、`zh-en`、`zh_en` |
| `online` | `Int` | `1` | 当前仅支持离线模式 `DingqiaoOnlineMode.OFFLINE` |
| `extraParams` | `Map<String, Any>` | 空 | 扩展参数 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `locate` | `String` | `CN` | 兼容字段；当前仅支持中国区，不改变模型选择 |
| `recognizerMode` | `String` | `long` | 接受 `short`/`long`，当前均按长语音流式模式处理 |
| `sysGeneralLexicon` | `List<String>` | 空 | 系统热词；与警务域默认热词合并后用于解码 |

### StartParams

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sessionId` | `String` | 无 | 非空，只允许字母、数字、下划线、短横线 |
| `audioInfo` | `AudioInfo` | 无 | 音频格式 |
| `extraParams` | `Map<String, Any>` | 空 | 会话扩展参数 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `recognitionMode` | `Number/String` | `1` | 仅支持 `1`（外部写入音频流）；`0`（SDK 内录音）暂不支持 |
| `vadBegin` | `Number/String` | 未启用 | 首次检测到语音前的静音超时，范围 500 到 10000 ms；仅显式传入时启用 |
| `enablePartialResult` | `Boolean` | `true` | 是否回调中间结果 |
| `maxAudioDuration` | `Number/String` | 未启用 | 单会话最长音频毫秒数；仅显式传入正有限值时启用，上限 28800000；达到上限后正常自动结束 |
| `vadEnd` | `Number/String` | `800` | VAD 尾静音阈值毫秒，范围 500 到 10000 |
| `sessionGeneralLexicon` | `List<String>` | 空 | V1 暂不支持；传入不会作为会话热词生效 |
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

> 交付批注 VP-20260715-01（2026-07-15）：`speakerSimilarity` 是可选值。有效语音短于 `TargetSpeakerConfig.minSegSec`（默认 1.5 秒）时无法可靠打分，SDK 保留识别结果但省略该字段；调用方不得把字段缺失当作会话结束或识别失败。

严格有效语音优先用于 `speakerSimilarity`。若严格样本不足，但 ASR 已产生非空 text/token，且本句实际 PCM 已达到 `minSegSec`，SDK 回退到本句真实 PCM 打分；不会填充假分数、复制上一句分数或补静音。非 last 的 token-only native endpoint 不会形成公开 final，其 PCM 会保留到下一条公开结果。

事件码：

| 事件码 | 名称 | 说明 |
|--------|------|------|
| `1` | `SPEECH_BEGIN` | 检测到语音开始 |
| `3` | `SPEECH_END` | 检测到语音结束 |
| `20` | `SPEAKER_VAD_CHANGED` | 目标说话人 VAD 开关变化 |
| `21` | `SPEAKER_VAD_DEBUG` | 目标说话人 VAD 调试信息 |
| `22` | `SPEAKER_VAD_REJECTED` | 目标说话人 VAD 拒绝当前 final |

`vadBegin` 按实际写入并由 VAD 处理的 PCM 时长计算；只调用 `startListening` 而不写入音频不会计时。达到阈值且始终未检测到语音时，SDK 回调空的 `onResult(isFinal=true,isLast=true)`，随后回调 `onComplete`，不回调 `SPEECH_BEGIN`、`SPEECH_END` 或错误。一旦检测到首个真实起音，本会话不再触发 `vadBegin`，后续停顿由 `vadEnd` 处理。该行为不依赖 `enablePartialResult`。

传入可用的 `voiceprintIds` 时，即使初始声纹开关为关闭，SDK 也会为 `onStart` 内同步调用 `setSpeakerVadEnabled(true)` 保留最多一次 `minSegSec` 确认窗。纯静音和稳态高能非语音仍会有界结束。

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

SDK 不在内部丢弃非目标说话人结果；达到有效语音门槛的 final 会返回增强文本与 `speakerSimilarity`，是否接受由客户业务侧判定。未达到门槛的 final 仍返回识别结果，但省略相似度。启用 `enableSpeakerVad` 时，SDK 可在目标说话人离场后提前切句。

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
