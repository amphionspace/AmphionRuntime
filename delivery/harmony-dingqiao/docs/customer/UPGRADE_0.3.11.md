# HarmonyOS ASR SDK 0.3.11 升级说明

本文说明 0.3.11 相对 0.3.10 需要业务方关注的公共接口、识别模式、Speaker VAD 和冷启动行为变化。

## 1. short 与 long 具有不同语义

`CreateEngineParams.extraParams['recognizerMode']` 和
`StartParams.extraParams['recognizerMode']` 均接受 `short` 或 `long`。会话级配置优先于
engine 级配置。

- `short`：适合 PTT、点击开始/结束和短句。`endpointMaxUtteranceMs` 仅在此模式生效，
  达到上限产生单句 final，但不结束 session。
- `long`：适合会议、长转写和持续填单。不按 20/60 秒周期性强切，
  `endpointMaxUtteranceMs` 被忽略；SDK 可在内部压缩已稳定前缀，该动作不产生公开 final 回调。

兼容规则：普通旧调用未传 `recognizerMode` 时仍为 `short`；仅当严格布尔值
`enableContinuousRecognition=true` 且未显式配置模式时，自动使用 `long`。显式
`short`/`long` 始终优先。

## 2. Speaker VAD 短句行为修复

开启 Speaker VAD 且使用 `short` 时，目标说话人短句在换人边界不再丢失已确认的开头文字。
该变化不要求调用方修改接口，也不改变非目标说话人过滤与生命周期回调顺序。

## 3. `startListening()` 不再加载重型模型

首次识别启用声纹校验或 Speaker VAD 时，SDK 不再在 `startListening()` 的 ArkTS 调用栈中重建
ASR recognizer、创建声纹提取器或同步读取 Speaker VAD 边界模型。相关能力在后台加载，避免阻塞
宿主应用的 `AudioCapturer` 回调并造成首句 PCM 缺口。

加载完成前 Speaker VAD 保持 fail-open；SDK 持续接收并保存真实 PCM，在能力就绪后的滑窗继续评分。
有非空 ASR final 时，声纹结果仍按既有契约等待真实提取器评分，不会填充假分数。

## 4. 调用方接入方式不变

推荐继续采用以下时序：

1. 用户开始录音后立即启动 `AudioCapturer`，在 SDK 会话可用前缓存 PCM。
2. 调用 `startListening(startParams)`。
3. 在 `onStart(sessionId, ...)` 内或之后按原顺序回灌缓存 PCM，再进入实时写入。
4. 普通连续识别最终由调用方执行 `finish(sessionId)`；不要把 `isFinal` 与 `isLast` 混用。

`onStart` 仍表示 session 已发布且可同步调用 `writeAudio`、`finish` 或 `cancel`。本版本没有要求客户
把 SDK、录音回调或公共 API 搬到 Worker。

## 5. Speaker Diarization 公共类型

0.3.11 包含 `SpeakerDiarizationConfig`、`SpeakerDiarizationUpdate`、
`SpeakerDiarizationResult` 及对应 listener 回调。只有在
`StartParams.speakerDiarization` 传入配置对象时才启用；未配置时，原有 ASR 结果和回调链保持不变。

角色分离当前仍未达到正式离线交付要求，不应在客户业务中启用或对外宣称已经交付。

## 6. 升级检查

1. PTT/短句显式配置 `recognizerMode='short'`。
2. 会议/长转写显式配置 `recognizerMode='long'`，不再依赖 `endpointMaxUtteranceMs`。
3. 杀进程后测试首次 PTT，核对按键时长、捕获 PCM 时长以及 `startListening` 前后的采音连续性。
4. 同时覆盖声纹校验和 Speaker VAD，确认非空 final 的 `speakerSimilarity` 与
   `isLast -> onComplete` 顺序正常。
5. 正常连续识别仍由调用方最终调用 `finish(sessionId)`。

目标说话人增强仍仅保留接口预留；本交付不包含该能力所需模型，不能启用
`enableTargetSpeakerEnhancement`。
