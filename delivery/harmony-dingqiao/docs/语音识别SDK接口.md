# 语音识别 SDK 接口（HarmonyOS 交付版）

> 本文件描述鼎桥 HarmonyOS 离线语音识别 SDK 的客户集成接口，并已纳入跨平台《语音识别SDK接口-交付批注版.md》的 HarmonyOS 扩展约束。Android 集成请使用 Android 交付文档。

| 文档项 | 值 |
| --- | --- |
| 文档版本 | v1.4（HarmonyOS 正式交付契约） |
| 更新日期 | 2026-07-13 |
| SDK 依赖 | `amphion_dingqiao` |
| SDK 版本 | `0.2.0`（运行时标识 `0.2.0-harmony`，授权主版本 `1`） |

SDK 依赖名为 `amphion_dingqiao`，核心入口为 `SpeechRecognizeSdk`。本版包含 License、Runtime、Model 三层生命周期控制，以及内置声纹模型的按需加载策略，便于宿主控制模型内存和识别启动时延。

集成工具链要求 DevEco Studio 5.x、HarmonyOS SDK 5.x（Stage 模型）；运行环境要求
HarmonyOS API 12 或更高版本，仅支持 `arm64-v8a` 真机。宿主负责申请麦克风权限并通过
`AudioCapturer` 采集音频；SDK 只接收 PCM，不主动申请录音权限。

## 1. 最小调用顺序

```ts
import {
  AudioInfo,
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

`writeAudio` 输入为 PCM S16LE、16 kHz、16 bit、单声道，每帧严格 640 字节，对应 20 ms
音频。帧必须连续、按时间顺序写入。调用 `finish` 表示本次会话音频输入结束，SDK 会处理
尾部缓存、输出最后一次 final 结果并回调 `onComplete`。历史导出的
`DINGQIAO_AUDIO_FRAME_BYTES_40MS` 仅用于源码兼容，已废弃；实现不接受 1280 字节帧。

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
| `SpeechRecognizeSdk.init(context: Context, deviceIdProvider?: LicenseDeviceIdProvider)` | 初始化 SDK；设备白名单授权建议由正式宿主注入稳定设备 SN |
| `SpeechRecognizeSdk.setWorkPath(path: string)` | 设置可读写工作目录，必须在创建引擎或注册声纹前调用 |
| `SpeechRecognizeSdk.getWorkPath(): string` | 查询当前工作目录 |
| `SpeechRecognizeSdk.setLicense(licensePath: string, callback: LicenseActivationCallback)` | 离线校验并缓存正式授权；不拉起 Runtime、不加载模型 |
| `SpeechRecognizeSdk.getLicenseInfo(): LicenseInfo` | 查询当前已激活授权信息 |
| `SpeechRecognizeSdk.prepareRuntime(callback: PrepareRuntimeCallback)` | 准备 Runtime；不加载识别模型 |
| `SpeechRecognizeSdk.createEngine(params: CreateEngineParams): SpeechRecognitionEngine` | 同步创建引擎；模型未加载时同步加载，同配置已加载时复用 |
| `SpeechRecognizeSdk.createEngineAsync(params: CreateEngineParams, callback: CreateEngineCallback)` | 异步创建引擎；推荐用于模型冷加载 |
| `SpeechRecognizeSdk.unloadModel(): void` | 卸载模型，保留 Runtime 和已验证授权 |
| `SpeechRecognizeSdk.unloadRuntime(): void` | 卸载 SDK 管理的 Runtime 状态；模型跟随释放，已验证授权保留 |
| `SpeechRecognizeSdk.registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult` | 同步注册本地声纹；需 Runtime 已就绪 |
| `SpeechRecognizeSdk.deleteVoiceprint(voiceprintId: string): boolean` | 删除本地声纹；不存在时抛出含 `1002200024` 的错误 |
| `SpeechRecognizeSdk.preloadVoiceprintModel(): boolean` | 同步预加载并预热声纹模型；应在非 UI 关键路径调用 |

声纹模型 `eres2net.onnx` 已内置在 `amphion_dingqiao.har`，宿主无需单独分发、导入或复制。`setWorkPath` 指向可读写目录，用于保存已注册的声纹 embedding；SDK 不会把 HAR 内模型复制到该目录。

## 3. 生命周期控制

### 3.1 三层状态

| 层级 | 加载接口 | 卸载接口 | 卸载后保留 |
| --- | --- | --- | --- |
| License | `setLicense()` | 重新设置授权 | 成功授权保存在当前进程内 |
| Runtime | `prepareRuntime()` | `unloadRuntime()` | 已验证授权 |
| Model | ASR：`createEngineAsync()` / `createEngine()`；声纹：注册、显式预加载或声纹会话按需加载 | `unloadModel()` | Runtime、已验证授权、HAR 内模型和已注册声纹 embedding |

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
- 接口幂等：Runtime 已就绪时直接回调 `onReady()`。
- 并发调用为 single-flight：多个调用方共享同一次准备过程，并分别收到结果。
- 本阶段完成授权状态复核与 Runtime 状态准备，不创建识别模型 Session。
- `unloadRuntime()` 后再次调用时，会重新校验保留的授权；授权已过期或失效时回调相应 License 错误。

### 3.3 `createEngineAsync()` / `createEngine()`

```ts
interface CreateEngineCallback {
  onSuccess(engine: SpeechRecognitionEngine): void;
  onError(errorCode: number, message: string): void;
}
```

- 必须在 `prepareRuntime().onReady` 后调用。
- 当前语言和模型配置未加载时，创建引擎会加载模型。
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
- Runtime 卸载是 SDK 管理状态和资源的生命周期控制；应用进程已经映射的 native `.so` 由操作系统管理，接口不承诺在进程存活期间物理卸载动态库映射。

### 3.6 重新设置授权

新的 `setLicense()` 成功后会替换旧授权，并使旧 Runtime 和模型状态失效。必须重新调用 `prepareRuntime()`，收到 `onReady()` 后再创建引擎。新的授权校验失败时，已生效的旧授权与正在使用的 Runtime 不被失败请求覆盖。

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

运行时调用 `setSpeakerVadEnabled(true)` 时，本次会话的 `StartParams.extraParams` 必须已经提供有效的 `voiceprintIds`，即使会话启动时 `enableSpeakerVad=false`。冷态启用 Speaker VAD 会同步等待声纹 extractor 就绪，因此该调用可能阻塞；关闭操作不加载模型。

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

`extraParams` 支持：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `sysGeneralLexicon` | `string[]` 或 `string` | 空 | 系统热词；字符串可用逗号或换行分隔 |
| `plateNormalizeEnabled` | `boolean` | `true` | 是否启用车牌增强 |
| `stationNormalizeEnabled` | `boolean` | `true` | 是否启用派出所增强 |
| `termsNormalizeEnabled` | `boolean` | `true` | 是否启用警务术语增强 |
| `disablePrepack` | `boolean` | `false` | 禁用 ORT 权重 prepack；可降低部分常驻内存/加载耗时，但会降低持续推理速度 |

SDK 会将客户热词与警务域默认热词合并后用于 ASR 解码。改变语言、热词、增强开关或
`disablePrepack` 会形成不同的模型配置，不命中已有模型复用池。

### 5.3 `StartParams`

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `sessionId` | `string` | 空 | 非空，只允许字母、数字、下划线、短横线 |
| `audioInfo` | `AudioInfo` | 默认对象 | 音频格式 |
| `extraParams` | `Record<string, Object>` | 空 | 会话扩展参数 |

常用 `extraParams`：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enablePartialResult` | `boolean` | `true` | 是否回调中间结果 |
| `maxAudioDuration` | `number` | `20000` | 单会话最长音频毫秒数，有效值不小于 20000；达到上限后正常自动结束 |
| `vadEnd` | `number/string` | `800` | VAD 尾静音阈值毫秒，范围 500 到 10000 |
| `enableVoiceprintVerification` | `boolean` | `false` | 是否在 final 阶段返回目标声纹相似度 |
| `enableSpeakerVad` | `boolean` | `false` | 是否启用目标说话人离场提前 endpoint；冷态启动会同步等待声纹模型 |
| `voiceprintIds` | `string[]` | 空 | 声纹 ID 列表；启用声纹校验或 Speaker VAD 时必填 |
| `speakerVadThreshold` | `number/string` | `0.40` | 目标说话人 VAD 阈值，超范围夹到 `[-1, 1]` |
| `speakerVadWindowMs` | `number/string` | `1000` | 窗长，超范围夹到 `[500, 5000]` ms |
| `speakerVadHopMs` | `number/string` | `300` | 步长，超范围夹到 `[100, 2000]` ms |
| `speakerVadConsecutiveBelow` | `number/string` | `2` | 连续低于阈值次数，取整并夹到 `[1, 5]` |

## 6. 回调

```ts
interface RecognitionListener {
  onStart?(sessionId: string, eventMessage?: string): void;
  onEvent?(sessionId: string, eventCode: number, message: string): void;
  onResult?(sessionId: string, result: SpeechRecognitionResult): void;
  onComplete?(sessionId: string, eventMessage?: string): void;
  onError?(sessionId: string, errorCode: number, message: string): void;
}
```

| 回调 | 说明 |
| --- | --- |
| `onStart` | 会话启动成功 |
| `onEvent` | 语音端点、声纹 VAD 状态等事件 |
| `onResult` | 识别结果，包含 partial 与 final |
| `onComplete` | 主动 `finish` 或达到 `maxAudioDuration` 上限自动结束后，识别完整结束 |
| `onError` | 发生错误 |

回调线程与时序约束：

- 参数错误、状态检查、Runtime 已就绪和模型池命中等路径可能在调用栈内同步回调；模型冷加载
  等路径通过异步任务回调。客户代码必须同时兼容两种情况。
- `onStart` 触发时会话已保存且可以立即调用 `writeAudio()`、`finish()` 或 `cancel()`；
  `onStart` 仍可能在 `startListening()` 返回前同步触发。
- 不保证回调位于 UI 线程。宿主更新 UI 时应切换到自己的 UI 调度器，并建议在同一个 ArkTS
  事件执行器上串行操作同一 engine。
- 不要在创建引擎或会话仍在执行时并发调用 `unloadModel()` / `unloadRuntime()`。

`SpeechRecognitionResult`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `isFinal` | `boolean` | 是否最终结果 |
| `isLast` | `boolean` | 是否本次会话的最后一条结果 |
| `result` | `string` | 识别文本；final 为警务增强后文本 |
| `beginTime` | `number?` | 起始时间毫秒，可能为空 |
| `endTime` | `number?` | 结束时间毫秒，可能为空 |
| `speakerSimilarity` | `number?` | final 且启用声纹能力时返回 |

事件码：

| 事件码 | 名称 | 说明 |
| --- | --- | --- |
| `1` | `SPEECH_BEGIN` | 检测到语音开始 |
| `3` | `SPEECH_END` | 检测到语音结束 |
| `20` | `SPEAKER_VAD_CHANGED` | 目标说话人 VAD 开关变化 |
| `21` | `SPEAKER_VAD_DEBUG` | 目标说话人 VAD 调试信息 |
| `22` | `SPEAKER_VAD_REJECTED` | 目标说话人 VAD 拒绝当前 final |

## 7. 声纹

```ts
const params = new VoiceprintRegisterParams();
params.samplePaths = [samplePath1, samplePath2];
const result = SpeechRecognizeSdk.registerVoiceprint(params);
if (result.status === 0) {
  // key 是 SDK 生成的 voiceprintId，value 是第一条样本的文件名。
  const ids = Object.keys(result.voiceprintId);
}
```

| 项 | 要求 |
| --- | --- |
| 模型 | `eres2net.onnx` 已内置在 `amphion_dingqiao.har`，宿主无需导入 |
| 样本格式 | 标准 WAV 文件，16 kHz、16 bit、单声道 PCM 编码 |
| 样本时长 | 每段 3 到 8 秒 |
| 样本数量 | 至少 1 段，不限制上限；建议多段提升稳定性 |
| 已注册声纹数量 | SDK 不设置上限，受宿主存储空间约束 |
| 返回 | `VoiceprintRegisterResult`：`status`、`message`、`voiceprintId: Record<string, string>` |

调用 `registerVoiceprint()` 前必须完成 `prepareRuntime()`。`VoiceprintRegisterParams.voiceprintId` 和
`audioInfo` 是跨平台兼容字段；当前 HarmonyOS 实现根据 WAV 头读取格式，并始终生成新的 ID，
不使用调用方预填的 `voiceprintId`。成功时 `status=0`，返回 map 的 key 为生成的 ID，value 为
第一条样本文件名；失败时查看 `status` 和 `message`。

`deleteVoiceprint()` 成功返回 `true`；ID 为空或不存在时会抛出含 `1002200024` 的错误，客户
应使用 `try/catch` 处理。

`registerVoiceprint()` 与 `preloadVoiceprintModel()` 都会在 extractor 尚未加载时同步加载并预热声纹模型，不应放在 UI 关键路径。注册成功后，同一个进程内的声纹识别复用该 extractor。`preloadVoiceprintModel()` 是可选优化接口，不是普通声纹识别的前置步骤；Runtime 未就绪或加载失败时返回 `false`。

启用 `enableVoiceprintVerification` 时，声纹 extractor 在 ASR 会话启动后后台加载，ASR 音频写入和 partial 结果不等待；如果 ASR final 产生时模型仍未就绪，只延后 final 和 `onComplete`，模型就绪后立即完成声纹打分。启用 `enableSpeakerVad` 时需要流式打分，因此冷态 `startListening()` 会同步等待 extractor。

内存声纹 extractor 由 `unloadModel()` / `unloadRuntime()` 一并释放；HAR 内置的模型文件和已注册的 embedding 属于持久数据，不随内存模型卸载。调用 `unloadModel()` 后再次使用声纹能力会重新按需加载 extractor，但无需重新注册声纹。

仅启用 `enableVoiceprintVerification` 时，SDK 不依据相似度丢弃识别结果；final 会返回增强文本与 `speakerSimilarity`，是否接受由客户业务侧判定。启用 `enableSpeakerVad` 时，SDK 会在流式阶段执行目标说话人判断，可拒绝非目标说话人片段，并在目标说话人离场后提前切句。

传入多个 `voiceprintIds` 时，SDK 跳过不存在的 ID，并将至少一个有效 ID 的 embedding 求平均
后作为一个目标；全部无效时返回 `VOICEPRINT_NOT_FOUND`。有效语音过短时可能无法计算可靠
embedding，约 1.5 秒以下的语音可能不返回 `speakerSimilarity`，因此该字段始终按可选值处理。

## 8. 授权

正式 App 授权文件名默认为 `amphion-license.lic`。`setLicense` 为异步回调，但鉴权为离线本地完整校验，不发起网络请求。校验范围包括授权结构、ECDSA 签名、ASR 能力、有效期、维护期、SDK 主版本和设备白名单；如 License 写入签名证书 SHA-256，则同时校验证书。宿主证书摘要由 SDK 从当前应用签名信息读取；已声明证书绑定但摘要缺失时校验失败，不会跳过。

设备绑定哈希规则为 `SHA-256(normalizedSn + deviceIdSaltId)`，其中 `normalizedSn` 为 trim 后转大写。正式系统宿主应通过 `LicenseDeviceIdProvider` 注入与签发清单一致的设备 SN。普通 Demo 可使用 ODID 签发体验授权，但 ODID 与 SN 不可混用。

```ts
interface LicenseDeviceIdProvider {
  getDeviceSerial(context: Context): string | undefined;
}

interface LicenseActivationCallback {
  onResult(result: LicenseActivationResult): void;
  onError(errorCode: number, message: string): void;
}
```

`LicenseActivationResult` 包含 `errorCode`、`errorMessage`、可选的 `remainingDays` 和 `authorizedFeatures`。

`LicenseInfo` 字段：

| 字段 | 说明 |
| --- | --- |
| `status` | `0` 有效；`1` 已过期；`2` 无效；`3` 设备或宿主证书不匹配 |
| `expireTime` | 到期日当天 `00:00:00 UTC` 的 epoch 毫秒；未提供或不可用时为 `-1` |
| `remainingDays` | 以 UTC 日期计算的剩余整天数；未提供或不可用时为 `-1` |
| `authorizedFeatures` | 授权能力列表 |

`getLicenseInfo()` 在尚未发起过 `setLicense()` 时会抛出含 `1002200034` 的错误。首次校验失败后
可查询对应失败状态；已有有效授权时，新授权失败不会覆盖旧授权信息。

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

甲方简版数据见 `SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md`。完整测试方法、逐轮数据和
证据索引在需要时另行提供，不随 SDK-only 包交付。性能数据是特定设备、系统构建、模型和包
版本下的测量值，不作为所有设备的固定常量。

## 11. 内置模型清单

自包含 HAR 已内置：中英 `zh-en`、粤英 `yue-en`、中英标点、中文 ITN FST、Silero VAD、
警务术语/车牌/派出所增强资源、`eres2net` 声纹模型，以及 `arm64-v8a` native 运行时。
当前中文 ASR transducer 使用 INT8 encoder、FP32 decoder、INT8 joiner；FP32 decoder 用于
避免 INT8 decoder 的明显漏 token。标点模型是独立模型，只对最终文本执行标点恢复。
