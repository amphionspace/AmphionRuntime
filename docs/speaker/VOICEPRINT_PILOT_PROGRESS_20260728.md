# 声纹评测 pilot 进展（2026-07-28）

## 当前结论

当前证据足以否定“只调整一个全局阈值即可解决交通噪声退化”，也足以确定下一轮开发优先级；
但它仍是公开 ASR 语料加合成交通噪声的 technology pilot，不能作为真实设备、真实交通现场或
商用 blind 结论。

在“仅使用本机合成数据”的当前范围内，已选定最小优化：每个身份使用 3 段独立注册语音求均值
embedding，继续使用固定阈值 `0.4343833029`。这利用 SDK 已有的多段注册能力，不改变公共接口
对单段注册的兼容性，也不改变 `speakerSimilarity` 或生命周期契约。

优先级如下：

1. 本机合成配置默认采用 3 段 enrollment；单段仍作为兼容性和 paired baseline 保留。
2. 保持全局阈值不变。动态降阈值和质量 backend 在 AISHELL-2 上能降低 FRR，但跨到 KeSpeech
   会增加 FAR，不能作为安全默认值。
3. 不接入当前 DPDFNet 前端：中型 paired A/B 未改善 5/0 dB FRR，且增加明显 CPU 延迟。
4. 预训练模型 A/B 已完成：现有 ERes2Net-base 在本轮 clean/5/0 dB 综合指标最好，暂不替换；
   CampPlus 只保留为算力受限候选，base-200k 与 ERes2NetV2 不进入下一轮。
5. 合成数据结论只作为本机优化，不外推到真实设备、跨日注册或交通现场。

## 已完成

- 固定官方 ERes2Net ONNX 声纹模型及 SHA-256；模型与 Android/Harmony delivery asset 字节一致。
- 打通指定 ASR 模型目录；兼容 `joiner.int8.onnx` 与当前目录中的 `joiner.onnx`。
- 新增 speaker-disjoint pilot runner：独立 recording enrollment/probe、dev 冻结阈值、合成交通噪声、
  可选 ASR、trial/summary/report 落盘及 artifact hash。
- 修复“只在 manifest 前缀选 speaker”的偏差：全量扫描后再按固定 seed 抽样。
- 新增外部固定阈值模式，支持跨 corpus 复验而不在新 corpus 上重调部署阈值。
- 新增 paired enrollment ablation：固定 speaker/probe，只改变 enrollment utterance 数量。
- 完成 AISHELL-2 扩样、KeSpeech 外部复验和 1-vs-3 enrollment ablation。
- 完成 score-only 与 score-plus-quality abstention ranker 的 AISHELL-2 开发、KeSpeech 外部诊断。

## 2026-07-29 SDK 低风险收口

在没有业务实录、GPU 又被占用时，本轮没有继续调模型或部署阈值，而是收口可由现有契约直接证明的
SDK 行为：Harmony 与 Android 统一为“没有 ASR text/token 语音证据时不计算声纹分数”；即使能量
筛选出的片段已经达到 `minSegSec`，也保留识别结果并省略 `speakerSimilarity`，避免把稳态高能噪声
误当成可评分语音。严格有效语音足够时仍优先使用严格样本；严格样本不足但 ASR 已确认语音、且本句
真实 PCM 达到门槛时，仍按原逻辑回退到本句 PCM。

Android/Harmony 同时增加内部评分选择诊断，记录使用严格样本、本句 PCM 或证据不足，以及有效语音、
本句 PCM、最低门槛时长和 ASR 证据；日志不包含识别文本、声纹 ID，也不改变公共 API、回调顺序、
阈值、模型或 Speaker VAD 行为。诊断仅在声纹校验启用时输出。

同步 `origin/main@4a96584` 后，Harmony 初始静音、final 生命周期、声纹回退/缓冲及交付压力工具相关
回归共 55 项通过；评测工具统计、固定阈值、跨 session、质量拒识和 cluster bootstrap 单测 18 项
通过。当前 Linux 主机已补齐 JDK 17、Android API 34 和 Build-Tools 34.0.0；Android Core SDK 与
鼎桥 SDK 的 Debug 77 项单测通过，Release 77 项单测及 R8 路径强制重跑通过。当前 Linux 主机也已
安装官方 Harmony Command Line Tools 5.1.0.849，完成 OHOS arm64 native 交叉编译，并用 Debug 与
Release 两种模式通过 `sherpa_onnx`、`amphion_asr`、`amphion_police`、`amphion_dingqiao` 四个 HAR
的 ArkTS/native 编译和归档完整性校验。为支持纯命令行构建，补齐了仓库原先缺失的
`asr/harmony/hvigor/hvigor-config.json5`，并移除了客户侧验证脚本中 `ohpm 5.1.3` 已不支持的纯日志
参数。随后使用 `/ai_sds_wuzz/MODELS/Amphion/onnx/asr/260717` 组装中英 ASR、标点、ITN、VAD 共
9 项模型资源，保留鼎桥 ERes2Net 声纹模型，生成中英自包含 HAR；该 HAR 已通过模型/native 字节
一致性检查，并在干净客户工程中仅依赖这一份 HAR 完成 `ohpm` 安装和 HAP 编译。尚未配置签名或连接
Harmony 真机，因此可以表述为“Linux 正式工具链和干净宿主编译通过”，不能表述为“真机验收通过”。

## 2026-07-30 本机合成优化

本轮遵循“只合成数据、只在本机优化”的范围，比较了注册段数、DPDFNet 前端降噪、全局阈值、
质量感知阈值和条件救援策略。选择标准是：保护 clean FAR，不增加跨语料 FAR，并在同一冻结阈值下
降低噪声 FRR。

最终只选择 3 段 enrollment。SDK 现有注册路径会分别提取多段语音并对 embedding 求均值、归一化，
因此无需修改 Android/Harmony 评分逻辑；本地评测工具的默认注册段数由 2 改为 3。公共 SDK 仍允许
至少 1 段样本，避免破坏既有调用方。

未选择的候选：

- DPDFNet baseline 在 30 dev / 100 test speaker 的中型 paired A/B 中，将 5 dB FRR 从 12% 提高到
  24%，0 dB FRR 从 40% 提高到 43%，平均每条增加约 286.7 ms；更大模型约 746 ms，也没有改善
  主指标。只降噪 probe 的 smoke 同样退化。
- AISHELL-2 上训练的 score + quality logistic backend 能降低同域噪声 FRR，但 KeSpeech clean/0 dB
  FAR 分别升到 2.4%/3.2%；保守组合和单向救援仍出现 clean FRR 或 FAR 退化。
- 联合 AISHELL-2/KeSpeech 约束的噪声检测救援在校准集上可控，迁移到独立中型 holdout 后几乎没有
  收益，说明策略在合成语料间仍不稳定。

这些负结果表明，本轮根因层的安全改动是改善 enrollment 表征，而不是在 probe 前端或决策阈值上
增加条件分支。

## 2026-08-04 Conv-TasNet 前端复验

分支拉取后无新增提交。本轮使用既有 `voiceprint_pilot_20260730_medium_baseline` 的 1,320 条
trial map，固定 30 dev / 100 test speaker、2 段 enrollment、同一 probe/noise/SNR/seed，评估
Asteroid `mpariente/ConvTasNet_WHAM_sepclean` 前置于现有 ERes2Net。该模型为 8 kHz 两路输出；
每一路分别滑窗提取 ERes2Net embedding，并在 target/non-target 上一律取最大分数。

| 配置 | clean FAR/FRR | 5 dB FAR/FRR | 0 dB FAR/FRR |
| --- | ---: | ---: | ---: |
| ERes2Net baseline，阈值 `0.484805` | 0% / 1% | 0% / 12% | 0% / 40% |
| Conv-TasNet → ERes2Net，原阈值 | 0.33% / 63% | 0.33% / 83% | 0.33% / 90% |
| Conv-TasNet → ERes2Net，clean dev EER 阈值 `0.303837` | 4.33% / 5% | 4.33% / 23% | 3.67% / 29% |
| Conv-TasNet → ERes2Net，dev FAR=0 阈值 `0.397106` | 0.67% / 26% | 0.67% / 49% | 0.67% / 59% |

原阈值 paired score 显示，target 平均分在 clean/5/0 dB 分别下降 `0.251/0.206/0.167`，
non-target 平均分反而上升 `0.027/0.036/0.034`。该分布压缩与 8 kHz 下采样、两人分离训练任务
不匹配一致，但本轮没有单独拆分两项因素的贡献；即使重校准，0 dB FRR 的 11 点改善也以 clean FAR
4.33%、clean FRR 5% 和 5 dB FRR 23% 为代价，不是净收益。

结论：当前 WHAM `sep_clean` Conv-TasNet 不纳入声纹候选，ERes2Net 单独评分仍更好。该结论只针对
此 checkpoint 和“中文单人语音 + 合成交通噪声”，不能外推到 16 kHz、目标说话人条件化或目标域
微调的 TasNet。完整 artifact 位于
`asr/tools/speaker/results/voiceprint_pilot_20260804_medium_convtasnet_wham_sepclean/`，按规则不提交 Git。

## 2026-08-04 Conv-TasNet 带宽 / 人数消融

为拆分上节仍混杂的两个因素，本轮补做两项冻结实验：

1. 对原 1,320 条单人 clean/交通噪声 trial 只做 `16k→8k→16k`，不经过分离网络；
2. 从 clean trial 为 30 dev / 100 test target 各保留一正一负，加入同 split、不同 speaker 的
   0 dB 全时语音干扰，共 260 条双人 trial。负例干扰人排除 enrolled target，标签保持不变。

| 单人条件 diagnostic EER | clean | 5 dB | 0 dB |
| --- | ---: | ---: | ---: |
| 原始 16 kHz ERes2Net | 0.17% | 3.00% | 3.83% |
| 仅 16k→8k→16k | 2.00% | 5.00% | 12.17% |
| Conv-TasNet→ERes2Net | 4.17% | 11.17% | 14.00% |

在 clean target 上，单纯带宽往返使平均分下降 `0.164`，Conv-TasNet 在此基础上再下降 `0.087`；
即原先总平均降幅 `0.251` 中约 65% 已由 8 kHz 往返解释，但分离网络仍有额外损伤。

| 双人 0 dB 全时重叠 | dev 阈值 | test FAR/FRR | test diagnostic EER |
| --- | ---: | ---: | ---: |
| 直接 16 kHz ERes2Net | 0.291210 | 4% / 11% | 9% |
| 仅 16k→8k→16k | 0.236171 | 8% / 21% | 16% |
| Conv-TasNet→ERes2Net | 0.215729 | 20% / 22% | 20% |

按各自 dev 阈值进行 paired 决策审计，8 kHz 对照到 Conv-TasNet 有 20 条由对变错、7 条由错变对，
exact McNemar `p=0.019`；直接 16 kHz 到 Conv-TasNet 为 30/3，`p=1.4e-6`。该显著性只按 trial
计算，未纳入 speaker cluster 和 dev 阈值不确定性，因此仍标为 diagnostic。

结论：人数错配不是主要解释。8 kHz 带宽损失已被实验证实；即便输入改成模型声明的两人重叠，
当前英文 WHAM `sep_clean` checkpoint 仍进一步压缩 target/non-target 可分性。剩余原因与训练域
错配、SI-SDR 分离目标不约束声纹表征，以及两路 max scoring 增加 non-target 命中机会一致；本实验
没有继续把这三项逐一隔离。完整 artifact 位于
`asr/tools/speaker/results/voiceprint_pilot_20260804_medium_convtasnet_ablations/`，按规则不提交 Git。

## 扩样主结果

工作点由 AISHELL-2 dev 冻结为 `0.4343833029`。每个 test 条件包含 100 个 speaker、
200 个 target trials 和 500 个 non-target trials。区间为 trial-level Wilson 95% CI；因为同一 speaker
贡献多个 trial，正式评测仍需 speaker/session cluster bootstrap。

| Corpus / condition | FAR（95% CI） | FRR（95% CI） | 诊断 EER | 解释 |
| --- | --- | --- | --- | --- |
| AISHELL-2 clean | 0.6%（0.2%–1.7%） | 0.0%（0.0%–1.9%） | 0.0% | clean 可分性好 |
| AISHELL-2 traffic 5 dB | 0.4%（0.1%–1.4%） | 3.5%（1.7%–7.0%） | 1.1% | 已出现稳定误拒 |
| AISHELL-2 traffic 0 dB | 0.2%（0.0%–1.1%） | 13.0%（9.0%–18.4%） | 3.0% | target 分数明显下移 |
| KeSpeech clean | 1.4%（0.7%–2.9%） | 2.5%（1.1%–5.7%） | 2.55% | 外部域已有 score shift |
| KeSpeech traffic 0 dB | 0.8%（0.3%–2.0%） | 17.5%（12.9%–23.4%） | 6.45% | 退化跨 corpus 复现 |

阈值敏感性也否定了简单降阈值：AISHELL-2 0 dB 在阈值 `0.30` 时 FRR 可降至 1.5%，但 clean FAR
升到 8.4%；在 clean-dev 冻结阈值 `0.434383` 时 clean FAR 为 0.6%，0 dB FRR 则为 13%。

## 多模板 paired ablation

本组固定 30 个 dev / 60 个 test speaker，probe 始终使用第 4、5 条 utterance，仅将 enrollment 从
第 1 条改为前 3 条。每个 test 条件为 120 个 target / 300 个 non-target trials。

| Enrollment | clean diagnostic EER | 0 dB diagnostic EER | 以 dev FAR ≤ 1% 冻结后的 clean FAR/FRR | 同工作点规则下 0 dB FAR/FRR |
| --- | --- | --- | --- | --- |
| 1 段 | 1.67% | 4.25% | 1.67% / 2.5% | 0% / 14.17% |
| 3 段 | 0% | 1.67% | 0% / 0% | 0% / 14.17% |

上表是每组各自重选 dev 工作点的历史诊断；它把注册样本变化和阈值变化混在了一起。用部署阈值
`0.4343833029` 对两组同一份 trial 重新计算后，得到可直接比较的结果：

| Enrollment | 固定阈值 clean FAR/FRR | 固定阈值 0 dB FAR/FRR |
| --- | ---: | ---: |
| 1 段 | 0.33% / 5.00% | 0% / 25.83% |
| 3 段 | 0.67% / 0% | 0% / 8.33% |

三段 enrollment 让 target score 平均提高 `+0.0848`（clean）和 `+0.0654`（0 dB），non-target
只提高 `+0.0119` 和 `+0.0079`。在固定阈值下，0 dB FRR 下降 17.5 个百分点，clean FAR 仍低于
1%，因此三段注册被选为当前本机合成默认配置。它仍未消除 0 dB 误拒，也不能替代真实域验收。

## CPU-only T0 abstention

T0 冻结声纹阈值 `0.4343833029`，只训练“当前决定是否容易出错”的 logistic ranker。输入不包含
condition/SNR；质量版在 score/margin 外加入时长、RMS、crest factor、帧能量动态、活动帧比例、
过零率、频谱平坦度和削波率。AISHELL-2 test 条件转为开发数据，KeSpeech 已被历史实验观察过，
因此只能称 external diagnostic，不能称 blind。

| Ranker | KeSpeech error AP/AUC | AISHELL 10% budget 迁移后的 KeSpeech coverage | error capture | KeSpeech 0 dB target coverage | conditional FRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| score-only | 0.314 / 0.897 | 87.93% | 78.43% | 71.5% | 5.59% |
| score + quality | 0.391 / 0.889 | 93.14% | 52.94% | 75.0% | 10.0% |

质量特征的 AP 增益说明它们有错误排序信号；但固定 AISHELL 风险阈值在 KeSpeech 上只产生 6.86%
abstain，而不是预注册的 10%，并漏掉更多错误，说明风险 calibration 不可跨语料直接迁移。score-only
虽然捕获更多错误，却以 KeSpeech 0 dB 仅 71.5% target coverage 为代价。两者都不能在缺少业务
`Cabstain` 和真实设备 blind 的情况下宣称净收益。

## LibriSpeech 跨 chapter 复验

GPU 占用期间继续使用 CPU 扫描本地 LibriSpeech：281,241 条 manifest 中有 1,753 位说话人满足
至少两个 chapter、每个 chapter 至少两条 1.5–10 秒语音。本轮固定 50 dev / 100 test speaker，
每人两条 enrollment 来自同一 chapter、两条 target probe 来自另一个 chapter；每目标另有 5 条
non-target。1,050 个 trial 的 session 字段逐条审计，交叉违规为 0。

| 工作点 | Test FAR | Test FRR | 诊断 EER |
| --- | ---: | ---: | ---: |
| LibriSpeech 50-speaker dev EER threshold `0.334978` | 8.8% | 1.0% | 3.0% |
| 既有 AISHELL-2 frozen threshold `0.434383`（同一分数事后复算） | 2.4% | 4.0% | 3.0% |

跨 chapter 诊断 EER `3.0%` 表明当前 embedding 在英语和 chapter 变化下仍保留区分度；主要异常是
100 target / 250 non-target 的 dev 将工作点选得过低，迁移到 test 后 FAR 达 `8.8%`。这再次支持
“先改 calibration 数据和门禁、暂不重训 embedding”。但 chapter 只是 source/session proxy，语料没有
本项目真实设备、日期、距离和交通现场信息，不能替代目标域 blind。

对上述 50-speaker dev 做 500 次 target/enrollment speaker 整簇 bootstrap 后，threshold
p05/p50/p95 为 `0.326071/0.334978/0.369690`；各阈值投到固定 test 后，FAR p05/p50/p95 为
`5.8%/8.8%/9.8%`，FRR 为 `0.5%/1.0%/1.0%`，`P(test FAR > 5%)=97.6%`。这说明在当前
calibration speaker 分布内重采样几乎无法满足 test FAR 门，而不只是原始 dev 恰好抽差。下一版必须
扩大并分层目标域 calibration、预注册成本/FAR 约束和 cluster CI；EER threshold 只能保留为诊断。

## 小样本端到端 ASR 观察

早期 10-speaker smoke 使用指定 ASR 模型验证了链路：clean/20 dB baseline 与 gated target CER
均为 0.68%；10 dB 为 0.68%/4.76%，5 dB 为 0.68%/14.29%，0 dB 为 5.44%/14.29%。该组
样本太小，不作为精度估计，只用于确认声纹误拒会直接恶化 gated CER。

## 本机合成范围的停止条件

本轮已经完成同输入、同 probe、同固定阈值的注册段数差分，并用独立中型集合和 KeSpeech 检查了
降噪及质量策略的退化。当前停止继续调 DPDFNet、全局阈值和规则型救援；继续重复同类合成 A/B
不会改变选择。

如果后续仍限定只用本机合成数据，下一项应单独立项为 embedding fine-tuning，并建立严格的
speaker/source-disjoint train/dev/holdout、clean FAR 门和导出一致性测试；不得把本轮已观察过的
AISHELL-2/KeSpeech test 再称为 blind。overlap 与反欺骗继续走独立轨。

## 可复现实验资产

- `asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_large_traffic/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_kespeech_external_traffic/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_enroll1_paired/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_enroll3_paired/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_quality_abstention/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_librispeech_cross_session_eres2net/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_librispeech_threshold_bootstrap/`
- `asr/tools/speaker/results/voiceprint_pilot_20260730_medium_baseline/`
- `asr/tools/speaker/results/voiceprint_pilot_20260730_medium_dpdfnet_baseline/`

每个目录保留 `trials.jsonl`、`summary.json` 和 `report.md`；结果目录按仓库规则不提交 Git。
