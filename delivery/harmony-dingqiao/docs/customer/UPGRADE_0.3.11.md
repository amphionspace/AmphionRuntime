# HarmonyOS ASR SDK 0.3.11 升级说明

本文说明 0.3.11 相对 0.3.10 需要业务方关注的公共接口与行为变化。

## 1. short 与 long 现在具有不同语义

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

```ts
const start = new StartParams();
start.sessionId = 'ptt-1';
start.extraParams['recognizerMode'] = 'short';
start.extraParams['endpointMaxUtteranceMs'] = 20000;
```

```ts
const start = new StartParams();
start.sessionId = 'meeting-1';
start.extraParams['recognizerMode'] = 'long';
start.extraParams['enableContinuousRecognition'] = true;
```

## 2. Speaker VAD 短句行为修复

开启 Speaker VAD 且使用 `short` 时，目标说话人短句在换人边界不再丢失已确认的开头文字。
该变化不要求调用方修改接口，也不改变非目标说话人过滤与生命周期回调顺序。

## 3. Speaker Diarization 公共类型

0.3.11 包含 `SpeakerDiarizationConfig`、`SpeakerDiarizationUpdate`、
`SpeakerDiarizationResult` 及对应 listener 回调。只有在
`StartParams.speakerDiarization` 传入配置对象时才启用；未配置时，原有 ASR 结果和回调链保持不变。

## 4. 升级检查

1. PTT/短句显式配置 `recognizerMode='short'`。
2. 会议/长转写显式配置 `recognizerMode='long'`，不再依赖 `endpointMaxUtteranceMs`。
3. 无论使用哪种模式，正常连续识别仍由调用方最终调用 `finish(sessionId)`。
4. `isFinal` 表示一句/endpoint 完成，`isLast` 仅表示整个 session 的最后结果，两者不能混用。
