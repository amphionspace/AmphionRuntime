# 鸿蒙 ASR SDK 声纹能力商用成熟度调研

日期：2026-07-27

范围：当前 Harmony/Android 鼎桥 SDK 中的 ERes2Net speaker embedding、余弦打分、注册/验证、Speaker VAD，以及达到“商用”所需但当前未必具备的评测、校准、反欺骗和治理能力。
方法：优先使用模型/工具官方仓库、论文原文、NIST 官方评测计划、ISO 标准页面、FIDO 正式要求和 ASVspoof 官方评测计划；仓库现状来自源码和已有可复现实验记录。本文不是法律意见，也不把公开 benchmark 等同于客户现场验收。

## 1. 问题重述、假设与结论

真正的问题不是“余弦分数是否要压到 0–1”，而是：**在明确的业务场景、攻击模型、目标人群和声学条件下，这套 SDK 能否用一个冻结的决策策略，稳定达到客户约定的误接收、误拒绝、可用性和安全指标。**

### 1.1 关键假设与风险级别

| 假设 | 当前证据 | 风险 |
| --- | --- | --- |
| 客户所谓“商用”主要是目标说话人过滤，而不是单因子身份认证或司法鉴定 | SDK 当前对外返回 `speakerSimilarity`，由业务侧决定是否接受；需求表述尚未冻结 | **高**：三种用途需要完全不同的门禁 |
| 当前交付模型就是 `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx` | 仓库 NOTICE 和内置资源名称一致 | 低 |
| 当前公开分数是未校准余弦相似度 | Harmony 与 Android 源码均直接计算 cosine | 低 |
| 客户环境与注册/开发语料同分布 | 没有客户身份标注评测集证明 | **高** |
| 输入切段内只有一个说话人，或目标人的存在足以代表整段都属于目标人 | 当前 embedding 验证不会分离重叠语音 | **高** |
| 无需抵抗录音回放、TTS/VC、深伪或音频注入 | 当前链路未见独立 PAD/反欺骗决策 | **严重**，若用于身份认证 |

### 1.2 结论先行

1. **“训练目标是角度，推理分数不在 0–1，需要归一化”只对了一半。** 当前模型使用 angular-margin 训练，SDK 推理使用 cosine；余弦按定义在 `[-1, 1]`。`(cosine + 1) / 2` 可以作为显示层单调映射，但它既不会提升区分能力，也不会自动成为“同一人的概率”。
2. **“speaker 公认无法落地”不准确。** NIST 自 1996 年持续组织 speaker recognition evaluation；FIDO 的现行生物组件要求明确覆盖 voice 的回放、剪接、合成器和模仿攻击；这说明产业界有可落地的限定场景和验收框架。它同时说明：可落地的是完整系统和明确条件，不是一个裸 cosine 分数。
3. **当前 SDK 今天还没有证据支持泛化的“商用级声纹认证”声明。** 已有门禁证明分数可返回、生命周期正确、设备可运行；没有证明客户域的 FAR/FRR、低 FAR 工作点、校准、反欺骗、跨设备/距离/方言、重叠说话人或模板保护。
4. **在当前 embedding 框架内仍有显著优化空间。** 不换模型就可以完成场景化评测、阈值冻结、多段多会话注册、质量门控、分数校准、条件感知校准、模板/分数语义修正；之后再 A/B ERes2NetV2、200k-speaker 模型、CAM++ 或更合适的 backend。
5. **能否到达商用取决于用途。** 对“低风险、可回退、单人或弱重叠、限定设备/距离/语言”的目标人过滤，经过下文 P0/P1 门禁后有现实可行性；对“嘈杂多人整段归属”，embedding-only 不足，需要 diarization/overlap detection/分离；对“单因子身份认证”，还必须增加 PAD、活体/挑战响应、重试限制、模板保护和系统级安全；对“司法/取证证据”，当前分数接口不够。

## 2. 两个观点应如何准确解释

### 2.1 Angular-margin 训练、cosine 推理和 0–1 映射

当前交付 ONNX 的内嵌 metadata 标明 `output_dim=512`、`sample_rate=16000`、`feature_normalize_type=global-mean`，model comment 指向 `iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k`。上游通用 ERes2Net-base recipe 页面写的是 80 维 fbank、192 维 speaker embedding、additive angular margin，说明**架构 recipe 的公开配置不能代替对实际导出模型的检查**；本文涉及当前产物时以 ONNX metadata 的 512 维为准。当前 SDK 直接计算两个 embedding 的余弦。来源：

- [3D-Speaker 官方 ERes2Net recipe](https://github.com/modelscope/3D-Speaker/tree/main/egs/3dspeaker/sv-eres2net)
- [ERes2Net 原论文](https://arxiv.org/abs/2305.12838)
- 当前实现：`asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets` 的 `cosineSimilarity`，以及 `asr/android/sdk/src/main/java/com/amphion/asr/internal/SpeakerVerifier.kt` 的 `cosine`

对两个非零 embedding `x, y`：

```text
rawScore = cosine(x, y) = x·y / (||x|| ||y||) ∈ [-1, 1]
displayScore = (rawScore + 1) / 2 ∈ [0, 1]
```

由 Cauchy–Schwarz 不等式，cosine 天然有界。这里有三种经常被混淆的“归一化”：

| 层次 | 例子 | 能改变什么 | 不能改变什么 |
| --- | --- | --- | --- |
| 单调显示映射 | `(s+1)/2`、乘 100 显示百分制 | 数值范围、UI 可读性、对应阈值数值 | ROC/DET、EER、可分性、真实性概率 |
| score normalization | Z/T/S-norm、cohort-based normalization | 补偿一部分 trial/cohort 条件差异，可能改变不同 trial 的排序 | 不保证是概率，也不能代替独立评测 |
| 概率/LLR 校准 | 代表性开发集上的 logistic regression、质量感知 calibrator | 把分数转换为可用于已定义 prior/cost 的 LLR 或 posterior；衡量 actual DCF/Cllr | 不会凭空修复 embedding 不可分；域偏移后可能失准 |

严格单调映射保持样本排序，因此在扫遍阈值时 ROC、EER 和 minDCF 不变。它只会把原阈值 `t` 变成新阈值 `(t+1)/2`。所以“相似度显示为 80%”不等于“80% 概率是同一人”。

### 2.2 什么才是概率校准

NIST SRE21 要求系统为每个 trial 输出 target/non-target 的自然对数似然比 LLR，而不是 0–1 cosine；主指标使用两个目标先验 `0.01` 和 `0.05` 下的实际 detection cost，并同时报告 minimum cost。来源：[NIST SRE21 Evaluation Plan](https://www.nist.gov/system/files/documents/2021/07/12/2021_SRE_Evaluation_Plan_V5.pdf)。

若校准后得到 LLR `l`，且业务先验“本次确为目标人”的概率是 `π`，理论上的 posterior 为：

```text
P(target | evidence) = sigmoid(l + log(π / (1 - π)))
```

这说明“概率”依赖两部分：证据的 LLR 和业务先验。把裸 cosine 直接过 sigmoid，或者用当前批次的最小/最大分数做 min-max，都没有给出这一语义。

[BOSARIS 原始论文/工具说明](https://arxiv.org/abs/1304.2865)将 discrimination、Bayes operating point、校准和 fusion 分开处理，并提供 logistic-regression calibration。它还强调，低错误率工作点的校准和评估需要很大的 trial 集；少量 demo 音频无法支持低 FAR 声明。[跨条件鲁棒 backend 原论文](https://arxiv.org/abs/2102.01760)进一步显示，传统全局 logistic calibrator 在未见条件下表现会变差，使用时长等 side information 的自适应校准可以改善跨域鲁棒性，但仍必须在多样数据上训练和验证。

### 2.3 “业界无法落地”的正确边界

声纹不是“不可用”，而是**没有脱离条件的全局准确率**：

- NIST SRE21 的正式试验明确控制 enrollment、test duration、电话/视频源、语言是否匹配、电话号码是否匹配，并按条件分区计算结果；其 enrollment 约 60 秒，test speech 约 10–60 秒，而不是当前 SDK 最短 1.5 秒。[NIST SRE21 Evaluation Plan](https://www.nist.gov/system/files/documents/2021/07/12/2021_SRE_Evaluation_Plan_V5.pdf)
- 上游 3D-Speaker 为当前 ERes2Net-base 架构公开的 EER 在 VoxCeleb1-O 为 0.84%，在 CN-Celeb 为 6.69%，在 3D-Speaker 为 7.21%；精度随数据域大幅变化。[3D-Speaker 官方仓库](https://github.com/modelscope/3D-Speaker)
- 更接近当前精确模型 recipe 的 3D-Speaker 条件表中，ERes2Net-base 在 cross-device、cross-distance、cross-dialect 条件分别为 7.06%、9.95%、12.76% EER。[官方 ERes2Net recipe](https://github.com/modelscope/3D-Speaker/tree/main/egs/3dspeaker/sv-eres2net)
- CN-Celeb 原论文把 genre、speaking style、physiological status、设备和噪声共同导致的 mismatch 列为主要挑战；同一模型在受控或公开视频 benchmark 上的结果会高估现场性能。[CN-Celeb multi-genre 原论文](https://arxiv.org/abs/2012.12468)

因此行业争议真正针对的是“任意人、任意设备、任意距离、任意时长、任意噪声、任意攻击下都能可靠认证”的无边界承诺。限定场景、完整决策系统、持续监控和回退机制仍然可以商业化。

目标说话人辅助也不是纯理论方向。Google 的 VoiceFilter-Lite 原始工程报告展示了一个 2.2 MB、端侧流式的目标说话人特征过滤器；在其限定的英语重叠语音实验中，WER 相对改善 25.1%，远场混响重叠条件改善 14.7%。这证明“限定场景的目标人辅助”可以工程落地，也同时说明当前 SDK 的 segment-level cosine gate 不能直接继承该结果：VoiceFilter-Lite 使用专门的混合语音训练和特征掩码，解决的是重叠语音抑制，而不是对整段 embedding 做后验判断。[Google Research：VoiceFilter-Lite](https://research.google/blog/improving-on-device-speech-recognition-with-voicefilter-lite/)

## 3. 商用评测指标：每个指标回答不同问题

### 3.1 基本错误率

| 指标 | 回答的问题 | 使用限制 |
| --- | --- | --- |
| FAR / false accept | 非目标人被接受的概率是多少 | 必须明确是 zero-effort impostor 还是主动攻击；两者不能混报 |
| FRR / false reject | 目标人被拒绝的概率是多少 | 必须同时报告 FTE/FTA/无分数率，不能把“未出分”静默排除 |
| EER | 当 FAR=FRR 时，ranking 大致有多好 | 不是业务工作点；高安全系统通常关心远低于 EER 的 FAR 区域 |
| DET/ROC | 阈值变化时 FAR/FRR 的完整权衡 | 应给置信区间和关键条件分桶 |
| minDCF | 给定 prior/cost 时，事后选择最佳阈值能达到的最低代价 | 是乐观下界；不能证明部署阈值已校准 |
| actual DCF | 冻结阈值或 LLR 阈值后的实际代价 | 同时反映 discrimination 和 calibration，更接近部署 |
| Cllr | LLR 软证据的校准敏感代价 | 适用于输出 LLR 的系统；应同时给 `Cllr_min`/calibration loss |

[Application-independent evaluation of speaker detection](https://doi.org/10.1016/j.csl.2005.08.001)提出的 `Cllr` 可以分解 discrimination 与 calibration；[BOSARIS](https://arxiv.org/abs/1304.2865)说明了 EER、ROC/DET、minDCF、actual Bayes error 和 calibration 的关系。NIST SRE21 用 actual cost 作为 primary、minimum cost 作为补充，这正是为了不把“排序好但阈值失准”算作完整成功。

### 3.2 不能只报 EER

假设业务需要 `FAR <= 0.1%`，模型的 EER 即使只有 2%，也不能推出这个工作点的 FRR、置信区间或跨域稳定性。商用验收至少要冻结：

1. target prior 或业务事件频率；
2. false accept 与 false reject 的业务成本；
3. 一个开发集上选定并冻结的阈值/校准器；
4. 一个 speaker 不重叠、音频不重叠的 blind test；
5. 关键工作点 FAR、对应 FRR、置信区间；
6. overall 与条件分桶的 actual DCF/Cllr；
7. FTE、FTA、无分数率、延迟和资源开销。

### 3.3 样本量与统计可信度

低 FAR 声明需要大量、且统计结构合理的 non-target trials。把少数几个人的录音做笛卡尔积可以制造很多 pair，但这些 pair 高度相关，不能当成同等数量的独立人群证据。应以 speaker/session 为抽样单元做 bootstrap 或分层置信区间，并保证 calibration/dev/test 的 speaker 隔离。

[ISO/IEC 19795-1:2021](https://www.iso.org/standard/73515.html)要求记录测试数据、报告结果、减少数据采集/分析偏差，并明确测试结果的适用边界。[FIDO Biometrics Requirements v4.1](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html)则给出一个可操作但特定于 FIDO authenticator 的例子：不同 BioLevel 使用 25 或 245 个 FAR/FRR subjects，实验室 FAR/FRR、self-attested FAR 和置信区间都有独立要求。它可以用作工程严谨度参照，但不能直接替代鼎桥业务自己的协议。

## 4. 当前系统的根因层能力边界

### 4.1 已经具备的能力

| 能力 | 当前状态 | 能证明什么 |
| --- | --- | --- |
| 端侧 speaker embedding | 内置约 38 MB ERes2Net ONNX | 能从达到时长门槛的音频提取固定维 embedding |
| 多段注册 | API 最低允许 1 段；传入多段时 `SpeakerEnroller` 对 raw embedding 求均值后 L2 normalize | 同一人的多个注册样本可以形成一个 centroid；当前接口/UI 不强制商用品质的跨 session 注册 |
| 余弦分数 | Harmony/Android 均有 cosine 实现 | 能提供 target/test embedding 的角度相似度 |
| 时长门槛 | 默认 `minSegSec=1.5s`；不足时省略分数 | 避免对极短片段伪造分数 |
| 生命周期门禁 | 已覆盖 cold/warm、fallback、final/last/complete 等 | 能证明接口与回调契约；不证明身份精度 |
| 目标人离场辅助切句 | Speaker VAD 对滑窗分数做状态机判断 | 在限定数据上可减少非目标音频拖尾；不是多说话人分离 |

当前 Android 资产与已构建的 Harmony HAP 中模型 SHA-256 都是 `1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b`。这能证明两端检查到的模型文件一致，不能证明两端 scorer、PCM 边界或最终 FAR/FRR 一致。

仓库已有文档已经正确区分了两类证据：

- `VOICEPRINT_DURATION_RELEASE_GATE.md` 和 `VOICEPRINT_DURATION_REGRESSION_EVIDENCE_20260717.md` 只证明应有分数、生命周期与资源边界，不比较 target/non-target 精度；
- `asr/tools/speaker/README.md` 记录的合成强重叠集曾得到 `EER=7.36% @ threshold=0.26`，并明确没有通过内部 `EER <= 5%` 的阶段门。但当前仓库只保留 README 摘要，所引用的 raw JSONL 与 summary 不在版本库/本地结果目录；其 328 个 negative 又混合了 164 个 `negative_distractor` 与 164 个 `negative_silence`，不是标准的纯 impostor speaker-verification trial。因此这只能作为待复核的风险信号，不能作为可复算的标准 EER 或商用证据。以 328 个负例估计低 FAR 也远远不够：摘要中的 0.91% 约等于 3 次误接收，Wilson 95% 区间约为 0.31%–2.65%；3.96% 约等于 13 次，区间约为 2.33%–6.66%。
- `docs/speaker/AIDATATANG_SPEAKER_VAD_EVAL.md` 的 500 人实验使用目标人的**同一条 utterance**同时注册和测试，原文已经注明 target 确认率偏乐观。它可验证 Speaker VAD 状态机在人工拼接的 target→other 序列上的相对行为，不能证明跨 session、跨设备注册泛化或身份核验精度。

### 4.2 分数语义现状

当前 `speakerSimilarity` 是 raw cosine，而不是：

- 0–1 的 UI 百分制；
- 同一人的 posterior probability；
- NIST 定义的 LLR；
- 已在客户域冻结阈值后的 accept/reject 决策；
- 对回放、合成或注入的真实性判断。

当前 Dingqiao 封装还显式使用 `SCORE_ONLY_THRESHOLD=-1`（Harmony 同样把核验 threshold 设为 `-1.0`），目的是不在 SDK 内拒绝 final，而是把分数交给客户业务侧判定。因此现状准确说是“**端侧 embedding + score 输出**”，不是一个已经冻结工作点、能独立作出身份认证决定的 verifier。把 raw cosine 映射到 0–1 不会补上这个决策层。

如果客户现有材料或调用代码把 `speakerSimilarity` 假定为 `[0,1]`，它与当前实现的理论范围 `[-1,1]` 存在契约冲突。这需要显式做兼容决策：保留 raw 字段并修正文档，或新增 display/calibrated 字段；不能静默改变旧字段，因为阈值数值与历史结果会同时失效。

在保持公共字段名 `speakerSimilarity` 不变的前提下，建议把接口语义和决策元数据拆开：

```text
speakerSimilarity       # 继续承载原始 cosine；范围和版本必须明确
speakerScoreScale       # RAW_COSINE；避免调用方把它误认成概率
speakerDecision         # TARGET / NON_TARGET / INSUFFICIENT_QUALITY
decisionPolicyVersion   # 模型、校准器、阈值、条件策略的版本
```

`speakerSimilarity` 的文档必须明确其范围、非概率语义、模型版本和阈值不可跨域照搬。若内部增加 LLR calibrator，应由版本化的 `speakerDecision` 消费，不要静默改写既有字段语义。UI 可另做 `displaySimilarity=(s+1)/2`，但不能命名为“置信度”或“认证概率”。

### 4.3 当前模型本身的证据边界

仓库 NOTICE 将当前模型标识为 `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`；上游同名模型位于 3D-Speaker 的 ERes2Net-base recipe。上游公开的是研究 benchmark，不是以下事项的证明：

- 鼎桥设备麦克风、codec、增益、距离和噪声下的 FAR/FRR；
- 1.5 秒 final 或实时滑窗的低 FAR 性能；
- 客户目标人口、方言、年龄、性别和身体状态的公平性；
- 录音回放、TTS/VC、deepfake 或音频注入抵抗；
- 任何 FIDO/ISO 合规或第三方认证；
- 司法鉴定用途。

### 4.4 Harmony/Android 同阈值风险需专项确认

源码检查发现需要进一步做同 PCM 差分验证：Android `SpeakerVerifier.segmentScore` 对长段采用多滑窗并取最大 cosine；Harmony `Runtime.applyTargetSpeaker` 当前可见路径对传入整段做一次 cosine。二者可能形成不同 score distribution，导致同一个阈值在两端的 FAR/FRR 不一致。只有在确认两端最终传入的 PCM 边界和其他上层逻辑等价后，才能排除此风险。

这不是“归一化”问题，而是 scorer 定义问题。商业校准必须绑定 scorer 版本；任何 `whole-segment -> max-window`、VAD、降噪、音量、采样率或 enrollment 聚合变化，都应触发重新验证，必要时重新校准。

### 4.5 多 `voiceprintIds` 的业务语义风险

当前 `loadMergedEmbedding(ids)` 会把多个 ID 的 embedding 求均值后再归一化。如果这些 ID 是**同一个人的多次注册**，centroid 语义合理；如果业务把它理解为“多个可接受目标人”，这种合并不等同于对每人独立打分后取 max，会生成一个可能不接近任何人的虚拟中心。接口必须明确：

- 一个 voiceprint ID 应代表一个 identity；
- 同一 identity 的多会话样本在注册内部合并；
- 多 identity 验证应返回 per-identity score 或做明确的 1:N 决策，不能把身份模板混成一个向量。

## 5. 主要商用风险矩阵

| 风险 | 根因层 | 可能后果 | 当前级别 | 优先缓解 |
| --- | --- | --- | --- | --- |
| 用途未定义 | 产品/决策 | 过滤、认证、取证用同一“准确率”验收 | 严重 | 先冻结 use case、攻击模型、prior/cost 和回退 |
| 0–1 映射被当概率 | 分数语义 | 阈值误用、客户误解、无法审计 | 高 | raw/display/LLR/decision 分层 |
| 无客户域校准 | 决策 backend | 开发集阈值现场漂移 | 严重 | 身份标注 in-domain dev/test、冻结校准器 |
| 域偏移 | 模型/数据 | 设备、距离、语言、情绪、疾病、codec 使 FAR/FRR 上升 | 严重 | 场景矩阵、augmentation、domain adaptation、条件监控 |
| 1.5 秒短语音 | 信息量 | phonetic coverage 少、embedding 方差大 | 高 | 最低有效语音、累计多句、质量感知校准、短时模型 A/B |
| 非语音/低 SNR/混响 | 前处理 | 假分数、漏验、阈值漂移 | 高 | speech quality gate、有效语音时长/SNR/reverb 分桶 |
| 多人和重叠语音 | state boundary | 目标人出现使整段通过，同时放行他人内容 | 严重 | diarization、overlap detection、分离或按 speaker-homogeneous segment 验证 |
| 回放/TTS/VC/deepfake | 安全/PAD | 攻击者用目标人录音或克隆音频通过 | 严重 | 独立 CM/PAD、挑战响应、融合、攻击集门禁 |
| 音频注入/绕过采集 | 系统安全 | 绕过麦克风侧 PAD | 严重 | capture attestation、secure path、注入威胁建模 |
| 注册污染 | enrollment | 错人、多人、回放或低质样本形成永久坏模板 | 严重 | 注册活体、单说话人/质量检查、多会话、人工/二因子绑定 |
| 多 ID 均值语义 | 模板/决策 | 多人模板形成虚拟 identity | 高 | identity-level template 与 1:N scorer 分离 |
| 模板泄露和不可撤销 | 隐私/安全 | embedding 被复制、关联或反复滥用 | 严重 | 加密、访问控制、可撤销模板、删除审计、最短留存 |
| 指标方差与数据泄漏 | 评测 | 漂亮数字不可复现、speaker overlap 泄漏 | 高 | speaker-disjoint blind test、subject bootstrap、artifact |
| 模型/阈值升级漂移 | 演进 | 新版本 silent regression | 高 | policy version、shadow test、阈值迁移和回滚 |

## 6. 短语音、噪声、域偏移和多人场景

### 6.1 短语音不是一个固定 magic number

当前 `minSegSec=1.5s` 是“允许尝试提 embedding”的工程门槛，不是“1.5 秒已经可靠”的统计证明。上游 ERes2NetV2 论文明确以短时退化为问题：其 VoxCeleb1-O EER 从 full-duration 0.61% 变为 3 秒 0.98%、2 秒 1.48%；该数字来自干净 benchmark，而且用的是比当前 ERes2Net-base 更新的 V2。[ERes2NetV2 原论文](https://arxiv.org/abs/2406.02167)

建议把以下值分开：

- `extractor minimum`：模型能否算出 embedding；
- `decision minimum`：该场景是否允许作身份决策；
- `high-assurance minimum`：高风险动作是否需要累计更多有效语音或二因子；
- `speaker-vad window`：实时状态机的响应时间，而非 final 认证时长。

可优化方式包括累计多句 target evidence、以有效语音而非文件/PCM 总时长计时、duration-aware calibration，以及使用专门为短时优化的模型做 A/B。不能只把 1.5 秒改成另一个未经评测的数字。

### 6.2 噪声和信道

CN-Celeb 的 multi-genre 研究把 speaking style、physiological status、设备和背景噪声列为组合型 session variation；NIST SRE21 也把 source type、phone number 和 language match 当成正式条件分区。这意味着“总体一个 EER”会掩盖最差域。[CN-Celeb 原论文](https://arxiv.org/abs/2012.12468)、[NIST SRE21](https://www.nist.gov/system/files/documents/2021/07/12/2021_SRE_Evaluation_Plan_V5.pdf)

必须至少按以下维度报表：

- 设备型号/麦克风、采样率/codec；
- 近讲/远讲、距离、朝向；
- SNR、混响、交通/人群/音乐/babble；
- 普通话/方言/中英切换；
- 正常/耳语/喊话/情绪/疲劳/感冒；
- enrollment/test 同设备与跨设备、同 session 与跨 session；
- 1.5–2s、2–3s、3–5s、5–10s、10s+ 有效语音。

### 6.3 多说话人和 overlap

speaker verification 的标准 trial 是“某个 enrollment identity 与一个 test segment 是否同一 speaker”。当 test segment 同时包含两个人时，一个固定维 embedding 无法给出每一帧/每个词的归属。3D-Speaker 官方 diarization pipeline 本身就把 overlap detection、VAD、segmentation、speaker embedding 和 clustering 列为多个独立模块，而不是只用 embedding 完成全部任务。[3D-Speaker 官方仓库](https://github.com/modelscope/3D-Speaker)

对当前 ASR 产品尤其要警惕“target-present”与“target-only”混淆：

- max-window cosine 只要找到一个很像目标人的窗口，就可能让包含非目标人内容的整段通过；
- whole-segment cosine 在重叠时又可能被他人污染，导致目标人被拒绝；
- Speaker VAD 可以缩短非目标人拖尾，但不会把同时讲话的两个声源拆开。

如果客户要求“只输出目标人的每个字”，需增加 speaker-homogeneous segmentation、overlap detection，必要时 target speaker extraction/source separation，并在 ASR 文本层做 speaker attribution。不能把它包装成 score normalization 优化。

## 7. 反欺骗、回放与 deepfake 是独立能力

### 7.1 裸 speaker embedding 不判断“真人正在说话”

FIDO v4.1 对 voice 明确列举：

- Level A：普通录音回放；
- Level B：特定短语录音、剪接、高质量回放、易获得的 voice synthesizer；
- Level C：更复杂的 voice synthesizer 和 impersonation。

它还提醒 text-independent 系统可能被“任何录音”攻击，而 text-dependent 系统至少要求特定 passphrase。[FIDO Biometrics Requirements v4.1，Voice PAI](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#p-pai-species-for-voice)

ASVspoof 5 则把系统拆成 stand-alone deepfake detector 和 spoofing-aware speaker verification（SASV），并允许独立 ASV 与 countermeasure 融合；评测数据包含针对 ASV/CM 优化的对抗攻击，指标使用 DCF/a-DCF/t-DCF，而不是只看 speaker cosine。[ASVspoof 5 官方 Phase 2 Evaluation Plan](https://www.asvspoof.org/file/ASVspoof5___Evaluation_Plan_Phase2.pdf)

### 7.2 商用安全路径

若用途涉及登录、支付、授权、执法身份确认或其他高后果动作，最低限度应是：

```text
capture integrity / anti-injection
            ↓
speech quality + bona-fide/PAD countermeasure
            ↓
speaker verification (calibrated)
            ↓
optional random phrase / challenge-response / ASR content check
            ↓
rate limit + device/account binding + second factor + audit
```

PAD 也不是“一次加上就永久安全”。[ISO/IEC 30107-3:2023](https://www.iso.org/standard/79520.html)规定 PAD 评测和报告方法，但明确不等同于整体系统安全/漏洞评估；捕获设备之外的注入攻击也超出该标准的 presentation-attack 范围。因此需要单独维护回放设备、codec、TTS/VC、未知生成器和注入攻击矩阵。

对于数字身份认证，还应采用更保守的边界：NIST SP 800-63B-4（2025）的认证指南明确规定不得使用基于声音的生物特征比较。该要求针对美国联邦数字身份体系，不是对所有行业和所有国家的普遍法律禁令；但它足以说明，不能把当前 raw cosine 能力包装成通用或单因子认证方案。[NIST SP 800-63B-4，Use of Biometrics](https://pages.nist.gov/800-63-4/sp800-63b.html#biometrics)

### 7.3 FIDO 数字只能作为参照，不能冒充当前认证

FIDO v4.1 的 BCC 各级同时要求 FAR、FRR 和 IAPAR；例如 BioLevel 2/2+ 的 lab-tested IAPAR 要求 7%，BioLevel 2/2+ 的 FAR 规则达到 `1:10,000` 的置信区间要求，并规定 fixed operating point、攻击 species 和实验室流程。[FIDO v4.1 要求表](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#biometric-requirements-by-levels)

但 FIDO BCA 的上下文是 authenticator biometric component，测试对象包含 capture、signal processing、comparison 和 decision，且由 accredited lab 执行。当前 SDK 只有其中一部分，所以可以采用其严谨度和攻击分类，不能声称已符合或已认证。

## 8. 隐私、模板保护与治理

声纹原始音频和 embedding 都必须按生物识别信息治理。中国网信办 2026 年个人信息保护问答明确把声纹列为敏感个人信息示例；《个人信息保护法》要求敏感个人信息只有在特定目的、充分必要、严格保护措施等条件下处理，并涉及单独同意、告知、影响评估等义务，具体适用需由法务结合客户主体和执法依据判断。[网信办 2026 问答](https://www.cac.gov.cn/2026-01/09/c_1769688003183197.htm)、[《个人信息保护法》官方文本](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm)

[ISO/IEC 24745:2022](https://www.iso.org/standard/75302.html)对 biometric information 的 confidentiality、integrity、renewability/revocability、存储/传输和隐私处理提出框架要求。对应当前 SDK，应至少评审：

源码当前把模板写成 `embedding.bin`（little-endian `int32 dim + float32[]`），未见 SDK 层静态加密、完整性校验或可撤销模板变换；当前链路也未见独立 PAD/反欺骗模块。这些是当前能力缺口，不只是未来增强项。

- workPath 中 `embedding.bin` 是否静态加密，密钥是否与应用数据分离；
- 模板是否绑定 tenant/device/account，是否防目录复制和跨设备重放；
- 谁能列出、读取、导出、删除模板，是否有审计；
- 删除是否覆盖备份、日志和派生数据；
- 模板泄露后如何 revoke/re-enroll，而不是继续使用同一个不可变生物特征；
- 原始 enrollment WAV 是否保留，保存期限和目的是什么；
- 模板升级/模型替换时旧新 embedding 能否关联，如何迁移和回滚。

准确率达到门槛但模板明文可复制，仍不能称为完整商用系统。

## 9. 当前框架内的优化层级

### 9.1 P0：不换模型也必须先做的事情

这些工作不会改善 embedding 本身，但能把未知风险变成可验收产品：

1. 冻结三类用途之一：辅助分数、目标人过滤、身份认证；不要混合验收。
2. 明确 raw cosine 范围和非概率语义；显示映射与决策分离。
3. 建立客户域 speaker-disjoint 的 enrollment/dev/blind-test 数据；保存 PCM、元数据、trial key、score 和版本。
4. 报 ROC/DET、EER、关键 FAR 下 FRR、minDCF、actual DCF；做 LLR 时再报 Cllr。
5. 选阈值只用 dev，blind test 不再调参；threshold/policy 与模型、平台、scorer 绑定版本。
6. 将无分数/质量不足作为独立结果，不把它当 reject 后从分母消失。
7. 做同 PCM Harmony/Android score parity 和分帧无关测试。
8. 明确多 ID 是同 identity 多 session，还是多 identity；修正错误聚合语义。

完成 P0 前，不能通过修改 `speakerSimilarity` 显示范围向客户宣称问题已解决。

### 9.2 P1：同模型、低改动、通常收益最高

| 优化 | 原理 | 验收方式 | 主要代价 |
| --- | --- | --- | --- |
| 多 session enrollment | 平均掉单次设备/状态偶然性 | 1/3/5 段 A/B，跨 session blind test | 注册交互更长 |
| enrollment quality gate | 拦截静音、多人、低 SNR、削波和回放 | FTE 与后续 FAR/FRR 联合看 | 更多重录 |
| 有效语音累计 | 短句先不决策，累计证据 | duration bucket、time-to-decision | 决策延迟增加 |
| logistic LLR calibration | 让阈值具备 prior/cost 语义 | actual DCF、Cllr、calibration plot | 需要有标签 dev 数据 |
| quality-aware calibration | 用时长、SNR、embedding norm 等适配条件 | held-out domains 的 Cllr/actual DCF | 模型/策略复杂度增加 |
| cohort score normalization | 补偿一部分 cohort 条件差异 | 与 raw cosine 同集 A/B | cohort 存储/算力、隐私 |
| per-condition reject/abstain | 不在证据不足时硬判 | coverage-risk curve | coverage 下降 |

注意：普通正斜率 affine calibration 是单调变换，通常改善 calibration/actual cost，不改善 EER；如果质量感知变换根据 trial 条件改变排序，才可能同时改善 discrimination，但也更容易过拟合，必须跨域 blind test。

### 9.3 P2：模型与 backend A/B

候选顺序应以同一客户 blind test 决定，而不是只看公开榜单：

1. 当前 ERes2Net-base + cosine，作为不可移动 baseline；
2. 当前模型 + 更合适的 length normalization/PLDA-diag 或 discriminative backend；
3. ERes2NetV2，重点看 1.5–3 秒桶；
4. 官方 200k-speaker ERes2Net/ERes2NetV2/CAM++；
5. 在有足够合规 in-domain 数据后做 domain adaptation 或 fine-tuning；
6. 多模型 fusion 只在单模型误差互补且成本允许时进入。

[Large-margin embedding scoring 原论文](https://arxiv.org/abs/2204.03965)表明，cosine 对 large-margin embedding 可以是强 baseline，但经过约束的 PLDA backend 在其实验中仍平均优于 cosine，EER/minDCF 分别相对降低 10.9%/4.9%。这不是保证当前 ERes2Net 也有同样收益，而是说明“cosine 是唯一正确 backend”也不成立，值得用客户域数据 A/B。

### 9.4 P3：超出 embedding-only 的架构升级

- 多人/重叠：diarization、overlap detection、source separation/target speaker extraction；
- 高安全认证：PAD/CM、random phrase、ASR phrase check、多因子和安全采集链；
- 大规模 1:N：per-identity indexing、候选召回、每 identity calibration 和 watchlist-specific evaluation；
- 司法/取证：population-representative LR framework、case-relevant calibration、可解释报告与专家流程。

这些不是“优化阈值”能解决的问题，应独立立项和验收。

## 10. 建议的客户域验收协议

### 10.1 先签字确认的产品契约

```text
Use case:
  [ ] 仅显示辅助相似度
  [ ] 目标说话人过滤/切句
  [ ] 身份认证/授权

Decision unit:
  一句 / 一个 speaker-homogeneous segment / 累计 N 秒 / 整个 session

Population and environment:
  用户数量、语言/方言、设备、距离、噪声、codec、是否多人/重叠

Threat model:
  zero-effort impostor / replay / cut-paste / TTS / VC / mimicry / injection

Business costs:
  false accept、false reject、abstain、超时分别造成什么后果

Fallback:
  PIN/人工/二因子/保留 ASR 文本但不做身份结论
```

### 10.2 数据划分

- enrollment、calibration/dev、blind test 按 identity 隔离；
- 同一原始录音的切片不得跨集合；
- 同一 session 不得同时支撑阈值选择和最终报告；
- 每人至少跨 session、跨日、跨设备/距离采集；
- non-target 包含随机人、同语言/方言、同性别、相近音色等 hard negatives；
- 多人/重叠单独形成 attribution set，不混入单人 SV 后只报一个 overall；
- PAD 集按攻击 species、设备、codec、已知/未知生成器拆分。

### 10.3 必须报告的矩阵

| 类别 | 指标 |
| --- | --- |
| discrimination | ROC/DET、EER、minDCF |
| deployed decision | frozen-threshold FAR/FRR、actual DCF、coverage、无分数率 |
| calibration | Cllr/Cllr_min、reliability/Bayes error plot（若输出 LLR/概率） |
| quality | 按 duration、SNR、distance、device、language、session mismatch 分桶 |
| multi-speaker | target-only、target+other sequential、overlap 各自 FAR/FRR/泄露时长 |
| spoof | replay/TTS/VC/cut-paste 各 species IAPAR 或 a-DCF/t-DCF |
| usability | FTE、FTA、重录次数、time-to-decision、p50/p95 latency |
| robustness | 冷热态、长时间、模型升级、平台 parity、离线/断网 |
| privacy/security | 模板静态/传输保护、权限、删除、审计、revoke/re-enroll |

### 10.4 Go/No-Go 不能先拍一个行业通用数字

最终门槛必须由客户业务损失和合规要求决定。可以设三级内部 gate，但数字需由双方签字：

- **辅助能力**：只显示或排序，不直接做高后果动作；重点是相关性、稳定性和不误导 UI。
- **目标人过滤**：在冻结环境下满足约定 FAR/FRR/coverage，并在不确定时保留/标记而非静默丢失；多人重叠另验收。
- **身份认证**：除低 FAR/可接受 FRR 外，必须通过独立 PAD、攻击、模板保护和系统安全门禁，并提供 fallback/限流。

不能用 `EER <= 5%` 自动推导“可商用”，也不能用一次 clean same-speaker/demo 成功自动推导“可认证”。

## 11. 按用途给出最终判断

| 用途 | 当前状态能否直接宣称商用 | 当前框架优化后的前景 | 关键缺口 |
| --- | --- | --- | --- |
| UI 显示相似度/调试 | **可以作为技术分数**，但不能叫概率 | 高 | 定义 raw/display 语义 |
| 限定场景目标人过滤、可人工回退 | **证据不足，暂不能** | **有条件可达** | 客户域 blind test、阈值/校准、注册质量、平台 parity |
| 嘈杂多人场景的逐字 speaker attribution | **不能** | embedding-only 仍不能；需架构升级 | diarization/overlap/分离/归属 |
| 单因子身份认证或授权 | **不能** | 只有加入 PAD、挑战/二因子、安全链后才有评估资格 | replay/deepfake/injection、低 FAR、模板保护 |
| 司法/证据级说话人比较 | **不能** | 需独立 forensic LR 与专家流程 | population data、LLR calibration、case protocol |

最稳妥的对外表述是：

> 当前 SDK 已具备端侧 speaker embedding 和 raw cosine 打分能力，接口与生命周期已完成工程门禁；声纹判别精度、客户域阈值和反欺骗尚需按具体用途完成身份标注评测与系统级验收。0–1 显示映射不等于概率校准，也不构成商用精度证明。

## 12. 推荐决策与主 trade-off

推荐先把目标定为“**限定场景的目标说话人辅助/过滤能力**”，而不是直接承诺“商用级身份认证”。按 P0 → P1 建立证据后再决定是否换模型或扩展 PAD。

主 trade-off 是：提高安全阈值会降低 FAR，但会提高 FRR、无结论率和决策延迟；积累更多有效语音、多 session enrollment 和二因子能降低风险，但牺牲交互速度；多人重叠若追求逐字归属，则必须付出额外模型、时延和端侧资源成本。

这条路线的停止条件应是：同一冻结版本在客户 blind test 达到约定工作点及置信区间，关键条件没有不可接受的最差桶，且风险用途需要的 PAD/隐私门禁全部通过。达不到时，应诚实收缩场景或增加架构能力，而不是继续调 0–1 映射。

## 13. 一手来源清单

### 模型与算法

- [3D-Speaker 官方仓库与 benchmark](https://github.com/modelscope/3D-Speaker)
- [3D-Speaker 官方 ERes2Net recipe、训练目标和跨设备/距离/方言结果](https://github.com/modelscope/3D-Speaker/tree/main/egs/3dspeaker/sv-eres2net)
- [An Enhanced Res2Net with Local and Global Feature Fusion for Speaker Verification](https://arxiv.org/abs/2305.12838)
- [ERes2NetV2: Boosting Short-Duration Speaker Verification Performance with Computational Efficiency](https://arxiv.org/abs/2406.02167)
- [Scoring of Large-Margin Embeddings for Speaker Verification: Cosine or PLDA?](https://arxiv.org/abs/2204.03965)
- [CN-Celeb: multi-genre speaker recognition](https://arxiv.org/abs/2012.12468)
- [A Speaker Verification Backend with Robust Performance across Conditions](https://arxiv.org/abs/2102.01760)

### 指标、评测与标准

- [NIST 2021 Speaker Recognition Evaluation Plan](https://www.nist.gov/system/files/documents/2021/07/12/2021_SRE_Evaluation_Plan_V5.pdf)
- [The BOSARIS Toolkit: Theory, Algorithms and Code for Surviving the New DCF](https://arxiv.org/abs/1304.2865)
- [Application-independent evaluation of speaker detection](https://doi.org/10.1016/j.csl.2005.08.001)
- [ISO/IEC 19795-1:2021 — Biometric performance testing and reporting](https://www.iso.org/standard/73515.html)
- [ISO/IEC 30107-3:2023 — Presentation attack detection testing and reporting](https://www.iso.org/standard/79520.html)
- [FIDO Biometrics Requirements v4.1](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html)
- [ASVspoof 5 Phase 2 Evaluation Plan](https://www.asvspoof.org/file/ASVspoof5___Evaluation_Plan_Phase2.pdf)
- [NIST SP 800-63B-4 — Digital Identity Guidelines: Authentication and Authenticator Management](https://pages.nist.gov/800-63-4/sp800-63b.html)

### 隐私与治理

- [ISO/IEC 24745:2022 — Biometric information protection](https://www.iso.org/standard/75302.html)
- [中华人民共和国个人信息保护法（官方文本）](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm)
- [国家网信办个人信息保护政策法规问答（2026 年 1 月）](https://www.cac.gov.cn/2026-01/09/c_1769688003183197.htm)
