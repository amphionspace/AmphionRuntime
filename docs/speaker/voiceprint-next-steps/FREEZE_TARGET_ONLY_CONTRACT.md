# 冻结 target-only 产品契约与成功门

- 类型：`wayfinder:grilling`（HITL）
- 状态：deferred / blocked on product、业务风险与测试负责人决策
- 路线图：[机主识别下一阶段路线图](../VOICEPRINT_NEXT_STEP_MAP_20260804.md)

## Question

产品对 C1、C2、C3 分别承诺什么可观察后置条件，才能把“只识别机主”变成可执行而非口号？需要与
产品、业务风险和测试负责人共同冻结：

1. 系统动作是自动隐藏、只做标记、保留原文供人工复核，还是丢弃音频/文本；原始 ASR 是否可追溯。
2. 决策单位是滑窗、native segment、公开 final、turn 还是完整 session；“片段里出现过机主”是否允许
   夹带非目标文字。
3. C1 的主指标和上限：非目标 lexical leakage、目标尾字截断、endpoint 延迟、partial 泄漏。
4. C2/C3 的主指标和分桶：target CER/WER、non-target insertion/leakage、overlap ratio、SIR/SNR、
   机主/干扰人距离与相对响度。
5. 轨 A 的 FAR/FRR/coverage/no-score 策略，以及 `Cmiss`、`Cfa`、可选 `Cabstain` 的排序。
6. 允许增加的 final 延迟、CPU RTF、峰值内存、包体和冷启动成本；Harmony/Android 是否必须同版本同策。
7. PASS、FAIL、INCONCLUSIVE 的机器可读判据和关键最差桶；不得只给总体 accuracy。

票据关闭时应产出版本化的产品契约和 acceptance schema，后续原型只能在该冻结接口上比较。

## 当前边界（2026-08-05）

本分支只能冻结研究门，不能替产品决定自动隐藏、人工复核、数据保留、错误成本和端侧资源预算。
C1/C2/C3 无训练候选已全部关闭，没有可进入生产 acceptance 的实现，因此本票据从本机工程队列移出。
未来若产品明确启动训练路线，必须由产品、业务风险和测试负责人共同提供上述选择后另开交付分支；
在此之前它是外部 HITL 前置条件，不是本分支待办，也不得由合成指标代填。
