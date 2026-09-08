# HarmonyOS ASR SDK 0.3.13 升级说明

本版基于 2026-09-08 最新 main，汇总相对 0.3.12 的变化。交付包含正式 SDK、Diagnostics Debug SDK、已签名 Demo 和可独立构建的 Demo 源码。

## 本版变化

- 角色分离改为以 120 秒为目标窗口分批定稿，等待句末及对应推理完成；已发布身份冻结，结束仅处理尾窗。120 秒不是固定返回时限。
- `onSpeakerDiarizationResult` 从整场一次回调改为多批，每批只含本窗结果。调用方按 `windowIndex` 去重、按 `sourceUtteranceId` 替换临时句子并累积保存；仅末批 `isSessionFinal=true`，不能每次覆盖全文。迁移细节见 [SDK 接口](../语音识别SDK接口.md)。
- 增加可选 ASR 线程调度配置 `AsrSchedulingConfig`；未配置时保持系统默认调度。
- 包含 main 已合入的 Speaker VAD final 尾部处理和右侧上下文修复。
- 包含受限警务文本纠错及普通输入保护，不对歧义词语作无条件替换。

## 接入与兼容性

ASR 的 `isFinal`、`isLast` 和 `onComplete` 生命周期契约不变；角色分离回调须按上述分窗语义迁移。普通连续识别仍由调用方执行 `finish(sessionId)` 结束。

冷启动时，业务方可先启动 `AudioCapturer` 并缓存 PCM，再调用 `startListening()`；收到 `onStart` 后按原顺序同步回灌缓存。升级后应检查冷启动首句、Speaker VAD 换人及取消后重启。

`recognizerMode='short'` 用于短句，`long` 用于会议和持续转写。显式配置保持优先。

Debug 包采用独立 Diagnostics 构建，包含诊断记录；正式包默认不采集诊断 PCM。诊断文件的导出和处理方式见包内说明。

角色分离的最终 ZIP 快速专项已验证明确句末后的中间批和终结批、无降级及正常回调顺序；详见 [专项报告](../../evidence/zip-acceptance/zip-acceptance-20260908-140548-diarization-quick-153641/SUMMARY.md)。该专项不替代精度、长会议稳定性或断网网络观测。

目标说话人增强仅预留接口，本交付不包含所需模型，不能启用。
