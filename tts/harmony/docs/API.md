# API 说明

HAR 入口：

```text
sdk/Index.ets
```

当前对外暴露的核心接口如下。

## TextToSpeechSdk

```ts
class TextToSpeechSdk {
  static setWorkPath(workPath: string): void
  static createEngine(params: CreateEngineParams): TextToSpeechEngine
  static createEngine(params: CreateEngineParams, callback: Callback<TextToSpeechEngine>): void
  static createEngineAsync(params: CreateEngineParams, callback: Callback<TextToSpeechEngine>): void
  static listVoices(params: VoiceQuery): VoiceInfo[]
  static listVoices(params: VoiceQuery, callback: Callback<VoiceInfo[]>): void
  static listVoicesAsync(params: VoiceQuery, callback: Callback<VoiceInfo[]>): void
}
```

说明：

- `setWorkPath()` 不是必填；不传时，SDK 会把 HAR 内置模型自动解包到应用私有目录
- `setWorkPath()` 一旦要用，仍然必须在创建任何 engine 之前调用
- `extraParams.modelPackageDir` 优先级最高，适合显式接入外部模型目录
- 当前仅支持 `RunMode.OFFLINE`
- callback 版 `createEngine` / `listVoices` 为 Android 对齐接口；`createEngineAsync` / `listVoicesAsync` 保留为兼容别名
- ⚠️ **线程约定（重要）**：`createEngine` 会加载模型——首次还需把内置模型解包到工作目录、并构建 native ONNX 运行时（多个模型），**耗时数秒**。**callback / `*Async` 重载并不会把这项工作切到后台线程**（当前实现只是下一个微任务再执行，仍跑在**调用线程**上）。因此：
  - **请在非 UI 线程调用 `createEngine`，或在调用前先显示"加载中"状态**；在 UI 线程直接调用会造成首启卡顿（可能触发无响应）。
  - 建议在应用启动/闪屏阶段预先 `createEngine` 一次并持有 engine，之后 `speak()` 即时返回。
  - 该耗时是"模型加载"固有成本，与是否用 callback 无关；调度到哪个线程由集成方决定。

## TextToSpeechEngine

```ts
interface TextToSpeechEngine {
  setListener(listener: SpeakListener): void
  speak(text: string, params: SpeakParams): void
  stop(): void
  isBusy(): boolean
  shutdown(): void
}
```

说明：

- `setListener()` 必须先调用，再 `speak()`
- `shutdown()` 后当前实例不可再复用
- `stop()` 会停止排队任务和播放，但不能中断已经开始的单次 native ONNX 推理

## Callback

```ts
interface Callback<T> {
  onSuccess(result: T): void
  onError(errorCode: number, errorMessage: string): void
}
```

## SpeakListener

```ts
interface SpeakListener {
  onStart?(requestId: string, response: StartResponse): void
  onData?(requestId: string, audio: ArrayBuffer, response: SynthesisResponse): void
  onComplete?(requestId: string, response: CompleteResponse): void
  onStop?(requestId: string, response: StopResponse): void
  onError?(requestId: string, errorCode: number, errorMessage: string): void
}
```

事件语义：

- `onStart`: 本次请求开始，返回采样率和 PCM 规格
- `onData`: 仅在 `SYNTHESIZE_ONLY` 下按 chunk 回传 PCM
- `onComplete`:
  - `SYNTHESIS_COMPLETE`: 合成完成
  - `PLAYBACK_COMPLETE`: 播放完成
- `onStop`: 当前请求被显式停止
- `onError`: 参数错误、前端错误、模型加载失败或 ONNX 推理失败

## 数据结构

### CreateEngineParams

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `language` | `string` | `zh-en` 或 `en-US` |
| `mode` | `RunMode` | 当前仅支持 `OFFLINE` |
| `voiceId` | `string` | 当前支持 `lits-female-01`、`lits-female-02` |
| `locate` | `string?` | 区域信息，默认 `CN` |
| `engineName` | `string?` | 引擎名称，可选 |
| `extraParams.modelPackageDir` | `string?` | 完整模型包目录；传入后优先使用，不走内置模型解包 |
| `modelLoadOnCreate` | `boolean?` | 当前仅支持 `true` |

### VoiceQuery

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `requestId` | `string` | 请求唯一标识 |
| `mode` | `RunMode` | 当前仅支持 `OFFLINE` |
| `language` | `string?` | 可选语种过滤 |
| `extraParams` | `ExtraParams?` | 预留 |

### VoiceInfo

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `language` | `string` | `zh-en` 或 `en-US` |
| `voiceId` | `string` | 当前 speaker ID |
| `gender` | `string` | 当前固定为 `Female` |
| `description` | `string?` | 说明文本 |

### SpeakParams

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `requestId` | `string` | 必填 | 同一 engine 内不可重复 |
| `speed` | `number` | `1.0` | 范围 `[0.5, 2.0]` |
| `pitch` | `number` | `1.0` | 范围 `[0.5, 2.0]` |
| `volume` | `number` | `1.0` | 范围 `[0.0, 2.0]` |
| `languageContext` | `string` | `zh-CN` | 支持 `zh-CN` / `en-US`，兼容旧值 `zh-en`；内部会把 `zh-CN` 归一到中英前端路径 |
| `audioType` | `string` | `pcm` | 当前仅支持 `pcm` |
| `playType` | `PlayType` | `SYNTHESIZE_AND_PLAY` | 合成后是否内部播放 |
| `queueMode` | `QueueMode` | `QUEUE` | 排队或抢占 |
| `soundChannel` | `number?` | `undefined` | HarmonyOS `audio.StreamUsage` 枚举值；不传时默认 `STREAM_USAGE_MUSIC` |
| `extraParams` | `ExtraParams?` | 预留 |

## 模型目录解析规则

模型目录优先级如下：

1. `extraParams.modelPackageDir`
2. `setWorkPath()` 指向的目录
3. HAR 内置模型自动解包目录

如果 `extraParams.modelPackageDir` 为空，且设置了 `setWorkPath()`，SDK 会按下面顺序找 `manifest.json`：

1. `<workPath>/manifest.json`
2. `<workPath>/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/manifest.json`
3. `<workPath>/tts/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/manifest.json`

如果以上都没命中外部模型，SDK 会自动把 HAR 中的 `rawfile` 资源解包到：

```text
<application filesDir>/tts/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
```

如果调用过 `setWorkPath("/some/base")`，则内置模型默认解包到：

```text
/some/base/tts/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
```

显式传目录仍然是最可控的方式：

```ts
extraParams: {
  modelPackageDir: "/absolute/path/to/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0"
}
```

## 当前运行时行为

- 文本前端在 ArkTS 层完成
- acoustic 和 vocoder 在 `sdk/src/main/cpp/lits_tts_native.cpp` 中通过 OHOS native ONNX Runtime 执行
- 输出固定为 `16 kHz / 16-bit / mono PCM`
- `SYNTHESIZE_AND_PLAY` 会在合成后走 HarmonyOS `AudioRenderer`
- `soundChannel` 会映射到 HarmonyOS `AudioRenderer.rendererInfo.usage`
- `SYNTHESIZE_ONLY` 不内部播放，只通过 `onData` 回传 PCM
- `ONLINE`、`STOP_PLAYBACK_ONLY` 仍是预留值；当前实现不承诺完整支持
- `QUEUE_FULL` 错误码已保留，但当前未启用固定队列上限

## 错误码

当前延续 Android 侧错误码语义：

- `1002300001` `TEXT_LENGTH_INVALID`
- `1002300002` `LANGUAGE_UNSUPPORTED`
- `1002300003` `VOICE_UNSUPPORTED`
- `1002300005` `CREATE_ENGINE_FAILED`
- `1002300006` `ENGINE_LIMIT_REACHED`
- `1002300007` `ENGINE_NOT_INITIALIZED`
- `1002300008` `ENGINE_DESTROYED`
- `1002300009` `INTERNAL_SERVICE_ERROR`
- `1002300010` `QUEUE_FULL`（当前未启用固定队列上限）
- `1002300011` `RUNTIME_EXCEPTION`
