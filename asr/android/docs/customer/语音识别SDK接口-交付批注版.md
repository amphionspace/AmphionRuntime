# 语音识别 SDK 接口文档（交付批注版）

本文档以《语音识别SDK接口-20260622.md》（v1.1）为接口契约基线。除本文明确批注的增补与澄清外，Android 与 Harmony 实现、Demo、测试和客户说明均不得偏离该基线文档。

本文只摘录需要批注的基线条目；未摘录条目按 20260622 基线原文执行。表格单元格保留基线原文或交付口径原文，批注放在表格外。

## 1. 契约真值来源

1. 基线文档：`语音识别SDK接口-20260622.md`。
2. 本交付批注版：仅记录本项目相对基线的增补、澄清和交付约束。
3. 实现优先级：基线文档 + 本批注版高于现有平台实现。若实现与文档冲突，除已批注条目外，修改实现对齐文档。

## 2. 最大音频时长

基线原文摘录：

| 位置 | 原文 |
|------|------|
| 概述/约束 | 最大音频时长：短语音模式：20000–60000 ms；长语音模式：20000–28800000 ms |
| writeAudio 错误码 | 1002200003：超过最大音频时长 |
| StartParams.extraParams | maxAudioDuration：Int (ms)，默认值 20000，最大音频时长；短语音 [20000, 60000]，长语音 [20000, 28800000] |
| 错误码总表 | 1002200003：超过最大音频时长，触发阶段 writeAudio |

> 批注（增补 S1，2026-06-29）：达到 `maxAudioDuration` 上限不再作为错误回调 `onError(1002200003)`，改为正常生命周期结束，等同 SDK 自动调用 `finish(sessionId)`：回调 `onResult(isFinal=true,isLast=true)` 后回调 `onComplete`，随后 `isBusy()==false` 且可立即再次 `startListening`。`1002200003` 保留为兼容占位，不再主动触发。

> 批注（参数边界，2026-06-29）：`maxAudioDuration` 默认值为 20000 ms。传入小于 20000 ms 的值时按 20000 ms 处理；当前交付不开放 0 表示不限时。

> 批注（参数上限，2026-07-14）：当前 Android 与 Harmony 均统一按长语音流式实现，`maxAudioDuration` 上限为 28800000 ms；数字与数字字符串均可解析，非有限值或非法字符串不得绕过默认下限。

## 2.1 首段静音与识别模式参数

> 批注（`vadBegin`，2026-07-14）：两端支持显式会话参数 `vadBegin`，范围 500 到 10000 ms；未传时保持禁用。计时依据是写入并被底层 VAD 处理的 PCM 时长，只启动会话而不写音频不会超时。

> 批注（回调顺序，2026-07-14）：持续静音达到 `vadBegin` 后，正常回调一个空的 `onResult(isFinal=true,isLast=true)`，随后回调一次 `onComplete`；不得回调 `SPEECH_BEGIN`、`SPEECH_END` 或 `onError`。阈值边界同时检测到真实语音时语音优先；首次真实起音后，本会话永久取消首段静音计时。

> 批注（模式兼容，2026-07-14）：`recognitionMode` 缺省为 `STREAM=1`，当前不支持 `RECORD=0` 的 SDK 内录音；`recognizerMode` 接受 `short` / `long`，两者均使用长语音流式实现。`locate` 当前仅兼容 `CN`，`sessionGeneralLexicon` 在 V1 不生效。

> 批注（错误码兼容，2026-07-14）：增加 `NO_MIC_PERMISSION=1002200012` 常量；由于当前不支持 SDK 内录音，两端不会主动发出该错误。

## 3. 写入音频帧

基线原文摘录：

| 位置 | 原文 |
|------|------|
| 概述/约束 | 每帧大小：640 字节（对应 20ms）或 1280 字节（对应 40ms） |
| writeAudio 参数说明 | audio：PCM 音频帧，仅支持 640 字节（20ms）或 1280 字节（40ms） |
| writeAudio 调用频率 | 两次 writeAudio 调用间隔须为 20ms（640 字节帧）或 40ms（1280 字节帧），与实时采集节奏对齐 |

> 批注（交付约束，2026-06-29）：基线文档中 1280 字节（40ms）已用删除线标记为废弃，本交付只接受 640 字节（20ms）帧。传入 320、960、1280 或其他非 640 字节帧时，按识别运行时错误处理。

> 批注（生命周期澄清，2026-06-29）：当 SDK 因 `maxAudioDuration` 自动结束后，调用方可能仍有少量采集线程残留帧到达。自动结束到 `onComplete` 的短暂窗口内，重复 `writeAudio` 不应导致崩溃、重复 complete 或 busy 卡死；`onComplete` 后再写入旧 `sessionId` 按非活跃会话处理。

## 4. 结束、取消与回调顺序

基线原文摘录：

| 位置 | 原文 |
|------|------|
| finish | 调用后引擎完成剩余音频解码，通过 onResult（isFinal=true）和 onComplete 回调返回最终识别结果 |
| cancel | 立即终止当前会话，不触发 onResult 和 onComplete，已识别的中间结果全部丢弃 |
| SpeechRecognitionResult.isLast | true = 整个会话的最后一条结果 |
| onResult | 当 isFinal=true 且 isLast=true 时，表示整个会话识别完毕 |
| onComplete | 调用 finish() 后，引擎完成所有解码时触发，标志会话正常结束 |

> 批注（生命周期澄清，2026-06-29）：所有正常结束路径，包括显式 `finish`、达到 `maxAudioDuration` 自动结束，都必须最多产生一次 `onResult(isFinal=true,isLast=true)` 和一次 `onComplete`。`onComplete` 之后不得再回调任何 `onResult`。

> 批注（生命周期澄清，2026-06-29）：`finish(sessionId)` 在同一活跃会话内重复调用应为幂等行为，不应重复触发 `onComplete` 或造成引擎 busy 卡死。

> 批注（生命周期澄清，2026-06-29）：`cancel(sessionId)` 表示调用方放弃本次识别；一旦 cancel 生效，本会话不得再触发 final result 或 `onComplete`。cancel 后引擎必须回到空闲。

> 批注（生命周期澄清，2026-06-29）：任何终止路径结束后，引擎必须满足 `isBusy()==false`，且可立即重新 `startListening`。

## 5. 声纹注册

基线原文摘录：

| 位置 | 原文 |
|------|------|
| 声纹注册说明 | 传入 3~5 条声纹样本音频，提取声纹特征并持久化存储，返回声纹 ID 供后续识别会话引用 |
| 声纹注册错误码 | 1002200021：样本数量不符，须为 3~5 条 |
| VoiceprintRegisterParams.samplePaths | 声纹样本文件路径列表，须为 3~5 条，每条时长 3~8s，覆盖远/中/近录音距离 |

> 批注（增补 S2，2026-06-29）：本交付将声纹样本数量硬性下限放宽为至少 1 条；3~5 条保留为推荐值，用于提升跨距离和噪声环境下的稳定性。`1002200021` 仅在样本数量小于 1 时触发。

> 批注（仍按基线执行，2026-06-29）：每条声纹样本时长仍须为 3~8 秒；不满足时触发 `1002200022`。

## 6. 声纹与目标说话人 VAD 扩展

基线原文摘录：

| 位置 | 原文 |
|------|------|
| StartParams.extraParams | enableVoiceprintVerification：是否在本次会话中启用声纹校验；启用时须同时传入 voiceprintIds |
| StartParams.extraParams | voiceprintIds：目标声纹 ID 列表；enableVoiceprintVerification=true 时必填，支持多个目标声纹 |
| SpeechRecognitionResult.speakerSimilarity | 本段语音与目标声纹的相似度（0~1）；仅在 isFinal=true 且会话启用声纹校验时有效 |

> 批注（交付扩展，2026-06-29）：本交付额外支持 `enableSpeakerVad`、`speakerVadThreshold`、`speakerVadWindowMs`、`speakerVadHopMs`、`speakerVadConsecutiveBelow` 与运行时 `setSpeakerVadEnabled(enabled)`，用于目标说话人离场检测。启用该能力时必须有可用的 `voiceprintIds`，否则应返回声纹不存在或启动失败相关错误。

> 批注（交付扩展，2026-06-29）：本交付的声纹核验为打分模式，SDK 不在内部丢弃非目标说话人 final 结果；是否接受该结果由客户业务根据 `speakerSimilarity` 判定。

> 批注（交付澄清 VP-20260715-01，2026-07-15）：`speakerSimilarity` 是可选值。有效语音短于 `TargetSpeakerConfig.minSegSec`（默认 1.5 秒）时无法可靠打分，SDK 保留 final 识别结果但省略该字段；调用方不得把字段缺失当作会话结束或识别失败。

## 7. License

基线原文摘录：

| 位置 | 原文 |
|------|------|
| setLicense | 设置 License 文件路径，异步激活并校验 |
| getLicenseInfo | 查询 License 状态及授权信息 |
| LicenseInfo.authorizedFeatures | 已授权的功能模块列表，如 ["asr", "tts"] |
| LicenseActivationResult.authorizedFeatures | 已授权的功能模块列表，仅激活成功时有效 |

> 批注（交付约束，2026-06-29）：鼎桥交付采用本地离线 License 校验，不描述为联网鉴权；客户可见文档不得出现“联网鉴权服务器”等表述。

> 批注（增补 S3，2026-06-30）：正式设备白名单 License 不按 Android applicationId 或 HarmonyOS bundleName 限制宿主应用；applicationId 与 bundleName 仅作为签发记录展示。正式授权边界为签名验真、授权能力、到期时间、SDK 大版本 / 维护期、设备 SN 白名单；如 license 内写入签名证书 SHA-256，则同时校验证书。Demo 体验 License 可记录 Demo 包名并绑定 Demo 签名，但不绑定 SN。

> 批注（生命周期澄清，2026-06-29）：`getLicenseInfo()` 查询的是当前进程通过 `setLicense()` 激活后的 License 信息。若仅依赖 AAR 或 Demo APK 内置体验 License，而未显式调用 `setLicense()`，`getLicenseInfo()` 可返回未设置 License。

## 8. HarmonyOS 生命周期控制

> 批注（HarmonyOS 交付扩展，2026-07-13）：本节接口当前仅适用于 HarmonyOS `amphion_dingqiao` SDK；Android 版本尚未提供，不得无平台标识地写入 Android 调用示例。

HarmonyOS 新增 License、Runtime、Model 三层生命周期：

| 层级 | 加载接口 | 卸载接口 | 说明 |
|------|----------|----------|------|
| License | `setLicense(licensePath, callback)` | 重新设置授权 | 只完成离线完整验权并缓存授权，不拉起 Runtime、不加载模型 |
| Runtime | `prepareRuntime(callback)` | `unloadRuntime()` | 管理 SDK Runtime 状态，不创建模型；卸载时模型跟随释放，已验证授权保留 |
| Model | `createEngineAsync(params, callback)` / `createEngine(params)` | `unloadModel()` | 模型未加载时加载；同语言、同配置已加载时复用 |

`PrepareRuntimeCallback`：

```ts
interface PrepareRuntimeCallback {
  onReady(): void;
  onError(errorCode: number, message: string): void;
}
```

> 批注（前置条件，2026-07-13）：最小顺序为 `init` → `setWorkPath` → `setLicense` 成功 → `prepareRuntime.onReady` → `createEngineAsync.onSuccess` / `createEngine` 返回 → 会话。`createEngineAsync` / `createEngine` 不得在 Runtime 未就绪时调用。

> 批注（幂等与并发，2026-07-13）：`prepareRuntime` 幂等且 single-flight；Runtime 已就绪时直接回调 `onReady`，并发调用共享同一次准备过程。该阶段不创建识别模型 Session。

> 批注（模型卸载，2026-07-13）：`unloadModel` 前必须结束或取消会话，并对持有的 engine 调用 `shutdown`。调用后旧 engine 不再使用；下次创建引擎重新加载模型，但保留 Runtime 与已验证授权。

> 批注（Runtime 卸载，2026-07-13）：调用 `unloadRuntime` 前同样必须结束或取消活跃会话，并对持有的 engine 调用 `shutdown`。`unloadRuntime` 会使模型跟随释放，但保留已验证授权。后续无需重新 `setLicense`，直接重新 `prepareRuntime`；准备时会再次校验保留授权。已映射的 native `.so` 由操作系统管理，不承诺在应用进程存活期间物理卸载动态库映射。

> 批注（授权替换，2026-07-13）：新的 `setLicense` 成功后替换旧授权，并使旧 Runtime / 模型失效，调用方必须重新 `prepareRuntime`。新的授权校验失败时，不得覆盖已经生效的旧授权或破坏正在使用的 Runtime。

## 9. 错误码一致性

基线错误码总表是跨平台唯一真值。Android 与 Harmony 必须使用相同数值与含义。

| 错误码 | 名称 |
|--------|------|
| 1002200001 | CREATE_ENGINE_FAILED |
| 1002200002 | START_LISTENING_FAILED |
| 1002200003 | MAX_AUDIO_DURATION |
| 1002200004 | FINISH_FAILED |
| 1002200005 | CANCEL_FAILED |
| 1002200006 | ENGINE_BUSY |
| 1002200007 | ENGINE_NOT_INITIALIZED |
| 1002200008 | ENGINE_DESTROYED |
| 1002200009 | INTERNAL_ERROR |
| 1002200010 | NOT_LISTENING |
| 1002200011 | RECOGNITION_ERROR |
| 1002200020 | VOICEPRINT_REGISTER_FAILED |
| 1002200021 | VOICEPRINT_SAMPLE_COUNT |
| 1002200022 | VOICEPRINT_SAMPLE_DURATION |
| 1002200024 | VOICEPRINT_NOT_FOUND |
| 1002200030 | LICENSE_FILE_UNREADABLE |
| 1002200031 | LICENSE_INVALID |
| 1002200032 | LICENSE_EXPIRED |
| 1002200033 | LICENSE_DEVICE_MISMATCH |
| 1002200034 | LICENSE_NOT_SET |
| 1002200035 | LICENSE_ACTIVATION_FAILED |

> 批注（兼容澄清，2026-06-29）：`1002200003` 因增补 S1 保留名称但不再主动触发。其余错误码不得跨平台复用为其他含义。

> 批注（兼容澄清，2026-06-30）：正式设备白名单 License 不再因 applicationId / bundleName 不匹配触发授权失败。`LICENSE_DEVICE_MISMATCH` 用于设备 SN 不可用、设备 SN 哈希未命中，或已写入证书绑定时签名证书不匹配等本地绑定失败。
