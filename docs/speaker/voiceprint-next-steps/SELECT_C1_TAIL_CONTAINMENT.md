# 选择 C1 尾音控制架构

- 类型：`wayfinder:prototype`（HITL）
- 状态：open / prototype unblocked
- 生产选择仍依赖：`冻结 target-only 产品契约与成功门`
- 路线图：[机主识别下一阶段路线图](../VOICEPRINT_NEXT_STEP_MAP_20260804.md)

## Question

针对“目标人说完、非目标人立即接话”的轮流讲话，哪个最小 coherent change 能在冻结的泄漏/截断门下
通过，同时保持生命周期、分帧无关和跨端语义？至少比较：

1. 参数基线：当前窗口/步长/连续低分与有限的阈值/迟滞扫描，用来量化可达上限，不作为默认答案。
2. **缓冲提交 + 尾部回退/重解码**：在 Speaker VAD 决策前暂存最近窗口，不让未确认尾音进入公开
   ASR；目标离场后丢弃未提交尾音并 final，持续目标则按有界延迟提交。
3. 是否需要把 partial 同样放在确认门后，防止 final 虽干净但非目标 partial 已泄漏到 UI。
4. 对 correctness、final/partial latency、CPU/内存、异常恢复、native/public state boundary、
   Android/Harmony 演进成本逐项比较。

原型必须使用 C1 和独立 target→other 语料，同时保护纯目标连续语音、短停顿、快速换气、纯非目标、
低音量、分帧差异和 finish/cancel/reentrant 生命周期。若只能通过不可接受的目标截断换取低泄漏，应关闭
票据并记录当前单麦/embedding 窗口的上限，而不是把参数写成“修复”。

## 首个候选

`0.2.9` 真机已证明 `1000 ms` 窗、`300 ms` 步长、连续 2 个低分窗、阈值 `0.35` 能让 C1 的
“准备明天去上海”单独放行并阻止“你好”进入放行 final。该结果只解除原型阻塞；在独立 turn 集验证
目标尾字截断、partial 泄漏和相邻生命周期前，不修改 Harmony 正式默认值。
