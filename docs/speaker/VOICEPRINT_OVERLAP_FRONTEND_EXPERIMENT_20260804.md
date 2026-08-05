# C1～C3 重叠前端离线实验（2026-08-04）

## 问题与判定门

本实验只回答一个问题：在现有 `ERes2Net + ZH_EN ASR` 不变时，加入真正的目标语音提取或两人分离
前端，能否恢复客户 C2/C3 中被重叠语音污染的目标内容。

冻结业务断言为：每条输出 ASR 文本必须包含目标词“上海”，且不得包含非目标词“你好”。三条样例逐条
判定，不能用聚合 PASS 掩盖单条失败。C1 同时作为无同步重叠主导的邻接不变量。客户 WAV 没有独立
target/other 源，因此本实验不能计算 SI-SDR、overlap-only CER 或统计准确率。

主机为 Apple M5、24 GiB、macOS 26.5.1。输入均为 16 kHz 单声道；声纹使用 delivery 中与 Harmony
字节一致的 ERes2Net，ASR 使用当前 delivery 的 `ZH_EN` INT8 encoder/joiner 和 FP32 decoder。所有候选
输出保持原输入时长，再送入同一声纹与 ASR，未用事后文本选择输出流。

## 结果摘要

| 前端 | C1 | C2 | C3 | 主机分离 RTF | 资源结论 |
| --- | --- | --- | --- | ---: | --- |
| 0.2.9 Speaker VAD `1000/300 ms` | PASS | FAIL | FAIL | 真机实时 | 只能解决轮流讲话尾音 |
| WeSep BSRNN+ECAPA TSE | PASS | PASS | PASS | `0.302～0.322` | 算法正信号；约 `1.94 GB` 峰值 RSS，不可直接端侧交付 |
| RE-SepFormer 两路分离 + ERes2Net 选流 | PASS | PASS | PASS | `0.035～0.039` | 正对照；不带 target identity，仍是非因果 8 kHz 模型 |
| 固定 4 秒 RE-SepFormer ONNX | 三条分块门可通过 | 三条分块门可通过 | 三条分块门可通过 | 单块中位 `0.0276` | `83.6 MB`、约 `430 MB` RSS、4 秒块延迟，仍超过生产预算 |
| Conv-TasNet 16 kHz 两路分离 + ERes2Net 选流 | PASS | PASS | PASS | 整段 `0.053～0.057` | 5.07M 参数；短期端侧首选，但 CC BY-SA 许可需先确认 |
| 固定 2 秒 Conv-TasNet ONNX + 0.5 秒交叠 | PASS | PASS | PASS（有一字退化） | 含选流 `0.073～0.078` | 20.1 MB；ORT 1.16.3 可运行，最有希望进入真机 pilot |

结论不是“公开模型可以直接装进 SDK”，而是更基础也更重要的一点：C2/C3 的目标内容确实能被前端
恢复，下一阶段应优化/训练小型因果 TSE，不应继续扫描 Speaker VAD 或 final 声纹阈值。

## P0：WeSep BSRNN+ECAPA 16 kHz TSE

### 固定产物

- WeSep commit：`99eca54b60300d39b9353d93cf285a14bba37854`。
- 官方 ModelScope 压缩包 SHA-256：
  `a129b8247e47a2a2fe7407768c69a55c0f97433ba1016c943e9afa1ad2414ffb`。
- `avg_model.pt`：`282,633,800` bytes，SHA-256
  `3d0502171eab31b7cf25835f35d1969b415bb95f2ac52e2c5e2a743ebd8f90e5`。
- checkpoint 中模型张量为 `27,633,829` 个参数；另含 `42,854,690` 个 optimizer state 元素，不能把
  整个 checkpoint 的 70.5M storage 都报告成推理参数。
- 配置：16 kHz、BSRNN、6 repeats、ECAPA-TDNN 192 维 enrollment embedding、VoxCeleb1 动态两人
  混合；BSRNN 使用双向 LSTM，因此是 offline 候选。

当前 WeSpeaker 的可选 S3PRL 前端会在新版 torchaudio 导入时访问已删除接口；本实验只禁用了未被
ECAPA 路径使用的可选 frontend import，并改用官方 `extract_speech_from_pcm` 避开新版 torchaudio 的
TorchCodec 文件加载要求，没有修改模型图、权重或推理决定。

### 逐例结果

| Case | enrollment | whole / 1.5 s max 声纹分数 | 提取后 ZH_EN 文本 | 结果 |
| --- | --- | ---: | --- | --- |
| C1 | near | `0.690380 / 0.633155` | `帮我查收明天的景单然后准备明天去上海` | PASS |
| C2 | far | `0.639917 / 0.618520` | `我准备明天去北京我看看明去北京的机票你帮我订一下准备去上海` | PASS |
| C2 | mid | `0.638471 / 0.619480` | 同上 | PASS |
| C2 | near | `0.641406 / 0.611770` | 同上 | PASS |
| C3 | near | `0.567794 / 0.632371` | `我准备去上海你帮我准备一下飞机票多少钱` | PASS |

C2 用三段 enrollment 分别独立条件化，三次决定一致，排除了“只挑一段注册音频碰巧通过”。输出与输入
等长、峰值统一归一到 `0.9`、没有削波。分离 RTF 为 `0.302～0.322`；同一进程加载模型并跑 C2 三次的
最大 RSS 为 `1,937,391,616` bytes。它通过内容恢复门，但超过本轮 `< 1 GiB` 的继续优化门，因此停止
对该公开双向大模型做参数搜索或直接 Harmony 移植。

## 正对照：RE-SepFormer + ERes2Net 选目标流

候选为 SpeechBrain 官方 `speechbrain/resepformer-wsj02mix`，snapshot
`b8e127bf2b3585c95eebbe7b786e9d3f16675156`，Apache-2.0。它在 8 kHz 英语 WSJ0-2mix 上训练，输出
两路波形，本身不知道哪一路是目标人。本实验将每路上采样回 16 kHz，以当前三段 enrollment 聚合的
ERes2Net 对两路打分，只取分数较高的一路。

| Case | 目标流 whole / max | 目标流 ASR | 非目标流证据 | 结果 |
| --- | ---: | --- | --- | --- |
| C1 | `0.390589 / 0.368262` | `帮我查收明天的景单然后准备明天去上海` | max `0.190813`，文本为“你好…” | PASS |
| C2 | `0.289256 / 0.395072` | `…准备去上海` | max `0.224137`，文本为“北京你好…” | PASS |
| C3 | `0.335284 / 0.434566` | `我准备去上海…` | max `0.119567`，文本为“你好…” | PASS |

模型含 `7,955,201` 个参数。整段 PyTorch 分离 RTF 为 `0.035～0.039`；C2 单次整段进程最大 RSS 约
`1.01 GB`。这条路线证明通用两人分离在当前三条样例上已经足以恢复内容，但它没有 enrollment
conditioning，跨 chunk permutation 与 target-absent 都是未解决风险，不能替代 TSE 产品架构。

## 固定 4 秒 ONNX 与分块实验

为验证现有 ONNX 推理栈的最低可移植性，将 RE-SepFormer 固定为 `1 × 32000`（8 kHz、4 秒）输入：

- ONNX opset 17 导出成功，文件 `83,580,266` bytes，SHA-256
  `7380a6f3da311a1a1244af381b3afc26d49ea7c5a071527cacb069e3addc7739`。
- 同一 C2 前 4 秒输入上，PyTorch/ONNX 输出 cosine 为 `1.0`，最大绝对差 `4.75e-4`、平均绝对差
  `1.23e-5`。
- ONNX Runtime 4 线程、1 次 warmup + 5 次计时，中位 RTF `0.0276`，进程最大 RSS
  `429,654,016` bytes。

4 秒块、1 秒交叠、每块 ERes2Net 选流并交叉淡化拼接时，选流门 `0.30` 会把 C2 末尾短目标块
（分数 `0.2641`）静音，导致漏掉“上海”；固定为实验门 `0.25` 后 C1/C2/C3 均满足“含上海、无你好”。
这同时揭示了边界风险：分块不是免费优化，选择门和短目标块会直接改变字词覆盖。当前 ONNX 仍是非因果、
固定 4 秒、8 kHz、通用分离，并且包体/RSS 超过生产建议的 `<30 MB / <150 MB`，因此只保留为可移植性
证据，不进入 HAR。

## 短期无训练候选：Conv-TasNet 16 kHz

用户明确短期不训练模型后，补测 Asteroid 模型卡
`JorisCos/ConvTasNet_Libri2Mix_sepclean_16k`。它是 16 kHz、两人通用分离模型，含 `5,066,929` 个
参数；模型卡文件约 20.4 MB。它不带 enrollment identity，因此仍必须用现有三段 enrollment 聚合的
ERes2Net 选择目标输出，不能按流序号或识别文本选择。

### 整段结果

| Case | 目标流 whole / max | 目标流 ASR | 非目标流 whole / max | 结果 |
| --- | ---: | --- | ---: | --- |
| C1 | `0.680507 / 0.622517` | `帮我查收明天的景单然后准备明天去上海` | `0.047181 / 0.321862` | PASS |
| C2 | `0.647260 / 0.587344` | `我准备明天去北京我看明去北京的机票你帮我订一下准备去上海` | `0.056324 / 0.157896` | PASS |
| C3 | `0.519358 / 0.614528` | `我准备去上海你帮我准备一下飞机票多少钱` | `-0.009397 / 0.141145` | PASS |

整段 PyTorch 分离 RTF 为 `0.053～0.057`。三个 case 都由 ERes2Net 明确选中目标流，另一流主要识别为
“你好”。这比 RE-SepFormer 更小、更快，并且避免了 8 kHz 下采样。

### 2 秒端侧形态

模型固定导出为 `1 × 32000`（16 kHz、2 秒）ONNX opset 17，大小 `20,147,162` bytes，SHA-256
`f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab`。checkpoint snapshot 为
`e1ef95ab7a037950f3a606b9a56760cf94701d3d`，权重 SHA-256
`8d97f012f7b2f22bb79cb0d0983a7ba27a52c1796ee3f63cbf25b4d28630adce`。图只包含
`Conv/ConvTranspose/PRelu/ReduceMean/Pad/Slice` 等标准算子；仓库 Harmony 使用的完整 ONNX Runtime
`1.16.3` 能在同版本桌面 runtime 成功加载和推理。

采用 2 秒块、0.5 秒交叠、每块两路声纹比较、低于现有阈值 `0.35` 时静音、交叉淡化拼接：

| Case | 分块输出 ASR | 结果 |
| --- | --- | --- |
| C1 | `帮我查收明天的景单然后准备明天去上海` | PASS |
| C2 | `我准备明天去北京我看明去北京的机票你帮我订一下准备去上海` | PASS |
| C3 | `不准备去上海你帮我准备一下飞看飞机票多少钱` | 严格门 PASS，但相对整段出现一字退化 |

C3 的目标流在不同块之间由输出 1 换到输出 0；逐块 ERes2Net 重新评分正确跟随了换序。因此端侧实现
不得在第一块后固定流序号，也不能靠事后 ASR 文本选流。

主机上“2 秒 ONNX + 每块 ERes2Net 选流”的总体 RTF 为 `0.073～0.078`。单测 ONNX session 使用
4 线程并关闭 CPU memory arena/memory pattern 时，ORT 1.28 中位 RTF `0.0238`、进程最大 RSS
`257 MB`；与 Harmony 相同的 ORT 1.16.3 中位 RTF `0.0583`、最大 RSS `267 MB`。这些是桌面进程值，
不能替代 ARM 真机数据；关闭 arena 的目的是让按需分离结束后不长期保留大块激活。

当前真机 0.2.9 基线为 12 个逻辑 CPU，客户回放峰值 RSS `536～554 MB`、CPU p95 约占整机
`12.4%～13.7%`。据此，Conv-TasNet 的计算量高概率可满足当前设备的按需离线 rescue，但内存和最终
延迟仍必须通过一次真实 HAP 验证，不能由主机比例换算宣布 PASS。

短期最小接入形态：保持现有实时识别和 Speaker VAD，只在“滑窗存在明确目标证据、whole final 因混合
而被拒绝”的句子上，按需创建 Conv-TasNet session，分离并重识别后立即销毁。不得对 target-absent
句子无条件运行 separator，也不得让它改变 `isLast/onComplete/cancel` 契约。

许可风险独立于算力：模型卡标记 CC BY-SA 4.0，且历史正文曾出现 3.0/4.0 不一致。内部 pilot 可继续，
闭源客户交付前必须确认 checkpoint 与派生 ONNX 的准确许可及 ShareAlike 义务；未澄清前不能作为正式
商业交付模型。若许可不可接受，Apache-2.0 的 RE-SepFormer 是无训练备选，但包体、内存和 4 秒延迟更高。

## 决策与下一输入

1. **内容恢复可行，失败层已确认。** 三条独立前端路径都能让 C1/C2/C3 逐条通过严格文本门；C2/C3
   后续归入 TSE/分离轨，不再归入声纹阈值或 Speaker VAD 参数轨。
2. **公开 checkpoint 均不直接交付。** WeSep 是任务匹配但资源过大、非因果；RE-SepFormer 资源更小且
   可导 ONNX，但不带 target identity、固定 4 秒延迟和资源仍超预算。
3. **短期无训练路线先验证 Conv-TasNet。** 20.1 MB、2 秒按需 ONNX 是唯一同时满足当前三条严格门和
   主机计算预算的轻量候选；先做许可审查和单一真机 HAP 资源/延迟 pilot，不立即改正式 SDK 默认行为。
4. **长期优化仍是数据与架构。** 准备带 target/other 独立源、对齐文本、enrollment、SIR/SNR/重叠比例
   的中文真实域小集；以 WeSep 输出作 offline teacher/reference，训练或蒸馏 `<30 MB`、有界 look-ahead
   的 causal TSE，再做 FP32 ONNX parity、FP16/INT8 和 Harmony 真机资源门。
5. **C1 保持独立轨。** 现有 `1000/300 ms` Speaker VAD 是更低成本的 C1 候选；只有独立
   target→other 集保护目标截断后，才考虑修改正式默认值。

原始客户 WAV、提取 WAV、模型与临时 Python 环境均不提交仓库。客户源压缩包和输入映射见
[客户样例证据](VOICEPRINT_CUSTOMER_CASE_EVIDENCE_20260804.md)；公开候选与许可核查见
[TSE 候选调研](TARGET_SPEAKER_EXTRACTION_RESEARCH_20260804.md)。
