# 冻结真实设备双域 pilot

- 类型：`wayfinder:task`（HITL/AFK 混合）
- 状态：closed / 当前无候选可进入 pilot
- 路线图：[机主识别下一阶段路线图](../VOICEPRINT_NEXT_STEP_MAP_20260804.md)

## Question

怎样用真实交付设备和最小但可估计方差的双域 pilot，决定所选 C1/C2/C3 架构是否值得进入正式
dev/blind，而不是再做一轮无法外推的本机合成 A/B？需要冻结：

1. 办公室 paired control 与交通主域的设备、位置、距离、方向、噪声、语言/方言、turn 和 overlap 桶。
2. speaker/session/source-disjoint 身份与录制结构；enrollment 与 probe 必须跨 session，重叠轨保留独立
   源音频、时间对齐参考文本、SIR/SNR 和 overlap ratio。
3. 轨 A 的 FAR/FRR/coverage/DCF，轨 B 的 turn miss/leakage/边界延迟，轨 C 的 target CER/WER 与
   non-target lexical leakage；生命周期、资源和反欺骗继续独立报告。
4. 当前 SDK baseline 与候选在完全相同 trials 上的 paired、speaker/session-cluster-aware 比较。
5. pilot 用于估计方差和失败桶，不做商用 PASS/FAIL；它必须输出正式 dev/blind 的 power/precision
   simulation 输入、system card、dataset card、trial schema 和 blind custody 草案。
6. 当结果显示区间过宽、条件覆盖不足或候选只在办公室有效时，结论必须是 INCONCLUSIVE/域受限，
   不得通过混合容易条件或增加同一人的相关 trials 得出总体通过。

票据关闭时应给出版本化 protocol、manifest/trial schema、采集清单、合规/授权状态、资源预算和明确的
停止规则；未经该冻结，不启动正式 blind 或对外准确率声明。

## 收口（2026-08-05）

C1 参数与 buffered-tail、C2/C3 无训练分离均未通过各自冻结门，当前不存在可与 SDK baseline 做 paired
pilot 的候选。为避免在没有候选时采集无法回答决策问题的数据，本票据按“无候选”关闭；没有启动正式
blind，也没有对外准确率声明。未来训练路线若产出满足离线门和资源门的新候选，应以新的合规/授权、
protocol 和 power 设计重新开票，本文件不构成本分支待执行清单。
