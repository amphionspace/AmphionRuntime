# Lits TTS Android SDK API

本文记录 Android AAR 当前公开 API。SDK-only 交付以本文、`INTEGRATION.md` 与交付包根目录 `README.md` 为准；仓库根目录研发文档不属于交付依赖。

## TextToSpeechSdk

```kotlin
object TextToSpeechSdk {
    fun init(context: Context, options: TtsLicenseOptions = TtsLicenseOptions())
    fun setLicense(licensePath: String, callback: Callback<LicenseActivationResult>)
    fun licenseStatus(): TtsLicenseStatus
    fun getLicenseInfo(): LicenseInfo
    fun deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String): String
    fun deviceLicenseFingerprint(context: Context): String
    fun setWorkPath(workPath: String)
    fun preloadFrontendAndTn()
    fun createEngine(params: CreateEngineParams): TextToSpeechEngine
    fun createEngine(params: CreateEngineParams, callback: Callback<TextToSpeechEngine>)
    fun listVoices(params: VoiceQuery): List<VoiceInfo>
    fun listVoices(params: VoiceQuery, callback: Callback<List<VoiceInfo>>)
}
```

说明：

- callback 版 `createEngine` / `listVoices` 为异步接口，Android 环境下回调派回主线程。
- 同步版 `createEngine` 会加载模型，调用方负责选择线程。
- `init` 同步校验授权；`setLicense` 异步读取文件并使用系统 SN 校验，成功进入 `onSuccess`，失败进入 `onError`。需要自定义 SN 来源时使用 `init` 的 `deviceIdProvider`。
- `licenseStatus` 可以在初始化前查询；`getLicenseInfo` 在尚未设置授权时抛 `LICENSE_NOT_SET`。
- `preloadFrontendAndTn` 可在授权和 `setWorkPath` 之后、创建引擎之前调用，只准备前端/TN，不加载 ONNX 模型。
- `deviceLicenseFingerprint(context)` 是旧版包名 + Android ID 算法。当前 SN 白名单应使用带 `deviceSerial` 和 `deviceIdSaltId` 的重载。

## TextToSpeechEngine

```kotlin
interface TextToSpeechEngine {
    fun setListener(listener: SpeakListener)
    fun speak(text: String, params: SpeakParams)
    fun stop()
    fun isBusy(): Boolean
    fun shutdown()
}
```

## Callback

```kotlin
interface Callback<T> {
    fun onSuccess(result: T)
    fun onError(errorCode: Int, errorMessage: String)
}
```

## SpeakListener

```kotlin
interface SpeakListener {
    fun onStart(requestId: String, response: StartResponse)
    fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse)
    fun onPlaybackStart(requestId: String, elapsedMs: Long)
    fun onComplete(requestId: String, response: CompleteResponse)
    fun onStop(requestId: String, response: StopResponse)
    fun onError(requestId: String, errorCode: Int, errorMessage: String)
}
```

所有 `SpeakListener` 事件由 SDK 内部异步派发，不保证在主线程；这些方法都有默认空实现，可以只覆盖需要的回调。`onPlaybackStart` 表示开始向 AudioTrack 写入 PCM，不代表扬声器已发声。

## 数据结构

### CreateEngineParams

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `language` | `String` | 必填 | `zh-en` 或 `en-US`；控制文本前端语种规则 |
| `mode` | `RunMode` | 必填 | 当前仅支持 `OFFLINE` |
| `voiceId` | `String` | 必填 | 通过 `listVoices` 获取；代表 speaker 身份 |
| `locate` | `String` | `CN` | 区域信息 |
| `engineName` | `String?` | `null` | 引擎实例名称 |
| `extraParams` | `Map<String, Any?>` | `emptyMap()` | 预留扩展 |
| `modelLoadOnCreate` | `Boolean` | `true` | 当前仅支持 `true` |

### VoiceQuery

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `requestId` | `String` | 必填 | 请求唯一标识 |
| `mode` | `RunMode` | 必填 | 当前仅支持 `OFFLINE` |
| `language` | `String?` | `null` | 过滤语种 |
| `extraParams` | `Map<String, Any?>` | `emptyMap()` | 预留扩展 |

### VoiceInfo

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `language` | `String` | 当前条目对应的前端语种 |
| `voiceId` | `String` | 音色 / speaker ID |
| `gender` | `String` | `Male` 或 `Female` |
| `description` | `String?` | 描述 |

当前仅公开 `lits-female-02`（模型 speaker 1），支持 `zh-en` 和 `en-US`。不筛选语种时返回两条语言记录，但只有一个唯一音色；筛选语种时返回一条。`lits-female-01` 不再支持，创建引擎时返回 `VOICE_UNSUPPORTED`。

### SpeakParams

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `requestId` | `String` | 必填 | 同一 engine 内不可重复 |
| `speed` | `Float` | `1.0` | 有效范围 `[0.5, 2.0]`；有限越界值截到边界，非有限值回退 `1.0` |
| `volume` | `Float` | `1.0` | 范围 `[0.0, 2.0]` |
| `pitch` | `Float` | `1.0` | 接受范围 `[0.5, 2.0]`，但当前双重重采样未实现有效升降调；建议保持 `1.0` |
| `languageContext` | `String` | `zh-CN` | 支持 `zh-CN` / `en-US`，兼容旧值 `zh-en`；内部会把 `zh-CN` 归一到中英前端路径 |
| `audioType` | `String` | `pcm` | 当前仅支持 `pcm` |
| `playType` | `PlayType` | `SYNTHESIZE_AND_PLAY` | 合成模式 |
| `soundChannel` | `Int?` | `null` | Android `AudioManager.STREAM_*` |
| `queueMode` | `QueueMode` | `QUEUE` | 排队策略 |
| `extraParams` | `Map<String, Any?>` | `emptyMap()` | 扩展参数；新接入优先使用类型化字段 |
| `streamingConfig` | `TtsStreamingConfig?` | `null` | 当前请求的流式配置 |

### 流式分块参数

`SpeakParams.streamingConfig: TtsStreamingConfig?` 可设置 `chunkSize`、
`firstChunkSize` 和 `pcmQueueCapacity`。当前 IMF 模型默认 50 帧，
可通过 `chunkSize` 改成 100 等不小于 40 的帧数；仍使用逐步独立的 KV 缓存。
小于 40 的常规块受当前 ONNX 导出限制，不能使用。首块等分块覆盖值必须
与所选块大小一致，不支持块大小增长。留空使用模型默认值。
更改推理块大小可能改变首包延迟、内存和音质，数值执行正确不代表听感相同。

| 字段 | 默认行为 | 约束 |
| --- | --- | --- |
| `chunkSize` | 使用模型默认 50 帧 | 正数覆盖需 ≥40；零/负数视为未覆盖 |
| `firstChunkSize` | 与当前块大小一致 | 正数覆盖必须等于最终 `chunkSize`；零/负数视为未覆盖 |
| `pcmQueueCapacity` | 128 个 PCM 块 | 仅影响 SDK 内部播放缓冲；整数截到 1–256，不是毫秒，也不是请求队列长度 |

`streamingConfig` 中已设置的字段优先于同用途的 `extraParams`。新接入无需设置增长策略、流步数或历史窗口扩展参数；当前模型使用两步和逐步独立 KV 缓存。

### 回调响应

| 类型 | 字段 |
| --- | --- |
| `StartResponse` | `audioType`, `sampleRate`, `sampleBit`, `audioChannel`, `compressRate`, `isStreaming`, `dataPath`, `modelSource`, `modelInfo`, `loadProfileInfo`, `streamingChunkSize`, `pcmQueueCapacity` |
| `SynthesisResponse` | `sequence`, `audioType`, `isStreaming`, `chunkSource` |
| `CompleteResponse` | `type`, `message`, `firstPacketMs`, `synthesisMs`, `audioDurationMs`, `rtf`, `profilingInfo`, `playbackStartMs` |
| `StopResponse` | `type`, `message` |

`playbackStartMs` 为已知播放起点时延，未记录时为 `-1`。其他 `CompleteResponse` 性能字段只在 `type = SYNTHESIS_COMPLETE` 时有意义；未知值为 `-1` 或空字符串。`profilingInfo` 是调试文本，当前包含流式路径的 frontend、hidden encoder、decoder、vocoder、chunk 数和模型 chunk size 等分段耗时。

内部流式播放的合成线程与播放线程并行。`onPlaybackStart` 和 `SYNTHESIS_COMPLETE` 的先后不固定：短音频可能在播放预缓冲完成前已经合成完。成功播放必须从 `onStart` 开始，最终以 `PLAYBACK_COMPLETE` 结束；合成完成、播放开始、播放完成各回调一次。不要据这两个中间事件的相对顺序判断失败。


`StartResponse.loadProfileInfo` 是引擎创建时记录的加载分段耗时，当前包含 layout/model install、frontend preload、ORT session 创建总耗时，以及各 ONNX session 创建耗时。

## 枚举

| 枚举 | 值 |
| --- | --- |
| `RunMode` | `OFFLINE`, `ONLINE` |
| `PlayType` | `SYNTHESIZE_ONLY`, `SYNTHESIZE_AND_PLAY` |
| `QueueMode` | `QUEUE`, `PREEMPT` |
| `CompleteType` | `SYNTHESIS_COMPLETE`, `PLAYBACK_COMPLETE` |
| `StopType` | `STOP_ALL`, `STOP_PLAYBACK_ONLY` |

`ONLINE` 与 `STOP_PLAYBACK_ONLY` 是预留值，当前实现不承诺完整支持。

## 错误码

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `TEXT_LENGTH_INVALID` | `1002300001` | 文本为空或长度超出范围 |
| `LANGUAGE_UNSUPPORTED` | `1002300002` | 语种不支持 |
| `VOICE_UNSUPPORTED` | `1002300003` | 音色不支持 |
| `CREATE_ENGINE_FAILED` | `1002300005` | 创建引擎失败 |
| `ENGINE_LIMIT_REACHED` | `1002300006` | 引擎实例数达到上限 |
| `ENGINE_NOT_INITIALIZED` | `1002300007` | 引擎未初始化 |
| `ENGINE_DESTROYED` | `1002300008` | 引擎已销毁 |
| `INTERNAL_SERVICE_ERROR` | `1002300009` | 内部服务错误 |
| `QUEUE_FULL` | `1002300010` | 队列已满，当前未启用该限制 |
| `RUNTIME_EXCEPTION` | `1002300011` | 运行时异常 |

### 授权错误码

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `LICENSE_MISSING` | `1002300012` | 未提供或无法读取授权 |
| `LICENSE_MALFORMED` | `1002300013` | 授权格式非法 |
| `LICENSE_SIGNATURE_INVALID` | `1002300014` | 签名无效 |
| `LICENSE_APP_MISMATCH` | `1002300015` | license 显式绑定的包名不符 |
| `LICENSE_CERT_MISMATCH` | `1002300016` | license 显式绑定的签名证书不符 |
| `LICENSE_EXPIRED` | `1002300017` | 运行授权过期 |
| `LICENSE_DEVICE_MISMATCH` | `1002300018` | SN 不可用或不在名单内 |
| `LICENSE_SDK_MAJOR_MISMATCH` | `1002300019` | 授权兼容主版本不匹配 |
| `LICENSE_MAINTENANCE_EXPIRED` | `1002300020` | SDK 发布日期超出维护期 |
| `LICENSE_FEATURE_MISSING` | `1002300021` | 未授权 TTS |
| `LICENSE_NOT_SET` | `1002300034` | 设置授权前调用 getLicenseInfo |

### 授权数据

- `LicenseActivationResult`：`errorCode`、`errorMessage`、`remainingDays`、`authorizedFeatures`。
- `LicenseInfo`：`status`（0 有效、1 过期、3 其他无效状态；尚未初始化时接口直接抛异常）、`expireTime`（UTC 毫秒）、`remainingDays`、`authorizedFeatures`（小写能力名称）。无到期日时，日期/剩余天数为 `-1`。
- `TtsLicenseStatus`：`state`（`NOT_INITIALIZED` / `DEV_UNLICENSED` / `LICENSED` / `INVALID`）、`valid`、`errorCode` 及授权客户、时间、功能和设备数量信息。
- `TtsLicenseOptions`：`license`（授权全文，优先使用）、`licenseAssetName`（默认 `amphion-license.lic`）、`deviceIdProvider`（默认系统 SN）、`enforcement`（默认 `ENFORCE`）、`expiryGraceDays`（默认 0）、`deviceSha256`（旧格式兼容字段）。当前 SN 名单使用 `deviceIdProvider`。
- `ENFORCE` 在授权校验失败时阻止创建引擎；`PERMISSIVE` 只记录无效状态，供排障使用。本包公钥已注入，接入示例使用默认 `ENFORCE`。

## 语言与分块边界

`CreateEngineParams.language` 使用 `zh-en` 或 `en-US`。`SpeakParams.languageContext` 默认 `zh-CN`（等价 `zh-en`）；明确选择 `en-US` 时数字按英文读。
当前模型的常规分块正数覆盖值必须不小于 40 帧；例如 `chunkSize=100` 可用。短于 40 帧的句尾由 SDK 自动处理，不要求调用方补齐。
