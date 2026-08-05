# 声纹模型 A/B 与训练路线（2026-07-28）

> 2026-08-04 范围校正：本文只规划轨 A“已切好单人 final 的 speaker verification”模型与 scorer。
> 客户 C1 的轮流讲话尾音、C2/C3 的重叠 target-only ASR 分别属于 endpoint/缓冲和目标语音提取问题，
> 见 [客户样例证据](VOICEPRINT_CUSTOMER_CASE_EVIDENCE_20260804.md) 与
> [下一阶段路线图](VOICEPRINT_NEXT_STEP_MAP_20260804.md)。在真实设备非重叠基线证明 verification
> 是主瓶颈前，T2 不再是整个机主识别问题的默认下一步。

## 决策摘要

继续使用当前 `ERes2Net-base 3D-Speaker` 作为端侧 baseline。三款可直接加载的中文预训练候选均未在
同一 AISHELL-2 clean/5/0 dB trial list 上改善低 SNR 根因：CampPlus 更快但略降精度；扩大到
200k speaker 的 ERes2Net-base 更差；ERes2NetV2 更慢且固定 clean 工作点的噪声 FRR 明显更高。

因此下一优先级不是继续盲换公开模型，而是：

1. 当前本机合成配置使用 3 段 enrollment 和固定阈值 `0.4343833029`；公共 SDK 仍兼容单段注册；
2. 不采用当前 DPDFNet 前端或质量动态阈值，它们未通过跨语料 FAR/FRR 保护门；
3. 如果继续限定本机合成数据，下一训练候选是带 clean anchor 的 embedding fine-tuning；
4. 从头训练和多模型 fusion 暂不启动。

2026-08-04 补充：WHAM `sep_clean` 的 8 kHz Conv-TasNet 作为 ERes2Net 前端，在同一 1,320 条
合成 trial 上也未通过。原阈值的 clean/5/0 dB FRR 为 `63%/83%/90%`；clean-dev 重校准虽把
0 dB FRR 从 baseline 40% 降到 29%，却引入 3.67% 的 0 dB FAR、4.33% clean FAR，并将 5 dB
FRR 从 12% 提高到 23%。这不是净收益，不进入 T0/T2 默认路线。

后续带宽/人数消融进一步确认：单人 clean diagnostic EER 为原始 16 kHz `0.17%`、仅
`16k→8k→16k` `2.00%`、Conv-TasNet `4.17%`；两人 0 dB 全时重叠则为 `9%/16%/20%`。
所以当前负结果不只是“输入人数不匹配”，也不能靠换成双人输入恢复；如继续分离路线，应改为
16 kHz、目标说话人条件化且直接约束 speaker embedding 保真的模型，不再投入该 checkpoint。

## A/B 协议

- 50 个 dev speaker、100 个独立 test speaker；speaker-disjoint。
- 每个 identity 使用 2 条 enrollment、2 条 target probe、每目标 5 条 non-target probe。
- 每个 test condition 为 200 target / 500 non-target trials。
- 模型共享相同 speaker、recording、probe、噪声、SNR、seed 和 max-window cosine scorer。
- threshold 只在各模型 AISHELL-2 clean dev 上选择；test 不调参。
- 5/0 dB 是合成交通噪声 technology stress，不是现场 blind。

## 模型结果

| 模型 | 大小 | 维度 | 2.5s 单核 RTF | clean FAR/FRR | 5 dB FAR/FRR | 0 dB FAR/FRR | 0 dB 诊断 EER |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ERes2Net-base 3D-Speaker（当前） | 38 MB | 512 | 0.0365 | 0.6% / 0% | 0.4% / 3.5% | 0.2% / 13.0% | 3.0% |
| CampPlus Chinese common | 27 MB | 192 | 0.0141 | 1.8% / 0.5% | 0% / 3.5% | 0.2% / 15.5% | 4.1% |
| ERes2Net-base 200k | 38 MB | 512 | 0.0362 | 1.2% / 0% | 0.2% / 7.0% | 0% / 18.5% | 4.45% |
| ERes2NetV2 200k | 69 MB | 192 | 0.0830 | 1.0% / 0.5% | 0% / 11.0% | 0% / 29.0% | 3.55% |

CampPlus 相对当前模型在 2.5 秒窗约快 `2.59x`，但没有精度收益。如果设备实测表明当前模型确有
RTF、冷启动或包体阻塞，可把它作为独立“性能优先”配置重新做真机 paired gate；当前不能替换默认模型。

`wespeaker_en_voxceleb_CAM++.onnx` 虽可被 sherpa extractor 加载，但 metadata 为
`normalize_samples=0`。在默认 PCM、显式 `32768` scale、中文/英文、2.5 秒/5 秒/整句多组诊断中，
EER 均约 44%–50%，判定为当前 runtime/scorer 不可用组合，不进入候选表。

## 这些结果对训练方向的含义

### 1. 不能只扩大 speaker 数量

`ERes2Net-base 200k` 与当前 base 架构、大小和速度近似，但 0 dB FRR 从 13% 升到 18.5%，诊断
EER 从 3.0% 升到 4.45%。所以“更多 identity”不是本问题的充分条件；训练数据必须显式覆盖部署域
的噪声、混响、设备、距离、短时长和 session 变化。

### 2. 更强公开 clean benchmark 不等于更稳的部署工作点

ERes2NetV2 的 0 dB 诊断 EER 为 3.55%，但 clean-dev threshold 下 FRR 达 29%。它说明 embedding
仍有一定可分性，却存在更大的 condition calibration shift。先做质量/条件 backend 比直接承担
2.27x RTF 和 1.8x 包体更符合当前失败层。

### 3. 训练必须把 discrimination 与 decision 分开

单调 logistic calibration 可以改善 LLR/actual DCF，但不会改善 EER；质量感知 backend 可以利用
有效语音时长、质量、设备和 embedding 统计改变不同条件下的排序，但更容易过拟合。因此必须使用
speaker/session-disjoint 的 train/dev/blind，并在同一冻结 policy 下报告 FAR、FRR、coverage、
abstain rate、Cllr/actual DCF 与诊断 EER。

## 训练选项

### T0：质量感知 calibration / abstention（推荐先做）

冻结当前 ERes2Net 和 cosine scorer，只训练小型 decision backend。

输入候选：raw cosine、有效语音时长、VAD speech coverage、RMS/动态范围、削波率、频谱平坦度、
embedding norm、设备/codec 类别和累计次数。输出为 calibrated LLR 与
`TARGET / NON_TARGET / INSUFFICIENT_QUALITY`，不得覆盖公共 raw `speakerSimilarity`。

优点是参数少、可审计、易回滚、端侧代价低。缺点是它不能创造缺失的 speaker 信息；若 0 dB 下
target/non-target 本身不可分，只能通过 abstain 换风险下降。

2026-07-28 的 CPU-only synthetic pilot 已完成：质量版相对 score-only 将 KeSpeech 外部错误排序 AP
从 `0.314` 提高到 `0.391`，说明质量特征有增量信号；但 AISHELL 冻结的 10% abstain 风险阈值
迁移到 KeSpeech 后只捕获 `52.94%` 错误，低于 score-only 的 `78.43%`，属于明显 calibration
shift。结论是保留 T0 架构、停止在合成数据上继续调阈值，待真实设备/session 数据重新训练。

2026-07-30 又检查了将 quality logistic 直接用于目标判决的方案：AISHELL-2 holdout 的 0 dB FRR
可降至 9%，但 KeSpeech clean/0 dB FAR 升至 2.4%/3.2%；加入保守约束后仍会牺牲 clean FRR，
规则型单向救援也不能稳定迁移。因此 T0 不进入当前本机默认配置。

补充的 LibriSpeech 跨 chapter CPU 复验在 100 个 test speaker 上得到诊断 EER `3.0%`；同一 test
分数使用小型 Libri dev threshold 时 FAR/FRR 为 `8.8%/1.0%`，使用既有 AISHELL frozen threshold
事后复算为 `2.4%/4.0%`。这说明跨 source 后 embedding 仍可分，但工作点对 calibration sample
和 domain 更敏感；现阶段仍没有启动 GPU embedding training 的证据。

该 LibriSpeech dev 的 500 次 speaker-cluster bootstrap 进一步得到 threshold p05/p95
`0.326/0.370`，对应固定 test FAR p05/p95 `5.8%/9.8%`，且 `97.6%` 的 bootstrap 工作点超过
5% test FAR。这表明问题不只是一次阈值抽样偶然性：当前 calibration population 与 EER 选点规则
不足以约束部署 FAR，应先扩大分层 calibration 并改为业务成本/FAR 约束门禁。

### T1：冻结 embedding 的 discriminative backend

在当前 embedding 上比较 cosine、regularized logistic/metric backend、PLDA-diag 和可选 cohort
normalization。只允许使用 train/dev identity，blind cohort 不可参与 adaptation。输出必须能导出为
简单矩阵/affine 或稳定的端侧实现，不能引入只能在服务器运行的隐式依赖。

### T2：in-domain embedding fine-tuning

以当前 ERes2Net 权重为起点，优先冻结前层、微调后层与分类头。训练 batch 应同时包含 clean anchor
和真实/合成退化对：交通噪声、车内/路侧混响、风噪、警笛/发动机、人群、codec、距离、朝向、
增益和短时裁剪。目标函数可采用 AAM-softmax，并增加同 utterance clean/noisy embedding 一致性约束。

必须防止以下失败：只优化 0 dB 导致 clean FAR 回归；同一 source 的增强版本跨 split；把 test
speaker 加入分类头；只按 trial bootstrap 夸大显著性；训练后继续沿用旧 threshold。

### T3：从头训练或多模型 fusion（暂缓）

只有在拥有足量、合规、跨 session 的目标人群数据，且 T0–T2 在新 blind 上仍不足时启动。从头训练
ERes2NetV2/CampPlus 或 fusion 会显著增加数据、GPU、导出、端侧适配和版本治理成本；当前公开 ASR
corpus 缺少可靠 session/device/date 真值，不满足启动条件。

## 数据与工程准备

本地可用于非正式训练预研的身份规模约为：AISHELL-2 `1,991` speakers，KeSpeech `25,137`
speakers（其中 `24,275` 人至少 5 条 utterance）。这只说明数量可用，不代表许可、同意、人口代表性、
session 真值或商用训练授权已经满足。

当前机器有 A800 80GB GPU，可支撑 pilot fine-tuning；但 AmphionRuntime/icefall 当前没有完整 speaker
training recipe。若引入官方 3D-Speaker 或 WeSpeaker，需要新增 PyTorch/CUDA/torchaudio/sox 等隔离环境、
训练配置、checkpoint provenance、ONNX metadata/export parity 和 Android/Harmony score parity。
不引入该依赖的后果是只能评测预训练 ONNX，不能做可复现 fine-tuning。GPU 是共享资源，启动训练前
仍需确认排期和显存预算，不能把本次空闲探测视为独占资源承诺。

## 启动训练前门禁

1. 冻结产品动作、错误成本、abstain 行为和主工作点规则。
2. 确认语料许可、身份映射、删除策略及训练授权。
3. 建立 source/speaker/session-disjoint train/dev/blind；真实交通 blind 不参与调参。
4. 冻结 baseline trial list、模型/scorer hash、augmentation 配方和 cluster bootstrap 实现。
5. 预注册成功判据：在匹配 clean FAR/coverage 的前提下比较 traffic FRR/actual DCF，并保护 clean、
   短时、低音量、方言、设备和 ASR gated CER 不变量。
6. 每个候选只允许一次正式 blind；失败后该 blind 降级为 dev，下一版本使用新身份/session。

## 下一实验

在当前“仅本机合成数据”范围内，三段 enrollment 已作为默认配置收口，不继续调 DPDFNet、全局阈值
或规则型质量救援。下一项不是立即启动 T2，而是按
[机主识别下一阶段路线图](VOICEPRINT_NEXT_STEP_MAP_20260804.md) 完成 target-only 契约和 C1～C3
同设备基线，判断主失败层属于 verification、endpoint/尾音，还是 overlap 架构缺失。

只有真实设备、非重叠、跨 session 结果在受保护 clean FAR 下仍显示 verification FRR/actual DCF 是
主瓶颈，才独立启动 T2 pilot：使用 source/speaker/session-disjoint 的 train/dev/holdout、clean anchor
与合成/真实交通退化一致性约束，按固定 clean FAR/coverage 比较 traffic FRR，并验证 checkpoint、
ONNX、Android 与 Harmony 分数一致。已经参与本轮决策的 AISHELL-2、KeSpeech 条件不得再标为 blind。

## 实验资产

- `asr/tools/speaker/results/voiceprint_pilot_20260728_model_ab/rtf_all.json`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_large_traffic_campplus_zh/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_large_traffic_eres2net_200k/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_large_traffic_eres2netv2_200k/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_quality_abstention/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_librispeech_cross_session_eres2net/`
- `asr/tools/speaker/results/voiceprint_pilot_20260728_librispeech_threshold_bootstrap/`

每个评测目录保留 `trials.jsonl`、`summary.json` 和 `report.md`；结果目录按仓库规则不提交 Git。

候选模型 SHA-256：

- CampPlus Chinese common：`f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11`
- ERes2Net-base 200k：`e2d2048292e055f7b61cdec3db010503f35369b245bf0b3bbad021c9a91e4053`
- ERes2NetV2 200k：`bf1a75b9930474cf3389ef415e6e5d38ca96fea4a3a00f7e301d080a58ee2239`

模型与训练 recipe 的外部基线以官方
[3D-Speaker](https://github.com/modelscope/3D-Speaker)、
[WeSpeaker](https://github.com/wenet-e2e/wespeaker) 和
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 仓库为准；公开 benchmark 只用于候选筛选，
本项目是否替换仍由上述 paired gate 决定。
