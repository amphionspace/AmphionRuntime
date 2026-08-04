# Conv-TasNet Linux 下一轮实验决策（2026-08-04）

## 1. 问题重述

下一轮 Linux 实验要回答的是：Mate 80 已通过小样本真机门的 **16 kHz、固定 2 秒 Conv-TasNet
按需重叠救援链路**，在模型、输入和算法完全对齐后，能否扩大到开放集非目标身份和受控 SIR 条件，
而不是重新回答“8 kHz WHAM Conv-TasNet 是否适合作为所有语音的常驻声纹前端”。

## 2. 现有 Linux 实验是否错误

**没有错误，但它回答了另一个问题。** 现有实验的代码、配对 trial 和消融结论仍然有效：

- `mpariente/ConvTasNet_WHAM_sepclean` 的 8 kHz checkpoint 不应作为 ERes2Net 的常驻前端；
- 单独 `16k→8k→16k` 已显著损伤声纹可分性，说明带宽是主要损失之一；
- 即使改成两人全时重叠，WHAM checkpoint 仍比 8 kHz 往返对照更差，说明人数匹配不是唯一原因；
- 这些结果不能外推到另一个 16 kHz checkpoint，也不能否定“只在疑似重叠时分两路、再按目标声纹选流、
  最后重新 ASR”的救援架构。

两轮实验的边界如下：

| 维度 | 已完成 Linux 实验 | 本轮正确实验 |
| --- | --- | --- |
| 模型 | `mpariente/ConvTasNet_WHAM_sepclean` | Mate 80 同一 `JorisCos/Libri2Mix sepclean` 固定 2 秒 ONNX |
| 采样率 | 8 kHz，输出后回到 16 kHz 打声纹 | 原生 16 kHz，输入/输出各 32000 samples |
| 用法 | 所有 probe 都先分离，再取两路最大声纹分 | 仅重叠救援；逐块两路选流、低置信静音、拼接后重 ASR |
| 主要任务 | voiceprint verification FAR/FRR | target-only ASR 与 non-target lexical leakage |
| 注册语音 | 冻结 trial 中每人 2 段 | 与真机一致的 3 段 enrollment 聚合 |
| 已证明的结论 | 该 8 kHz checkpoint 不可做常驻前端 | 尚需验证开放集泛化；C1～C3 和单个负例已在 Mate 80 通过 |

因此不得把两个结果平均、互相覆盖，或写成“Linux 证明 Conv-TasNet 不可用”。准确表述是：

> 8 kHz WHAM 常驻前端路线已停止；16 kHz Libri2Mix 按需重叠救援路线进入同口径复验和开放集门。

## 3. 高风险假设

本轮在以下假设被证伪前只算内部 pilot：

1. C1～C3 和一个 other-only 身份可能只是小样本命中，不能代表开放集。
2. 盲分离没有目标条件，两个输出都会存在；ERes2Net 阈值和两路最大选择会增加误接收机会。
3. RMS 归一化可能放大低能量残留，使“本应静音的非目标路”获得虚高声纹分。
4. 输出流序号会跨块交换；不能首块选定一路后一直沿用。
5. Linux x86 的 RTF/RSS 只能做回归和异常定位，不能按固定倍率换算成 Harmony ARM 预算。
6. 当前 checkpoint 的 CC BY-SA 义务和采样率 metadata 尚未完成交付审查；算法 PASS 不等于可外发。

## 4. 实验顺序

### 阶段 L0：冻结身份，禁止换模型补结果

使用 Git commit `8bac266` 或其后只包含文档/评测修复的提交。首先校验：

- separator SHA-256：`f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab`；
- 输入为 `[1,32000]`，输出为 `[1,2,32000]`；
- ERes2Net、ZH_EN encoder/decoder/joiner/tokens 和八段 C1～C3 输入均通过
  [`CONVTASNET_LINUX_INPUT_HASHES_20260804.json`](CONVTASNET_LINUX_INPUT_HASHES_20260804.json)；
- CPU Execution Provider，separator ORT 版本先与真机对齐为 `1.16.3`。

任一哈希不同，本轮不得与真机结果做 paired 比较；应新建实验名并明确写成模型或输入变体。

### 阶段 L1：同输入、同算法的最小配对复验

严格按 [`CONVTASNET_LINUX_REPRODUCTION.md`](CONVTASNET_LINUX_REPRODUCTION.md) 先跑独立进程
`baseline`，再跑引用该报告的 `full`。本阶段只证伪以下风险：实现、资源或输入在 Linux 上发生漂移。

通过条件：

- C1/C2/C3 均“含上海、无你好”；
- target-only 保留，other-only 全部拒绝且 ASR 为空；
- 每个 2 秒块的两路分数、选择结果和最终文本可审计；
- separator p95 RTF `<0.35`；相对同环境基线的 peak RSS 增量 `<250 MiB`；
- `failures` 为空，模型和输入哈希全部匹配。

L1 失败时先定位 Linux 与 Mate 80 的模型、重采样、归一化、声纹 embedding、crossfade 或 ASR 差异，
不直接调阈值。L1 通过也不能宣布开放集可用，只允许进入 L2。

### 阶段 L2：开放集和受控混合扩展

使用带身份和独立源真值的数据，不从 C1～C3 复制说话人扩样。最小数据设计：

- 至少 20 个与 target 不同的非注册身份，dev 与 blind/test 按 speaker 隔离；
- target 的 3 段 enrollment 与 probe 按 recording/session 隔离；
- 每个非目标身份覆盖 target-only、other-only、target-absent、轮流讲话和全时重叠；
- 重叠至少覆盖 SIR `-5/0/+5 dB`，混合前保留 target/other 独立源和对齐文本；
- 固定混合 seed 和 trial manifest；同一 trial 在所有方案中使用完全相同的 PCM。

主要指标必须直接对应产品目标：

- **target CER/WER**：只对 target 独立源的参考文本计分；
- **non-target lexical leakage**：增强后文本中来自 other 参考文本的字/词比例；
- **false rescue**：target-absent 或 other-only 被选流并产生非空文本；
- **false rejection**：target-only 或 target-present 的有效目标内容被全部静音；
- 每块 `score_0`、`score_1`、最大绝对分、两路分差、输出能量和最终选择；
- separator、speaker、ASR 分阶段 RTF，以及独立进程 peak RSS。

报告 raw baseline 与 full 的 paired 差异，不能只报 full 的绝对文本。C1～C3 继续作为固定回归样例，
不得用三条样例计算或宣传 FAR/FRR。

### 阶段 L3：只做三项有根因对应的选流消融

按以下顺序比较，所有阈值只能在 dev 冻结，blind/test 不得重选：

1. **A：当前基线** — 每路完整 2 秒 embedding，绝对阈值 `0.25`，逐块重新选流。
2. **B：能量/VAD 先验门** — 在任何 RMS 归一化前拒绝低能量残留，再执行 A；验证假设 3。
3. **C：绝对阈值 + 两路 margin** — 同时要求最大分过门且与另一路分差过门；验证两路最大选择的
   开放集误接收是否可控。

不在本轮继续扫描 DPDFNet、全局 voiceprint threshold、注册语音加噪或更多通用分离 checkpoint；已有
实验已经达到这些方向的停止条件。若 B/C 只有在 blind/test 重新调参才成立，按失败记录，不增加规则。

### 阶段 L4：稳压只在正确性通过后执行

L2/L3 的冻结方案通过后，再运行 30 cycles 且总观察超过 60 秒。任一 case 首次失败立即保留原目录并
停止，不用重跑覆盖。Linux 稳压只判断非有限输出、结果漂移、进程资源增长和异常退出；Harmony
`isLast/onComplete/cancel` 契约仍以真机门为准。

## 5. 决策与停止条件

### 继续为短期 opt-in pilot

只有同时满足以下条件才继续：

- exact 16 kHz L1 完整通过；
- L2 的 paired target CER/WER 在重叠条件相对 raw baseline 有稳定改善；
- target-only 不因救援路径退化；
- frozen blind/test 中没有新增 target-absent/other-only 非目标文本泄漏；
- 资源门和 60 秒以上稳压通过。

这里的“没有新增泄漏”是小规模内部 pilot 的保护门，不是对真实世界误接收率为零的统计声明。正式
阈值需要更大 speaker/session cluster 样本和置信区间。

### 停止阈值搜索，回退 C1-only

出现以下任一情况即停止在盲分离输出上继续堆规则：

- exact 16 kHz 路线仍像 8 kHz WHAM 一样压缩 target/non-target 分布并恶化目标 ASR；
- target-absent/other-only 在 blind/test 出现新增 false rescue；
- B/C 只能通过牺牲 target-only retention 才降低泄漏；
- 结果对非目标身份、SIR 或块边界高度敏感，无法用 dev 冻结参数；
- 资源、稳定性或许可门失败。

短期此时只交付已真机验证的 C1 `Speaker VAD 1000/300 ms` 候选；C2/C3 保留原始 ASR/fallback，
不把不确定的增强文本覆盖原结果。长期路线转到 16 kHz、目标条件化、小型 causal TSE，而不是继续训练
通用盲分离的后处理阈值。

## 6. 结果解释矩阵

| 结果 | 正确解释 | 下一步 |
| --- | --- | --- |
| 8 kHz WHAM 失败，exact 16 kHz L1/L2 通过 | 旧负结果主要受 checkpoint、带宽和任务接法影响 | 做 L4，再回 Mate 80 开放集真机门 |
| exact 16 kHz L1 失败 | Linux 与真机同口径链路存在实现/资源漂移 | 先查哈希与各 stage parity，不扩样、不调阈值 |
| L1 通过，L2 开放集失败 | C1～C3/单负例是小样本命中，盲分离救援不可泛化 | 回退 C1-only；长期 TSE |
| Linux 全部通过 | 平台无关算法门通过 | 仍须 Harmony 生命周期、长稳压和许可门，不能直接外发 |
| Linux RTF 很快但文本失败 | 算力足够，正确性不够 | 不以性能结果抵消业务失败 |

## 7. 必须回传的证据

不要提交模型、客户音频或 enhanced WAV。保留并回传：

- baseline/full 的 `report.json`、`memory.csv`；
- L2 trial manifest、speaker-disjoint split、混合 seed、SIR 和独立源哈希；
- L3 每个候选的冻结 dev 参数及 blind/test paired summary；
- `uname -a`、`lscpu`、`free -h`、Python/package 版本、完整运行命令和 Git commit；
- 首次失败目录，不能被后续运行覆盖。

结论落档时必须分别写“验证了什么、没有验证什么”。Linux 可以证明算法、模型和输入的一致性，不能
替代 Mate 80 的 ARM 资源和 SDK 生命周期证据。
