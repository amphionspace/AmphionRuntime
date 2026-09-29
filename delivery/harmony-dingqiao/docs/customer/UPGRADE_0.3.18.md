# HarmonyOS ASR SDK 0.3.18 候选升级说明

本包为待验收候选，禁止分发。角色分离仍有漏人、误认及短段 UNKNOWN；合入不等于正式交付通过。

相对 2026-09-18 双端基线：采用端侧离线 Community-1 角色推理；修正证据、文本和时间区间归属，保留未提交身份可修正及已提交窗口冻结。Harmony 包含共享 encoder、mask 复用、1 秒证据密度、短 mask 归属及 AHC 成本改进。Android 保留整窗聚类路径，不能宣称两端身份精度相同。

调用方按 windowIndex 累积角色结果，以 sourceUtteranceId 关联原 ASR 句子；临时身份允许修正，角色末批使用 isSessionFinal。isFinal 仍指 ASR 句末，isLast 仅指 session 最后一条，不能混用。保留 UNKNOWN、overlap、speakerInferred 和原始 speakerTurns，不按逐字角色变化拆坏完整词语。

自上一交付后的变更范围包括 #216 工具链、#217 资产说明、#218 ASR 1.4 模型、#221 离线 Community、#225 长会议积压、#226 文本/时间归属、Android Community 对齐、#230 出场顺序、#232 非连续 run、#233 短会话聚类、#234/#236 评测证据及 #235 运行时改进；#215 为旧发布记录、#227 为归档规范。完整提交范围由 Git 基线 5f622c6d 至 7f41e794 保留。

PR #235 已通过的生命周期证据及用户接受的 RSS 增长见仓库合入报告；本候选尚无最终 ZIP 专属验收，不将旧证据改写为新包 PASS。角色身份、四锚点、完整实录、长会议与最终呈现仍保留发布阻断。
