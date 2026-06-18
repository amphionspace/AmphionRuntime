# Lits TTS Android SDK API

本文记录 Android AAR 当前公开 API。对外接口说明以本文和 `INTEGRATION.md` 为准；源码仓库中的构建说明用于协作者从源码构建 AAR，不属于运行时接口定义。

## TextToSpeechSdk

```kotlin
object TextToSpeechSdk {
    fun setWorkPath(workPath: String)
    fun createEngine(params: CreateEngineParams): TextToSpeechEngine
    fun createEngine(params: CreateEngineParams, callback: Callback<TextToSpeechEngine>)
    fun listVoices(params: VoiceQuery): List<VoiceInfo>
    fun listVoices(params: VoiceQuery, callback: Callback<List<VoiceInfo>>)
}
```

说明：

- callback 版 `createEngine` / `listVoices` 为异步接口，Android 环境下回调派回主线程。
- 同步版 `createEngine` 会加载模型，调用方负责选择线程。

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
    fun onComplete(requestId: String, response: CompleteResponse)
    fun onStop(requestId: String, response: StopResponse)
    fun onError(requestId: String, errorCode: Int, errorMessage: String)
}
```

所有 `SpeakListener` 事件由 SDK 内部异步派发。

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

同一个 `voiceId` 可能对应多条 `VoiceInfo` 记录，仅 `language` 不同，表示同一 speaker 支持多种前端语种。

### SpeakParams

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `requestId` | `String` | 必填 | 同一 engine 内不可重复 |
| `speed` | `Float` | `1.0` | 范围 `[0.5, 2.0]` |
| `volume` | `Float` | `1.0` | 范围 `[0.0, 2.0]` |
| `pitch` | `Float` | `1.0` | 范围 `[0.5, 2.0]` |
| `languageContext` | `String` | `zh-en` | `zh-en` 或 `en-US`；控制数字等局部读法上下文 |
| `audioType` | `String` | `pcm` | 当前仅支持 `pcm` |
| `playType` | `PlayType` | `SYNTHESIZE_AND_PLAY` | 合成模式 |
| `soundChannel` | `Int?` | `null` | Android `AudioManager.STREAM_*` |
| `queueMode` | `QueueMode` | `QUEUE` | 排队策略 |
| `extraParams` | `Map<String, Any?>` | `emptyMap()` | 预留扩展 |

### 回调响应

| 类型 | 字段 |
| --- | --- |
| `StartResponse` | `audioType`, `sampleRate`, `sampleBit`, `audioChannel`, `compressRate` |
| `SynthesisResponse` | `sequence`, `audioType` |
| `CompleteResponse` | `type`, `message` |
| `StopResponse` | `type`, `message` |

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
