# HarmonyOS ASR SDK 0.3.13 升级说明

本版基于 2026-09-08 最新 main，汇总相对上一正式交付的变化。交付包含正式 SDK、Diagnostics Debug SDK、已签名 Demo 和可独立构建的 Demo 源码。

## 本版变化

- 增加可选 ASR 线程调度配置 `AsrSchedulingConfig`；未配置时保持系统默认调度。
- 包含 main 已合入的 Speaker VAD final 尾部处理和右侧上下文修复。
- 包含受限警务文本纠错及普通输入保护，不对歧义词语作无条件替换。

## 接入与兼容性

公共 API 的 `isFinal`、`isLast` 和 `onComplete` 生命周期契约不变。普通连续识别仍由调用方执行 `finish(sessionId)` 结束。

冷启动时，业务方可先启动 `AudioCapturer` 并缓存 PCM，再调用 `startListening()`；收到 `onStart` 后按原顺序同步回灌缓存。升级后应检查冷启动首句、Speaker VAD 换人及取消后重启。

`recognizerMode='short'` 用于短句，`long` 用于会议和持续转写。显式配置保持优先。

Debug 包采用独立 Diagnostics 构建，包含诊断记录；正式包默认不采集诊断 PCM。诊断文件的导出和处理方式见包内说明。

角色分离不作为本次交付验收或能力承诺；不得把保留的类型和接口视为已完成离线验收。目标说话人增强仅预留接口，本交付不包含所需模型，不能启用。
