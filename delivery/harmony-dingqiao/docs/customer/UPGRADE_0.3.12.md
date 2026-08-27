# HarmonyOS ASR SDK 0.3.12 升级说明

本文说明 0.3.12 相对 0.3.11 需要业务方关注的冷启动行为变化。公共 API 和参数保持兼容。

## 1. `startListening()` 不再加载重型模型

首次识别启用声纹校验或 Speaker VAD 时，SDK 不再在 `startListening()` 的 ArkTS 调用栈中重建
ASR recognizer、创建声纹提取器或同步读取 Speaker VAD 边界模型。相关能力在后台加载，避免阻塞
宿主应用的 `AudioCapturer` 回调并造成首句 PCM 缺口。

加载完成前 Speaker VAD 保持 fail-open；SDK 持续接收并保存真实 PCM，在能力就绪后的滑窗继续评分。
有非空 ASR final 时，声纹结果仍按既有契约等待真实提取器评分，不会填充假分数。

## 2. 调用方接入方式不变

推荐继续采用以下时序：

1. 用户开始录音后立即启动 `AudioCapturer`，在 SDK 会话可用前缓存 PCM。
2. 调用 `startListening(startParams)`。
3. 在 `onStart(sessionId, ...)` 内或之后按原顺序回灌缓存 PCM，再进入实时写入。
4. 普通连续识别最终由调用方执行 `finish(sessionId)`；不要把 `isFinal` 与 `isLast` 混用。

`onStart` 仍表示 session 已发布且可同步调用 `writeAudio`、`finish` 或 `cancel`。本版本没有要求客户
把 SDK、录音回调或公共 API 搬到 Worker。

目标说话人增强仍仅保留接口预留；本交付不包含该能力所需模型，不能启用
`enableTargetSpeakerEnhancement`。本次异步化只涉及声纹校验和 Speaker VAD 已交付能力。

## 3. 升级检查

1. 确认宿主仅依赖本包的自包含 `amphion_dingqiao.har`，清理旧 HAR 缓存后重新 `ohpm install`。
2. 杀进程后测试首次 PTT，核对按键时长、捕获 PCM 时长以及 `startListening` 前后的采音回调连续性。
3. 同时覆盖声纹校验和 Speaker VAD 开启场景，确认非空 final 的 `speakerSimilarity` 与
   `isLast -> onComplete` 顺序保持正常。
