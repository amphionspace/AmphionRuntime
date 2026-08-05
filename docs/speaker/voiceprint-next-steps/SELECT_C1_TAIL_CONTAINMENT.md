# 选择 C1 尾音控制架构

- 类型：`wayfinder:prototype`（HITL）
- 状态：open / 参数候选已否决，缓冲候选待验证
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

## 独立合成复验（2026-08-05）

已用 `asr/tools/speaker/15_eval_c1_turn_transition_synthetic.py` 在冻结 AISHELL-2
speaker-disjoint enrollment/probe 上执行 target→other 复验。参数固定为 `0.35 / 1000 ms / 300 ms /
连续 2 个低分窗`，没有使用 test 调阈值。30 个 dev、60 个 test target 分别与不同 speaker 配对；
主矩阵覆盖 `-0.3/0/0.3/0.6s` 间隔和 `0.3/0.6/1.0/2.0s` 非目标尾音，另有音量、分帧、
target-only 和 other-only anchor，共 3060 行。

test 主矩阵结果：

- 目标确认率 `100%`；平均非目标音频泄漏 `0.973s → 0.455s`，降幅 `53.24%`。
- 原始 session CER `14.09%`，公开前缀 CER `4.17%`，接近 target-only CER `2.96%`；但
  `30/960` 行仍发布了可归因的非目标文本。
- `16/960` 行发生目标截断，全部来自同一个长目标 probe 的重复场景；独立 target-only anchor
  仍有 `1/60` 在实时 20 ms 下提前 endpoint，不能以矩阵重复解释掉该风险。
- other-only anchor 在实时 20 ms 下有 `2/60` 被误确认，说明冻结 ERes2Net 工作点仍存在开放集误接收。
- 相对实时 20 ms，irregular 分帧 state mismatch `13.33%`、exact endpoint match `26.67%`；
  single-block state mismatch `99.17%`。这与 Android/Harmony 当前每次公开 `writeAudio` 最多处理一个
  跨越 hop 的分数一致，违反同一 PCM 不应随调用方分帧改变决定的不变量。

严格门结论为 **FAIL**：`1000/300 ms` 能明显减少 C1 拖尾，但不能作为正式默认值。失败同时包含
模型层的目标误拒/非目标误接收和调度层的分帧依赖；继续在同一 test 上搜索阈值不能解决后一问题，
也会污染开放集结论。

## 下一候选

先修正并单测 Android/Harmony 的 hop 调度，使一次大块写入能够按绝对 PCM 时间处理所有跨越的 hop，
且与 20 ms/irregular 分帧得到相同决定；该修改必须作为独立生命周期/状态机工作，不夹带阈值变化。
随后在同一冻结输入上重放参数基线。若模型层 anchor 仍失败，则不再把纯 Speaker VAD 参数路线作为
默认方案，转去比较“缓冲提交 + 尾部回退/重解码”，并把 partial 一并置于确认门后。

本轮只完成本机合成诊断，没有修改 SDK，也没有覆盖 Silero/ASR 更早 endpoint、真实设备声学或
`isLast/onComplete/cancel` 真机生命周期。
