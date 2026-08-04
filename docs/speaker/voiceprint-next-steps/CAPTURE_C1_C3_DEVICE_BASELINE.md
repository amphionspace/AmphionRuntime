# 捕获 C1～C3 当前真机基线

- 类型：`wayfinder:task`（AFK，需可用 Harmony USB 设备）
- 状态：in progress / unblocked
- 路线图：[机主识别下一阶段路线图](../VOICEPRINT_NEXT_STEP_MAP_20260804.md)

## Question

在同一台 Harmony 设备、同一组注册 WAV、同一 PCM、相同参数和喂入时序下，0.2.8 客户版本与当前
候选版本的状态机究竟在何时确认目标、何时累积低分、何时 endpoint，以及哪些 PCM 进入公开 final？

任务必须：

1. 只构建/安装中英 `ZH_EN` 测试 HAP，记录 SDK/HAR/HAP、模型、设备、OS、参数和输入 SHA-256。
2. 为每个 session 保存有序的 write/finish、speech begin/end、逐窗 score、target-confirmed、低分计数、
   speaker endpoint、native endpoint、final/last/complete 时间线。
3. 记录每个公开 final 的实际 PCM 起止/有效语音时长、原始 ASR 文本、`speakerSimilarity` 和业务 gate；
   诊断输出不得进入正式客户接口，结束后清除临时 debug 日志。
4. 分别执行实时 paced 与固定 burst；同一模式至少重复到确认结果确定，禁止用放宽空结果率掩盖差异。
5. 精确断言 C1 非目标文字泄漏、C2 机主文字误丢、C3 近场干扰下目标恢复失败，以及 finish 前
   `isLast=0`、结束后恰好一次 last/complete。
6. 输出 0.2.8→候选版本的同输入差分，区分既有能力边界、当前修改引入的回归和时序暴露的旧缺陷。

停止条件是三条样例都有不被后续运行覆盖的报告、逐轮结果、hilog、输入映射和终止原因；本票据不为
追求轮数继续跑无关模式，也不在这里修改阈值或实现修复。

## 2026-08-04 进展

- 已完成 `0.2.9 / 1ca9108`、实时 `20 ms` 喂入的 C1～C3 逐窗真机基线，并保存两轮确定性复现。
- 已完成固定阈值的 `1000/300 ms` 短窗探针；精确业务门为 `C1 PASS / C2 FAIL / C3 FAIL`。
- 已记录窗口 score、target-confirmed、低分计数、endpoint 来源、公开 final 文本与分数；见
  [客户样例证据](../VOICEPRINT_CUSTOMER_CASE_EVIDENCE_20260804.md)。
- 尚未完成 0.2.8 同设备诊断 HAP 差分和 burst 对照，因此本票据保持 in progress；这两项不再阻塞
  C2/C3 进入 TSE 离线可行性准备，但在声称版本回归或关闭票据前必须补齐。
