# 语音识别 SDK 接口（HarmonyOS 交付版）

> 本文件描述 Amphion HarmonyOS 离线语音识别 SDK 的客户集成接口。跨平台共同参数以
> `shared/api-spec/dingqiao-asr-parameters.json` 为机器可读单一来源：Android/HarmonyOS
> 使用相同字段名、取值、默认值和优先级。`enableTargetSpeakerEnhancement` 是 HarmonyOS
> 预留扩展，不属于共同客户配置，当前未包含获准模型的交付中不得启用。

| 文档项 | 值 |
| --- | --- |
| 文档版本 | v1.9（SDK 0.3.12：端侧角色分离与冷启动采音连续性） |
| 更新日期 | 2026-08-28 |
| SDK 依赖 | `amphion_dingqiao` |

SDK 依赖名为 `amphion_dingqiao`，核心入口为 `SpeechRecognizeSdk`。本版包含 License、Runtime、Model 三层生命周期控制，以及内置声纹模型的按需加载策略，便于宿主控制模型内存和识别启动时延。

## 1. 最小调用顺序

```ts
import {
  AudioInfo,
  AmphionLogLevel,
  CreateEngineParams,
  LicenseDeviceIdProvider,
  SpeechRecognitionEngine,
  SpeechRecognizeSdk,
  StartParams
} from 'amphion_dingqiao';

class HostDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    return readStableDeviceSnFromHost();
  }
}

SpeechRecognizeSdk.init(context, new HostDeviceIdProvider());
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/dingqiao_asr`);
SpeechRecognizeSdk.setLogLevel(AmphionLogLevel.INFO); // 可选；需在 prepareRuntime 前设置

let engine: SpeechRecognitionEngine | undefined;
SpeechRecognizeSdk.setLicense(licensePath, {
  onResult: () => {
    // setLicense 只校验并缓存授权，不拉起 Runtime 或加载模型。
    SpeechRecognizeSdk.prepareRuntime({
      onReady: () => {
        SpeechRecognizeSdk.createEngineAsync(new CreateEngineParams(), {
          onSuccess: (createdEngine) => {
            engine = createdEngine;
            createdEngine.setListener(listener);

            const start = new StartParams();
            start.sessionId = 'session-1';
            start.audioInfo = new AudioInfo();
            createdEngine.startListening(start);
            createdEngine.writeAudio(start.sessionId, pcmFrame640Bytes);
            createdEngine.finish(start.sessionId);
          },
          onError: (errorCode, message) => {}
        });
      },
      onError: (errorCode, message) => {}
    });
  },
  onError: (errorCode, message) => {}
});
```

`writeAudio` 输入为 16 kHz、16 bit、单声道 PCM，每帧 640 字节，对应 20 ms 音频。调用 `finish` 表示本次会话音频输入结束，SDK 输出最后一次 final 结果并回调 `onComplete`。

不再使用模型时，先结束会话并释放引擎，再按需要卸载模型或整个 Runtime：

```ts
engine?.shutdown();
engine = undefined;

SpeechRecognizeSdk.unloadModel();   // 保留 Runtime 与已验证授权
// 或：
SpeechRecognizeSdk.unloadRuntime(); // 模型跟随释放，保留已验证授权
```

## 2. 全局接口

| 接口 | 说明 |
| --- | --- |
| `SpeechRecognizeSdk.init(context: Context, deviceIdProvider?: LicenseDeviceIdProvider)` | 初始化 SDK；本交付的无设备绑定授权无需传 `deviceIdProvider` |
| `SpeechRecognizeSdk.setWorkPath(path: string)` | 设置可读写工作目录，必须在创建引擎或注册声纹前调用 |
| `SpeechRecognizeSdk.setLogLevel(logLevel: AmphionLogLevel)` | 设置 Runtime 日志等级；默认 `WARN`，查看初始化版本日志时在 `prepareRuntime` 前设为 `INFO` |
| `SpeechRecognizeSdk.getWorkPath(): string` | 查询当前工作目录 |
| `SpeechRecognizeSdk.setLicense(licensePath: string, callback: LicenseActivationCallback)` | 离线校验并缓存正式授权；不拉起 Runtime、不加载模型 |
| `SpeechRecognizeSdk.getLicenseInfo(): LicenseInfo` | 查询当前已激活授权信息 |
| `SpeechRecognizeSdk.prepareRuntime(callback: PrepareRuntimeCallback)` | 准备 Runtime 并预加载默认中英识别模型；并发调用 single-flight |
| `SpeechRecognizeSdk.createEngine(params: CreateEngineParams): SpeechRecognitionEngine` | 同步创建引擎；默认配置复用已准备模型，其他配置按需加载 |
| `SpeechRecognizeSdk.createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback)` | 异步复用或按需加载模型并创建引擎 |
| `SpeechRecognizeSdk.unloadModel(): void` | 卸载模型，保留 Runtime 和已验证授权 |
| `SpeechRecognizeSdk.unloadRuntime(): void` | 卸载 SDK 管理的 Runtime 状态；模型跟随释放，已验证授权保留 |
| `SpeechRecognizeSdk.registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult` | 注册本地声纹 |
| `SpeechRecognizeSdk.deleteVoiceprint(voiceprintId: string): boolean` | 删除本地声纹 |
| `SpeechRecognizeSdk.preloadVoiceprintModel(): boolean` | 同步预加载并预热声纹模型；应在非 UI 关键路径调用 |

声纹模型 `eres2net.onnx` 已内置在 `amphion_dingqiao.har`，宿主无需单独分发、导入或复制。`setWorkPath` 指向可读写目录，用于保存已注册的声纹 embedding；SDK 不会把 HAR 内模型复制到该目录。

日志等级设为 `INFO` 后，首次 `prepareRuntime` 初始化成功会在 Harmony hilog 输出：

```text
[AmphionRuntime] AmphionRuntime Harmony init done, version=0.3.12, license=LICENSED
```

可通过 DevEco Studio Log 或 `hdc shell hilog | grep "AmphionRuntime Harmony init done"` 查看。

## 3. 生命周期控制

### 3.1 三层状态

| 层级 | 加载接口 | 卸载接口 | 卸载后保留 |
| --- | --- | --- | --- |
| License | `setLicense()` | 重新设置授权 | 成功授权保存在当前进程内 |
| Runtime / 默认 ASR 模型 | `prepareRuntime()` | `unloadRuntime()` | 已验证授权 |
| 其他 ASR 配置 / 声纹模型 | ASR：`createEngineAsync()` / `createEngine()`；声纹：注册、显式预加载或声纹会话按需加载 | `unloadModel()` | Runtime、已验证授权、HAR 内模型和已注册声纹 embedding |

完整状态流转：

```text
init
  → setLicense 成功
  → prepareRuntime.onReady
  → createEngineAsync.onSuccess / createEngine 返回
  → startListening / writeAudio / finish
  → engine.shutdown
  → unloadModel 或 unloadRuntime
```

### 3.2 `prepareRuntime()`

```ts
interface PrepareRuntimeCallback {
  onReady(): void;
  onError(errorCode: number, message: string): void;
}
```

- 调用前必须先完成 `init()`，且 `setLicense()` 已成功。
- 接口幂等：Runtime 与默认中英模型均已就绪时直接回调 `onReady()`。
- 并发调用为 single-flight：多个调用方共享同一次准备过程，并分别收到结果。
- 本阶段完成授权状态复核、Runtime 状态准备和默认 `zh-CN` 配置的中英 ASR/标点模型预加载；
  不创建业务引擎或识别 Session，也不加载声纹模型。
- `unloadRuntime()` 后再次调用时，会重新校验保留的授权；授权已过期或失效时回调相应 License 错误。

### 3.3 `createEngineAsync()` / `createEngine()`

```ts
interface CreateEngineCallback {
  onSuccess(engine: SpeechRecognitionEngine): void;
  onError(errorCode: number, message: string): void;
}
```

- 必须在 `prepareRuntime().onReady` 后调用。
- 默认 `zh-CN` 配置复用 `prepareRuntime()` 已准备的模型；其他语言或配置未加载时，创建引擎会按需加载模型。
- 同语言、同配置模型已加载时直接复用模型，只创建新的引擎对象；会话对象在 `startListening()` 时创建。
- `createEngine()` 在冷加载时会阻塞调用线程；客户业务优先使用 `createEngineAsync()`，不得在 UI 关键路径同步冷加载。
- 创建识别引擎只加载 ASR 相关模型，不会因为 HAR 内置声纹资源而加载声纹 extractor。声纹 extractor 在注册、显式预加载或声纹会话中另行按需加载。

### 3.4 `unloadModel()`

- 调用前应结束或取消所有会话，并对仍持有的 engine 调用 `shutdown()`。
- 调用后已有 engine 不应继续使用；下次识别需重新调用 `createEngineAsync()` 或 `createEngine()`。
- Runtime 与已验证授权保留，无需重新 `setLicense()` 或 `prepareRuntime()`。
- ASR 模型、标点模型、VAD 和内存声纹 extractor 都在本层释放；HAR 内置模型文件及 `{workPath}/voiceprints/` 下的 embedding 不会删除。
- 接口返回表示 SDK 已释放模型持有关系；操作系统回收物理页可能延后，进程 RSS 不保证在返回瞬间下降到最终稳定值。

### 3.5 `unloadRuntime()`

- 若模型仍已加载，模型会跟随 Runtime 一并释放。
- 已验证授权保留。后续调用顺序为 `prepareRuntime()` → `createEngineAsync()` / `createEngine()`，无需再次 `setLicense()`。
- 调用后已有 engine 不应继续使用。
- 正常调用方仍应先结束或取消 session 并 `shutdown()`。若释放请求与 session 尾部 native 异步工作重叠，SDK 会阻止新 session，并把模型和 Runtime 的实际释放延后到 stream 安全关闭；此时 `prepareRuntime()` 会返回 Runtime 正在释放，调用方应在原 session 的 `onComplete` 后重试。
- Runtime 卸载是 SDK 管理状态和资源的生命周期控制；应用进程已经映射的 native `.so` 由操作系统管理，接口不承诺在进程存活期间物理卸载动态库映射。

### 3.6 重新设置授权

新的 `setLicense()` 成功后会替换旧授权，并使旧 Runtime 和模型状态失效。若旧 session 尚在排空，`setLicense()` 的成功回调会等待其 stream 安全关闭及旧 Runtime 释放。成功回调后必须重新调用 `prepareRuntime()`，收到 `onReady()` 后再创建引擎。新的授权校验失败时，已生效的旧授权与正在使用的 Runtime 不被失败请求覆盖。

## 4. 引擎接口

| 接口 | 说明 |
| --- | --- |
| `setListener(listener: RecognitionListener)` | 设置识别回调 |
| `startListening(params: StartParams)` | 开始一次识别会话 |
| `writeAudio(sessionId: string, audio: ArrayBuffer)` | 写入一帧 640 字节 PCM 音频 |
| `finish(sessionId: string)` | 结束本次音频输入并等待 final/complete 回调 |
| `cancel(sessionId: string)` | 取消本次识别，不再输出 final |
| `isBusy(): boolean` | 查询当前引擎是否有进行中的识别会话 |
| `shutdown(): void` | 释放引擎对象 |
| `setSpeakerVadEnabled(enabled: boolean)` | 运行时启用或关闭目标说话人 VAD |

一个 `SpeechRecognitionEngine` 同时只处理一个活跃会话。`startListening` 成功后才能写入音频；`finish` 或 `cancel` 后如需继续识别，请重新调用 `startListening` 创建新会话。

`finish(sessionId)` 被接受后，`isBusy()` 会保持 `true`，直到唯一的 last final 和随后的 `onComplete`
完成。调用方应以 `onComplete` 作为可安全释放或复用的边界。为兼容旧宿主，若在该排空窗口立即调用
`shutdown()`，SDK 会延迟内部资源释放至 final/complete 已送达；但在收到 `onComplete` 前仍不得调用
`unloadModel()` 或 `unloadRuntime()`。在 `SPEECH_END` 回调内同步调用 `finish()` 时，当前带文本
endpoint final 会直接成为本 session 的 `isLast=true` 结果，不再追加空 terminal final。

`onStart(sessionId)` 是该 session 已可调用的边界。宿主可以在 `onStart` 回调调用栈内同步冲刷此前缓存的 640 字节 PCM 帧，也可以立即 `finish` 或 `cancel`；SDK 不得在成功回调后返回 `NOT_LISTENING`。在收到 `onStart` 之前不要写入音频。

运行时调用 `setSpeakerVadEnabled(true)` 时，本次会话的 `StartParams.extraParams` 必须已经提供有效的 `voiceprintIds`，即使会话启动时 `enableSpeakerVad=false`。冷态启用 Speaker VAD 会在后台加载声纹 extractor；调用立即返回，模型就绪前保持 fail-open。关闭操作不加载模型。

## 5. 参数对象

### 5.1 `AudioInfo`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `audioType` | `string` | `pcm` | 仅支持 PCM |
| `sampleRate` | `number` | `16000` | 仅支持 16000 Hz |
| `sampleBit` | `number` | `16` | 仅支持 16 bit |
| `soundChannel` | `number` | `1` | 仅支持单声道 |

### 5.2 `CreateEngineParams`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `language` | `string` | `zh-CN` | 支持 `zh-CN`、`zh-en`、`zh_en`、`zh-yue`、`zh_yue` |
| `online` | `number` | `1` | 当前仅支持离线模式 `DingqiaoOnlineMode.OFFLINE` |
| `extraParams` | `Record<string, Object>` | 空 | 扩展参数 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `locate` | `string` | `CN` | 兼容字段；当前仅支持中国区，不改变模型选择 |
| `recognizerMode` | `string` | `short` | `short` 保持旧版有最大单句时长的分段识别；`long` 为会议/持续转写，不做周期性 Rule3 硬切，仅在内部压缩已稳定解码前缀且不产生回调 |
| `sysGeneralLexicon` | `string[]` | 空 | 调用方热词，用于解码 |
| `disablePrepack` | `boolean/number/string` | `true` | 默认跳过 ORT INT8 权重 prepack，降低冷加载时间和峰值内存；设为 `false` 恢复吞吐优先模式 |

SDK 会自动进行保守的 WebRTC AGC2 输入电平归一化，调用方无需配置开关。该处理不会改善低 SNR 或已削波音频，调用方不要再叠加固定软件增益。

### 5.3 `StartParams`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `sessionId` | `string` | 空 | 非空，只允许字母、数字、下划线、短横线 |
| `audioInfo` | `AudioInfo` | 默认对象 | 音频格式 |
| `extraParams` | `Record<string, Object>` | 空 | 会话扩展参数 |
| `speakerDiarization` | `SpeakerDiarizationConfig?` | `undefined` | 不设置时关闭角色分离；设置配置对象时开启 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `recognitionMode` | `number/string` | `1` | 仅支持 `1`（外部写入音频流）；`0`（SDK 内录音）暂不支持 |
| `recognizerMode` | `string` | engine 配置；否则普通调用为 `short`、continuous 为 `long` | 会话级覆盖：`short` 使用 `endpointMaxUtteranceMs`；`long` 只按自然静音或 `finish` 公开分段，内部 stable-prefix 压缩不产生 endpoint/final。显式值优先，长转写和会议场景仍建议显式设置 `long` |
| `vadBegin` | `number/string` | 未启用 | 首次检测到语音前的静音超时，范围 500 到 10000 ms；仅显式传入时启用 |
| `enablePartialResult` | `boolean` | `true` | 是否回调中间结果；启用 Speaker VAD 后仍遵循该参数。partial 属于推测结果，可能包含随后从 final 中移除的非目标说话人文本；目标说话人边界保证仅适用于 final |
| `enablePoliceEnhancement` | `boolean` | `true` | 是否对 final 文本执行警务术语、车牌和派出所归一化；`false` 返回原始 ASR 文本 |
| `maxAudioDuration` | `number/string` | 未启用 | 单会话最长音频毫秒数；显式正有限值按调用值生效，上限 28800000；达到上限后正常自动结束，非正数或非法值按未启用处理 |
| `enableContinuousRecognition` | `boolean` | `false` | 设为 `true` 时保持同一个模型会话连续识别，并禁用 `maxAudioDuration` 自动结束；调用方必须最终显式调用 `finish(sessionId)`。未显式传 `recognizerMode` 时同时使用 `long`，显式 short/long 优先；仅布尔值 `true` 生效 |
| `endpointMaxUtteranceMs` | `number/string` | `20000` | 仅 `recognizerMode=short` 生效的单句强制 final 时长；不会结束 session。long 模式忽略该参数 |
| `vadEnd` | `number/string` | `800` | VAD 尾静音阈值毫秒，范围 500 到 10000 |
| `sessionGeneralLexicon` | `string[]` | 空 | V1 暂不支持；传入不会作为会话热词生效 |
| `enableVoiceprintVerification` | `boolean` | `false` | 是否在 final 阶段返回目标声纹相似度 |
| `enableSpeakerVad` | `boolean` | `false` | 是否启用目标说话人离场提前 endpoint；冷态所需模型在后台加载，就绪前保持 fail-open；仅处理先后说话，不提供重叠语音分离 |
| `enableTargetSpeakerEnhancement` | `boolean` | `false` | 是否在 ASR 前启用目标说话人增强；必须同时启用 Speaker VAD 并提供有效声纹 ID；仅在已包含获准商用模型的设备包中可用 |
| `voiceprintIds` | `string[]` | 空 | 声纹 ID 列表；启用声纹校验或 Speaker VAD 时必填 |
| `speakerVadThreshold` | `number/string` | `0.35` | 目标说话人 VAD 阈值 |
| `speakerVadWindowMs` | `number/string` | `1500` | 目标说话人 VAD 窗长 |
| `speakerVadHopMs` | `number/string` | `500` | 目标说话人 VAD 步长 |
| `speakerVadConsecutiveBelow` | `number/string` | `2` | 连续低于阈值多少次触发 endpoint |

### 5.4 Speaker Diarization

Speaker Diarization 是通用的匿名说话人分离能力，不限定会议业务。配置对象存在即开启，
不再使用 `enableSpeakerDiarization`、`maxSpeakerCount`、`expectedActiveSpeakerCount` 或
`speakerDiarizationProcessEntry` 等 `extraParams` 字符串参数。

```ts
import { SpeakerDiarizationConfig, StartParams } from 'amphion_dingqiao';

const start = new StartParams();
start.sessionId = 'session-1';

const diarization = new SpeakerDiarizationConfig();
diarization.maxSpeakers = 4;
start.speakerDiarization = diarization;

engine.startListening(start);
```

| `SpeakerDiarizationConfig` 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `maxSpeakers` | `number` | `4` | 稳定 speaker 索引的硬上限；V1 只接受整数 `1..4`，非法值使本次 `startListening` 失败，不会静默裁剪 |

SDK 自动估计实际发言人数，不接收参会名单人数或 hard K。证据不足、能力未开启、
尚未完成分配或超出上限时，对外统一返回 `speakerIndex=-1`；分配成功时返回
`0..(maxSpeakers-1)`。该索引仅在当前 session 内稳定，业务显示“说话人 1”时需使用
`speakerIndex + 1`。

角色分离完全在 SDK 内端侧执行。`pyannote-segmentation-3.0.onnx` 与 `eres2net.onnx` 已内置在
`amphion_dingqiao.har`，宿主无需配置地址、认证、模型路径、网络权限或 ChildProcess 入口。
PCM 写入应用沙箱的 10 秒分块临时文件，处理完成且不再被推理任务引用后回收。
SDK 按 10 秒推理窗口、2.5 秒 hop 串行执行本地 segmentation 和 embedding。
分人结果以 120 秒为目标窗口，在其后的第一个 ASR endpoint 及所需分人推理完成后校准并发布。
跨窗长句等待原句结束，不强行分句。120 秒是工程默认值，不是准确率最优或固定延迟保证。
窗口发布后，其中全部身份（包括 `-1`）永久冻结。整场保留匿名编号及代表声纹；结束仅完成尾批，
不再对历史全文或整场 embedding 重新聚类。

模型加载、端侧推理、存储或单窗超时会保留 ASR，并通过分窗及终结
`onSpeakerDiarizationResult` 返回明确的 `degradedReason`。产品发布门禁必须把降级视为角色分离
失败，不能只检查 `onComplete`。

## 6. 回调

```ts
interface RecognitionListener {
  onStart?(sessionId: string, eventMessage?: string): void;
  onEvent?(sessionId: string, eventCode: number, message: string): void;
  onResult?(sessionId: string, result: SpeechRecognitionResult): void;
  onSpeakerDiarizationUpdate?(sessionId: string, update: SpeakerDiarizationUpdate): void;
  onSpeakerDiarizationResult?(sessionId: string, result: SpeakerDiarizationResult): void;
  onComplete?(sessionId: string, eventMessage?: string): void;
  onError?(sessionId: string, errorCode: number, message: string): void;
}
```

| 回调 | 说明 |
| --- | --- |
| `onStart` | 会话已启动且可立即调用该 session 的 `writeAudio`、`finish`、`cancel` |
| `onEvent` | 语音端点、声纹 VAD 状态等事件 |
| `onResult` | 识别结果，包含 partial 与 final |
| `onSpeakerDiarizationUpdate` | 按 `utteranceId + revision` 增量修订说话人归属；只更新 speaker 信息，不修改 ASR 文本 |
| `onSpeakerDiarizationResult` | 返回本窗口定稿的 utterance 和 speaker timeline；每场多次，只有末次 `isSessionFinal=true`，包含降级结果 |
| `onComplete` | 主动 `finish`、达到 `vadBegin` 首段静音阈值或达到 `maxAudioDuration` 上限后，识别完整结束 |
| `onError` | 发生错误 |

所有回调均归属于创建它们的 session。调用方可以在回调内 `cancel` 当前 session 并立即启动下一
session；被取消 session 的迟到回调不会改用新 sessionId 发送，也不会结束新 session。

`SpeechRecognitionResult`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `isFinal` | `boolean` | 是否最终结果 |
| `isLast` | `boolean` | 是否本次会话的最后一条结果 |
| `result` | `string` | 识别文本 |
| `beginTime` | `number?` | 起始时间毫秒，可能为空 |
| `endTime` | `number?` | 结束时间毫秒，可能为空 |
| `speakerSimilarity` | `number?` | final 且启用声纹校验，并有 ASR 语音证据和非空真实 PCM 时尝试返回 |
| `targetSpeakerEnhancementApplied` | `boolean?` | 当前 session 启用目标说话人增强时为 `true`；未启用时省略 |
| `utteranceId` | `string?` | 开启角色分离时，final utterance 的稳定 ID |
| `speakerIndex` | `number` | 说话人索引；默认 `-1`，已分配为 `0..3` |
| `secondarySpeakerIndexes` | `number[]` | 重叠语音的次要说话人索引；默认空数组。检测到次要说话人但证据不足以分配身份时包含 `-1`，不得据此猜测为上一位或最近一位 |
| `speakerConfidence` | `number` | speaker 归属分数，范围 `[0,1]`，默认 `0`；不是经校准的概率 |

`SpeakerDiarizationUpdate` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `utteranceId` | `string` | 需更新的 final utterance |
| `revision` | `number` | 单调递增修订号；调用方忽略重复或更旧修订 |
| `speakerIndex` | `number` | `-1` 或稳定的 `0..3` |
| `secondarySpeakerIndexes` | `number[]` | 次要说话人索引 |
| `beginTime` / `endTime` | `number` | session-global 毫秒时间轴 |
| `confidence` | `number` | 本次归属分数，范围 `[0,1]` |

`SpeakerDiarizationResult` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `utterances` | `DiarizedUtterance[]` | 本窗口定稿文字；每项的 `sourceUtteranceId` 指向原 ASR final，安全拆句时多个片段可共享该 ID；包含 `rawText`、`text`、全局时间、speaker 索引、`confidence` 和 `overlap` |
| `speakerTurns` | `SpeakerTurn[]` | 本窗口 speaker timeline；保留 primary、secondary、`confidence` 和 `overlap` |
| `windowIndex` | `number` | session 内从 0 开始递增；用于批次去重 |
| `windowBeginTime` / `windowEndTime` | `number` | 本批音频起止位置，session-global 毫秒 |
| `isSessionFinal` | `boolean` | 只有正常收尾最后一批为 `true`；不能与 ASR `isLast` 混用 |
| `speakerCount` | `number` | 截至本批，session 已确认的匿名说话人数 |
| `degraded` | `boolean` | 是否返回当前最佳降级结果 |
| `degradedReason` | `SpeakerDiarizationDegradedReason` | 稳定降级枚举，成功时为 `NONE` |
| `degradedMessage` | `string?` | 可选的详细说明；业务分支应使用 `degradedReason` |
| `inferenceMs` | `number` | 累计分人推理耗时 |
| `rtf` | `number` | 分人处理实时率 |

`SpeakerDiarizationDegradedReason` 包含 `NONE`、`INFERENCE_UNAVAILABLE`、
`MODEL_UNAVAILABLE`、`INFERENCE_TIMEOUT`、`FINISH_TIMEOUT`、`STORAGE_UNAVAILABLE`
和 `SPEAKER_LIMIT_EXCEEDED`。
分人失败不使用致命 `onError` 终止 ASR。

开启 Speaker Diarization 时，`finish()` 仍立即返回；对外收尾顺序固定为：

1. 最后一批 `onSpeakerDiarizationUpdate`。
2. 唯一 `onResult(isLast=true)`。
3. 唯一 `onSpeakerDiarizationResult(isSessionFinal=true)`，即使尾批为空也会返回。
4. 唯一 `onComplete`。

会话进行中可多次返回 `isSessionFinal=false` 的窗口结果，不能据此停止录音或清空全文。
调用方按 `sourceUtteranceId` 替换本批临时句子并累积保存；窗口发布后不再收到对应句子的 update。
`onResult.isFinal` 只定稿文字，只有窗口结果才定稿身份，整场完成仍以 `onComplete` 为准。
此处是 Harmony／Android 的新语义，旧调用方必须同步迁移；iOS 本轮未改，不能套用本分窗契约。

分人收尾超时时会按相同顺序返回 `degraded=true` 的当前最佳结果；`cancel()` 不产生
last、`onSpeakerDiarizationResult` 或 `onComplete`。未开启时不产生任何 diarization 回调，
原有 ASR 生命周期不变。

> `TargetSpeakerConfig.minSegSec` 默认并在鼎桥适配层固定为 `0`，SDK 不设置最短时长门槛。ASR
> 已产生非空 text/token 时，SDK 使用当前句非空真实 PCM 尝试评分，不再因短句质量判断省略分数。
> 音频时长、短句相似度风险、场景阈值和接受策略由业务方承担。没有 ASR 语音证据、没有
> 真实 PCM、声纹能力未生效或 extractor 技术上无法产生 embedding 时可以省略；SDK 不填充假分数、
> 复制上一句分数或补静音。

> `enableTargetSpeakerEnhancement` 是正式接口预留，但开源 Conv-TasNet 权重没有默认进入商用 HAR。
> 客户包必须先完成模型商用授权、固定模型哈希并重跑对应真机门禁；缺少模型时启动会明确失败，
> 不会静默退回普通 Speaker VAD。本 0.3.8 交付不包含该能力所需模型，不能启用该参数。

> 交付批注 LC-20260716-02（v0.2.6）：调用方在 `SPEECH_END` 回调内同步调用 `finish()`，且没有更早排队的音频时，当前带文本 final 同时标记 `isLast=true`，不会再追加空的 last final。`vadBegin` 命中或确实没有可识别语音时，last final 仍允许为空。

事件码：

| 事件码 | 名称 | 说明 |
| --- | --- | --- |
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

## 7. 声纹

`VoiceprintRegisterParams`：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `voiceprintId` | `string` | 空 | 兼容字段；SDK 仍生成安全 ID 并在结果中返回 |
| `samplePaths` | `string[]` | 空 | 至少 1 个样本路径，每段 3 到 8 秒 |
| `audioInfo` | `AudioInfo` | 默认对象 | 与识别相同的 16 kHz、16 bit、单声道 PCM 格式 |

同步注册无论成功或业务参数失败都返回 `VoiceprintRegisterResult`：`status=0` 表示成功，失败时
`status/message` 携带错误；客户无需为 Android/HarmonyOS 编写不同的异常分支。

```ts
const params = new VoiceprintRegisterParams();
params.samplePaths = [samplePath1, samplePath2];
const result = SpeechRecognizeSdk.registerVoiceprint(params);
```

| 项 | 要求 |
| --- | --- |
| 模型 | `eres2net.onnx` 已内置在 `amphion_dingqiao.har`，宿主无需导入 |
| 样本格式 | 标准 WAV 文件，16 kHz、16 bit、单声道 PCM 编码 |
| 样本时长 | 每段 3 到 8 秒 |
| 样本数量 | 至少 1 段，不限制上限；建议多段提升稳定性 |
| 已注册声纹数量 | SDK 不设置上限，受宿主存储空间约束 |
| 返回 | `VoiceprintRegisterResult.voiceprintId` |

`registerVoiceprint()` 与 `preloadVoiceprintModel()` 都会在 extractor 尚未加载时同步加载并预热声纹模型，不应放在 UI 关键路径。注册成功后，同一个进程内的声纹识别复用该 extractor。`preloadVoiceprintModel()` 是可选优化接口，不是普通声纹识别的前置步骤；Runtime 未就绪或加载失败时返回 `false`。

启用 `enableVoiceprintVerification` 或 `enableSpeakerVad` 时，声纹 extractor 在 ASR 会话启动后后台加载，ASR 音频写入和 partial 结果不等待。模型就绪前 Speaker VAD 保持 fail-open；如果 ASR final 产生时 extractor 仍未就绪，只延后 final 和 `onComplete`，模型就绪后立即完成声纹打分。

内存声纹 extractor 由 `unloadModel()` / `unloadRuntime()` 一并释放；HAR 内置的模型文件和已注册的 embedding 属于持久数据，不随内存模型卸载。调用 `unloadModel()` 后再次使用声纹能力会重新按需加载 extractor，但无需重新注册声纹。

仅启用 `enableVoiceprintVerification` 时，SDK 不依据相似度丢弃识别结果；有 ASR 语音证据且本句
真实 PCM 非空的 final 会尝试返回增强文本与 `speakerSimilarity`。SDK 负责出分，客户业务侧负责
决定是否接受，并承担短句分数波动和阈值选择风险。启用 `enableSpeakerVad` 时，SDK 会在流式阶段
执行目标说话人判断，可拒绝非目标说话人片段，并在目标说话人离场后提前切句。

## 8. 授权

授权文件名为 `amphion-license.lic`。`setLicense` 为异步回调，但鉴权为离线本地完整校验，不发起网络请求。本交付校验授权结构、ECDSA 签名、ASR 能力和四个月有效期；包内授权不绑定包名、签名证书、设备、SDK 主版本或维护期。

`LicenseDeviceIdProvider` 为兼容既有公共接口而保留；本交付授权的设备白名单为空，宿主无需读取或注入 SN/ODID。

```ts
interface LicenseDeviceIdProvider {
  getDeviceSerial(context: Context): string | undefined;
}

interface LicenseActivationCallback {
  onResult(result: LicenseActivationResult): void;
  onError(errorCode: number, message: string): void;
}
```

`LicenseActivationResult` 包含 `errorCode`、`errorMessage`、可选的 `remainingDays` 和 `authorizedFeatures`。`LicenseInfo` 包含 `status`、`expireTime`、`remainingDays` 和 `authorizedFeatures`。

## 9. 错误码

| 错误码 | 名称 | 说明 |
| --- | --- | --- |
| `1002200001` | `CREATE_ENGINE_FAILED` | 创建引擎失败 |
| `1002200002` | `START_LISTENING_FAILED` | 启动识别失败 |
| `1002200003` | `MAX_AUDIO_DURATION` | 兼容占位；达到上限时正常自动结束，不主动回调此错误 |
| `1002200004` | `FINISH_FAILED` | 结束识别失败 |
| `1002200005` | `CANCEL_FAILED` | 取消识别失败 |
| `1002200006` | `ENGINE_BUSY` | 引擎忙 |
| `1002200007` | `ENGINE_NOT_INITIALIZED` | SDK 或 Runtime 未初始化 |
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
| `1002200033` | `LICENSE_DEVICE_MISMATCH` | 设备 SN 未命中白名单，或已配置证书绑定但签名不匹配 |
| `1002200034` | `LICENSE_NOT_SET` | 未设置授权 |
| `1002200035` | `LICENSE_ACTIVATION_FAILED` | 授权激活失败 |

## 10. 生命周期性能说明

甲方简版数据见《SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md》，完整测试方法、逐轮数据和证据索引见《SDK_LIFECYCLE_PERFORMANCE_20260713.md》。性能数据是特定设备、系统构建、模型和包版本下的测量值，不作为所有设备的固定常量。
