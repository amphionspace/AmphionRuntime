# 角色分离端到端验收矩阵

本矩阵把“录音输入到用户可读结果”拆成八个可观测阶段：`input → asr → segmentation → embedding → clustering → identity_freeze → sdk_alignment → caller_display`。每个场景还要分别报告身份准确性、实时队列、内存、可读性、生命周期和离线运行。单测或单个短样例只能证明对应阶段的局部约束，不能替代完整场景。

机器可读定义在 [`diarization_acceptance_matrix.json`](../../delivery/harmony-dingqiao/delivery/diarization_acceptance_matrix.json)。提交前先运行：

```bash
python3 delivery/harmony-dingqiao/delivery/validate_diarization_acceptance_matrix.py \
  --check-evidence
```

命令退出码只表示矩阵结构和证据路径是否有效；输出中的 `matrixStatus` 才是当前场景结论。本基线目前为 `validationStatus=PASS`、`matrixStatus=FAIL`（3 个场景失败，5 个场景未完成证据闭环）。

事件层的首偏离定位使用 [`analyze_diarization_diagnostics.py`](../../delivery/harmony-dingqiao/delivery/analyze_diarization_diagnostics.py)：

```bash
python3 delivery/harmony-dingqiao/delivery/analyze_diarization_diagnostics.py \
  --events /path/to/events.ndjson \
  --evaluation /path/to/evaluation.json \
  --caller /path/to/caller-result.json \
  --expected-speaker-count 4
```

分析器只把已出现的诊断事件作为阶段证据。`DIARIZATION_COMMUNITY_COMMIT` 证明聚类和身份注册表已经运行，不证明识别准确；`DIARIZATION_PUBLIC_RESULT` 证明 SDK 生成了公开角色结果，不证明调用方已经正确展示。没有调用方 payload 时，`caller_display` 必须保持 `UNVERIFIED`。没有 `DIARIZATION_QUEUE` 样本时，不能把 RTF 或 finish 时间当成“长期无积压”证据。

`firstDivergenceStage` 按管线阶段顺序选择第一个 `FAIL`；`firstObservedFailure` 还会把生命周期、实时队列和公开评测中的身份缺失单独列出。前置阶段证据不足时返回 `UNVERIFIED`，避免把纯静音、没有标注或未抓取的日志误判成模型失败。评测 JSON 只在出现说话人数缺失、少数说话人召回为零或同一参考说话人发生多个 SDK ID 时给出明确 `FAIL`；没有项目批准阈值时，即使没有这些红灯，也保持 `INCONCLUSIVE`。

`--expected-speaker-count` 只接受离线评测或客户录音的外部标注，绝不传给 SDK，也不作为端侧强制建组参数。它只能帮助把“最终只冻结一个角色”的症状定位到身份质量门禁。

起始主线基线是 `f5bd3867`、Mate80、`com.amphion.asr.harmony.demo` 0.3.17。矩阵中的公开集结果来自其祖先提交 `711f5ae7`，并明确标为 `ancestor-not-current`，因此不能直接作为当前交付 PASS 证据。现有公开集固定六段的加权严格 DER 为 29.41%；AISHELL-4 三/四人片段存在输出人数不足和少数说话人召回为零，轮流发言和 overlap 场景仍是失败项。单人对齐、时间轴、生命周期和短会话首人修复的已有报告被保留为定位线索，必须在最终 HAP 和当前提交上重新绑定后才能进入交付结论。

矩阵场景覆盖：单人连续发言、两到四人轮流发言、句内换人、短插话、UNKNOWN、overlap、长会议和停止录音尾段。完成整体交付还需要在同一提交、设备和产物上同时满足：公开集同协议相对回归门槛、实录身份与可读性门槛、长时队列和内存门槛、用户可读的文本与角色归属、离线运行，以及 final/last/complete/cancel/finish 的生命周期契约。任何一个核心场景仍为 `FAIL` 或关键证据为 `INCONCLUSIVE`，都不能宣称角色分离已交付。

2026-09-28 更新：[本轮推进记录](DIARIZATION_E2E_PROGRESS_20260928.md) 与 [同产物证据索引](evidence/DIARIZATION_E2E_DIAGNOSTIC_PROGRESS_F850A7CC.json) 绑定 `f850a7cc`。矩阵补齐 `identityStability` 和 `honesty` 门禁；祖先报告/测试源码不能作为当前设备 PASS，相关格恢复为 INCONCLUSIVE。官方 11.7/20.3 仅用于校准；公共集回归、实录体验与资源红灯按已接受策略分别报告。
