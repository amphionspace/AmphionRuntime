# 交通执法场景机主声纹评测集规范

## 1. 要解决的问题

本评测集用于回答：在交通执法的真实采集链路下，冻结版本的 SDK 能否在同一工作阈值上可靠保留机主语音、拒绝非机主语音，并在重叠讲话时达到约定的端到端指标。

它不把办公室测试结果外推为交通场景结论，也不把余弦相似度的显示归一化当作精度改善。

## 2. 评测原则：用途和风险优先，不以客户拍定数字反推测试

客户提出的“97%/70%”只保留为候选报告点。在 decision unit、错误代价、目标出现先验和“不决策”处理没有定义前，它们不是可执行指标，也不能决定样本构成或商用结论。

### 2.1 先冻结产品用途和决策代价

预注册协议必须先回答：

- 能力是辅助显示、可回退的目标说话人过滤，还是身份认证/授权；
- decision unit 是一句、speaker-homogeneous segment、累计有效语音，还是整个 session；
- 误接收非机主、误拒绝机主、不决策和延迟分别造成什么业务后果；
- 真实运行中机主/非机主 trial 的先验比例来自什么数据；
- 低质量、无分数和多人重叠时是保留并标记、人工复核，还是自动丢弃。

阈值应由上述 prior/cost 与 dev 数据共同选择，并与模型、scorer、注册策略和平台版本绑定。不能为了接近客户数字在 blind 上反复移动阈值。

### 2.2 分开讲话的主指标

在同一个冻结工作点上报告：

- **FAR/误接收率**：只有非机主讲话时被采纳为机主的比例；
- **FRR/误拒绝率**：机主讲话时被拒绝或无法形成所需决策的比例；
- **coverage/abstention**：可决策覆盖率和主动不决策率；
- **actual DCF 或业务期望损失**：按预注册的 prior/cost 汇总实际工作点代价；
- ROC/DET、EER 和 minDCF 作为 discrimination 与诊断指标，不直接等同商用通过。

如果还评测 ASR 内容，则另外报告目标字符 CER、警务实体召回和非机主内容 leakage。说话人判断和文字识别不能混成一个“准确率”。

### 2.3 同时讲话是独立能力轨道

当前 speaker embedding + cosine 只能判断一个混合片段“像不像机主”，不能把同一时刻两个人的每个字分开。重叠场景必须作为**端到端目标说话人 ASR**独立评测，至少报告：

- 重叠区机主字符准确率 `1 - target_CER`；
- 机主语音保留率；
- 非机主字符泄漏率；
- overlap-aware speaker attribution F1 或 DER；
- 无分数率与覆盖率。

只看 `speakerSimilarity` 是否超过阈值，不能证明重叠讲话能力。客户的 70% 只在双方先定义指标后作为参考点报告；若现有架构不足，应立项 overlap detection、diarization 或 target-speaker extraction，而不是调分数范围。

## 3. 数据集分层和规模

### 3.1 固定分层，不固定通用人数

| 数据层 | 用途 | 是否允许调参 |
| --- | --- | --- |
| pilot | 跑通采集/标注/评分，估计说话人和 session 间方差 | 可以，不对外声明 |
| dev/calibration | 选模型、阈值、校准器、质量门和注册策略 | 可以 |
| blind test | 验证冻结系统、工作点和预注册假设 | 不可以，只运行一次 |
| office diagnostic | 与交通域做同人配对，量化 domain shift | 不参与阈值选择和商用结论 |

不存在对所有声纹用途都正确的“200 人、4000 条”固定答案。人数、正负 trial 和困难桶规模必须在 pilot 后，根据下列因素做 power analysis 并写入冻结协议：

- 主指标是 FAR、FRR、DCF、CER 还是 leakage；
- 需要分辨的最小实际差异和置信区间宽度；
- 运行先验、错误代价和允许的最大误差；
- 说话人、session、地点和设备造成的 cluster correlation；
- 必须独立报告的最差场景桶数量；
- 是否需要证明低 FAR。零错误时，独立二项近似的单侧 95% 上界约为 `3/N`，所以低 FAR 声明通常需要远多于一般准确率评测的负 trial。

pilot 规模以能够稳定估计主要 cluster 方差并暴露采集失败模式为停止条件，而不是预设固定人数。正式报告使用 speaker/session-aware cluster bootstrap；不能通过少量录音的 enrollment × probe 笛卡尔积制造虚假样本量。

## 4. 人员、session 与注册协议

- pilot、dev 和 blind 的 `speaker_id` 完全隔离。
- dev 与 blind 都必须覆盖目标用户总体；非机主从同一总体招募，不能只用明显不同性别或年龄的“容易负样本”。具体人数由 pilot 功效分析决定。
- 每位机主需要多个独立注册/probe session 和跨日采集，数量在预注册协议中冻结，且足以估计 session variation。
- 每个 identity 采集多段、内容不同的注册音频，支持“当前产品注册流程”和“多 session 优化版”A/B；正式验收使用哪几段必须在 blind 前冻结，不能用优化版结果替当前产品背书。
- 注册环境必须复刻真实产品流程。若警员通常在办公室注册，则主实验使用“办公室注册 -> 交通现场 probe”；另做“交通注册 -> 交通 probe”只能作为优化对照。
- 注册音频和 probe 不得来自同一原始录音、同一切片或同一次连续录制。
- speaker ID 必须是假名化随机 ID；真实身份映射单独加密保管，不进入评测仓库。

## 5. 交通场景采集矩阵

盲测按真实部署占比加权，同时保证困难桶有足够样本。建议最少覆盖：

| 维度 | 建议桶 |
| --- | --- |
| 场景 | 路肩检查、路口/卡点、车辆外对话、车窗开启的车内外对话、警车/社会车辆内 |
| 背景 | 稳态车流、车辆加速/鸣笛、大车经过、警笛/对讲机、人群 babble、雨声 |
| SNR | `>=15 dB`、`5–15 dB`、`0–5 dB`、`<0 dB`；自然权重来自部署调查，困难桶另设最低证据量 |
| 风 | 无/弱、中、强或阵风；权重来自部署地点和季节数据 |
| 机主距离 | 真实佩戴位 0.2–0.6 m；手持形态按产品实际距离另分桶 |
| 非机主距离 | 0.8–3 m 为主，另含近距离抢话/围观者 |
| 有效语音时长 | `<1.5 s`、1.5–2 s、2–3 s、3–5 s、>5 s；短语音作为质量/abstain轨道保留 |
| 语言 | 普通话、当地主要方言、口音普通话、中英/字母数字混说 |
| 说话状态 | 正常、快速、喊话、低声、情绪激动；口罩/头盔按实际比例 |
| 硬件 | 所有交付设备型号、麦克风批次、佩戴位置、系统版本 |
| 时间/地点 | 白天/夜间，不同道路和至少一个未出现在 dev 的 blind 地点 |

内容同时覆盖随机警务脚本和半自由角色扮演，权重按真实业务话语分布冻结。注册文本与 probe 文本不同。相同脚本可用于办公室/交通配对实验，但不能让标注员根据脚本自动填充未听清内容。

## 6. 分开、连续和重叠样本

三类样本必须分别保存和报告：

1. `separate`：一个决策单元只有一名说话人，是标准 speaker verification 主评测集。
2. `sequential`：机主与非机主前后接续但不重叠，用来测 endpoint、Speaker VAD 拖尾和错误合段。
3. `overlap`：两人同时有声，至少含 10–30%、30–50%、>50% 三个重叠比例桶。

负样本必须是真实非机主语音，包含：随机负样本、同性别/近年龄/同方言、相似音色、同一场景近距离高信噪比的 hard negatives。纯静音、环境噪声和无语音文件只进入 VAD/接口质量集，不进入声纹 FAR/TNR 分母。

若用途上升为身份认证/授权，回放、剪接、TTS、VC、模仿和采集链注入必须建立独立攻击/PAD 集并使用相应攻击指标；不能把这些样本混入普通 zero-effort impostor 后只报一个 FAR，也不能用本目标说话人过滤集替代安全认证评测。

## 7. 标注与复核

每条 probe 至少标注：

- 说话人匿名 ID、机主/非机主角色；
- 每个 turn 的起止时间和逐字参考文本；
- 每段 overlap 的起止时间；
- 可听语音时长、目标语音时长、非目标语音时长；
- 场景、距离、设备、佩戴位置、SNR、风和车流等级；
- 削波、丢帧、遮挡、设备摩擦、标注不确定性等质量标记。

另设受保护的 subject registry，以 `speaker_id` 为键保存年龄段、性别、主要语言/方言、地区和角色等分层字段。该表不保存姓名、警号或身份证号，不随普通评测 artifact 分发；最终报告只给聚合桶和小样本抑制后的统计。

盲测标注在模型推理前完成。对按场景分层抽取的样本做双人独立标注，抽样量以说话人身份、文本和重叠边界的一致性置信区间为依据；存在分歧时交给第三人裁决。身份标签错误是最高风险错误，受试者/session/文件映射全部复核。

## 8. 数据切分与防泄漏

- `split=dev` 和 `split=blind` 之间不得共享 speaker、session、原始录音、音频 hash 或由同一原始音频产生的切片。
- 阈值、分数归一化、校准器、质量门和任何模型选择只能使用 dev。
- blind 在模型、scorer、平台实现和阈值全部冻结后只运行一次；失败后若继续调参，该集合自动降级为 dev，必须重建新 blind。
- 同一 blind 人员可同时录办公室与交通条件，以计算配对域差；二者仍属于 blind，不能用办公室结果调阈值。
- 必须保存 raw PCM、manifest、标注、SDK 输出、每条 `speakerSimilarity`、模型/hash、阈值、设备/系统版本和完整运行 artifact。

## 9. 预注册协议与商用决策

### 9.1 冻结项

运行 blind 前冻结：

- SDK/HAR/HAP、声纹模型和 ASR 模型的 SHA-256；
- Harmony/Android scorer 语义和窗口策略；
- 注册段数与聚合方式；
- `minSegSec`、decision unit、无分数策略；
- 唯一工作阈值或校准器版本；
- 文本归一化和 CER/泄漏计算代码版本。

### 9.2 Go/No-Go 的来源

商用条件不在本规范中预设统一百分比。冻结协议必须记录：

- primary metric、方向和 decision unit；
- prior/cost 的业务来源、fallback 和 coverage 要求；
- 允许的点估计/置信区间、关键最差桶和停止条件；
- pilot power analysis 得到的 dev/blind 人数、trial、session 和日期要求；
- overlap 是否在当前版本范围内，若在范围内使用什么端到端指标。

最终 Go/No-Go 以冻结工作点的 FAR、FRR、coverage、actual DCF/业务损失和关键条件置信区间共同决定。EER、ROC/DET 和 blind 上事后寻找的 best threshold 不能作为 pass。客户的 97%/70%可以并列报告，但不得凌驾于预注册的风险指标。

### 9.3 推荐实施路径

1. **定义范围**：冻结用途、decision unit、运行先验、错误代价、fallback 和 overlap 是否在本期范围。
2. **现场 pilot**：用交付设备采真实交通条件，先验证采集/标注链并估计 speaker/session/domain 方差。
3. **冻结 baseline**：保存当前模型、Harmony/Android scorer、注册方式和原始 `speakerSimilarity`，不先做显示归一化或事后挑阈值。
4. **分层归因**：分别检查采集质量、VAD/切段、短语音无分数、embedding discrimination、calibration、Speaker VAD 拖尾、ASR CER 和 overlap leakage。
5. **按根因优化**：优先 A/B 注册质量/多 session、有效语音累计、质量感知 abstain 和 dev 校准；区分力仍不足再比较 backend/模型；重叠逐字归属不足则进入 diarization/target-speaker extraction 独立项目。
6. **冻结候选并盲测**：先依据 pilot 完成功效分析和协议预注册，再锁定全部 artifact、阈值与报告代码运行一次 blind。
7. **影子部署**：先保留原始 ASR/音频和人工回退，观察真实 prior、最差桶、漂移与失败后果，再决定是否扩大自动决策范围。

## 10. 办公室与交通域差评估

对 blind 中同一批人员、同一设备和配对脚本分别录办公室与交通音频，使用交通 dev 冻结的同一阈值，报告：

- `TPR_traffic - TPR_office`、`TNR_traffic - TNR_office`；
- score 分布和无分数率的配对变化；
- 按 SNR、距离、风、场景的退化曲线；
- 置信区间和每位说话人的 paired delta。

办公室显著优于交通只说明存在 domain shift；不能用办公室结果覆盖交通不达标。若客户目前只给办公室数据，它适合接口联调和 clean-domain 上限估计，不足以验收交通部署。

## 11. Manifest 与校验

本目录采用一行一个录音事件的 JSONL：

- [manifest.schema.json](manifest.schema.json) 定义字段；
- [protocol.template.json](protocol.template.json) 定义预注册协议骨架；模板故意保持 `draft/null`，必须经 pilot 功效分析补全并冻结；
- [examples/manifest.example.jsonl](examples/manifest.example.jsonl) 给出最小示例；
- [validate_manifest.py](validate_manifest.py) 检查结构、身份/录音泄漏、标签一致性和验收规模；
- [test_validate_manifest.py](test_validate_manifest.py) 固化关键防泄漏断言。

结构检查：

```bash
python3 asr/evaluation/voiceprint_traffic/validate_manifest.py \
  asr/evaluation/voiceprint_traffic/examples/manifest.example.jsonl
```

正式验收门禁（会检查文件、hash、WAV 属性和最低规模）：

```bash
python3 asr/evaluation/voiceprint_traffic/validate_manifest.py \
  /secure/path/voiceprint-traffic-v1/manifest.jsonl \
  --dataset-root /secure/path/voiceprint-traffic-v1 \
  --check-files --acceptance \
  --protocol /secure/path/voiceprint-traffic-v1/protocol.frozen.json
```

这里的 `PASS` 只表示数据完整性、隔离和证据规模符合冻结协议，不表示模型性能或“商用”已经通过；性能结论由冻结评分器在 blind 上计算主指标后另行产生。

## 12. 现有本地语料的定位

当前机器已有：

- `aidatatang_test_spk_balanced_500`：可提供 500 人 clean speech 和初步跨说话人试验；
- `AISHELL3` 子集：可补充普通话说话人与文本；
- `ts_hw_test`：可做合成重叠和 pipeline 回归；
- `AudioSet_RoadTraffic_20h`：可作为道路噪声源；
- `tdtech_testdata`：可覆盖警务词、派出所和车牌 ASR 内容。

这些数据可以构成 **synthetic traffic pilot**，用于 SNR sweep、阈值初筛和发现明显实现错误，但不能进入正式 blind：独立录制后再混音缺少真实距离、混响、设备自动增益、风噪耦合、遮挡和现场说话行为，也不是交付设备的原始采集链。它们不能替代受控交通实景数据。

## 13. 交付前完成条件

- 产品方和客户先确认用途、decision unit、prior/cost、fallback、无分数处理和主指标；97%/70%只作为候选参考点；
- 采集协议通过个人信息、声纹模板和执法数据合规评审；
- pilot 证明录音链和标注一致，按 pilot 的 cluster 方差复核样本量；
- dev/blind 人员名单在采集前冻结并由独立人员保管；
- blind 执行者拿不到 dev 调参权限，研发只收到最终只读结果；
- 所有失败样本可回溯到 PCM、真值、设备、场景、模型、阈值和回调轨迹。

只有完成这些条件后，得到的数字才足以支持“限定交通执法场景是否达到商用指标”的决策。
