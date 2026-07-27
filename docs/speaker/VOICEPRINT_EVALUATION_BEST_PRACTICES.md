# 声纹与目标说话人能力：最佳实践评测路径

调研日期：2026-07-27

范围：说话人验证（speaker verification）、非重叠目标说话人检测/过滤、重叠语音中的目标说话人 ASR，以及必要时的反欺骗评测。本文只回答“怎样建立可信证据”，不接受客户随意给出的 `97%`/`70%` 作为测试集设计依据，也不预判当前模型一定能或不能达到某个工作点。

方法：优先使用 ISO 官方标准页面、NIST 官方评测计划与统计报告、FIDO 正式生物组件要求、ASVspoof 官方计划和原始论文。FIDO 指标是认证场景的规范实例，不是本项目应照抄的门槛；NIST/公开挑战是评测方法参照，不代表产品认证。

## 1. 问题重述与结论

真正的问题是：**针对交通执法现场中的明确产品动作，怎样用与部署人群、设备、声学条件和失败代价一致的数据，估计系统的错误、拒绝服务和不确定性，并在不接触盲测答案的情况下验证一个冻结的决策策略。**

结论先行：

1. 客户写下的 `97%`/`70%` 可以登记为“待论证需求”，但不能反推数据集。测试集由目标人群、部署环境、决策单位、目标/非目标先验、错误后果、覆盖率要求和期望统计精度共同决定。
2. “准确率”不适合作为声纹主指标。它受正负样本比例支配，也没有区分误接收与误拒绝。应报告同一冻结工作点下的 FAR、FRR、coverage/无分数率、置信区间和实际 DCF，并用 DET、EER、minDCF 做诊断。
3. 办公室只能作为受控对照域；交通现场才是主目标域。二者应分层报告，并使用同人、同设备、近似同内容的配对采集量化 domain shift，不能混成一个总体准确率。
4. 单人/轮流讲话验证与重叠语音是不同任务。重叠轨必须评测目标文本的 CER/WER、非目标内容泄漏和无重叠条件退化；普通 embedding 相似度只能回答混音里是否存在目标声纹的证据，不能证明“哪些字属于谁”。
5. 正确路径是“用途冻结 → pilot 表征方差 → cluster-aware power analysis → dev/calibration → 冻结系统与工作点 → sequestered blind test”。在 pilot 之前宣布正式样本量或商用阈值，证据顺序是倒置的。

ISO/IEC 19795-1:2021 的官方摘要要求生物识别测试协议减少不当采集和分析造成的偏差、尽可能估计现场性能，并说明测试结果的适用边界；这直接排除了用办公室便利样本替代交通部署域的做法。[ISO/IEC 19795-1:2021](https://www.iso.org/standard/73515.html)

ISO/IEC 19795-2 进一步区分使用离线语料评算法辨识力的 technology evaluation，与包含传感器、真人交互和环境的 scenario evaluation。当前交付判断需要以后者为主、前者为诊断；二者不能共用一个“准确率”。[ISO/IEC 19795-2](https://www.iso.org/standard/41448.html)

## 2. 为什么不能从 `97%`/`70%` 反推测试集

### 2.1 百分比没有定义任务

“机主识别准确率”至少可能指：

- 目标说话人被接受的比例，即 `1 - FRR`；
- 被接受片段中真正属于目标人的比例，即 precision/PPV；
- 每个 turn 的角色标签正确率；
- 目标说话人的文字 CER/WER；
- 整段文本是否仅含目标人内容；
- ASR 普通文字准确率，而非身份判断准确率。

这些量的分母、错误含义和标注粒度完全不同。没有先定义产品输出和决策单位，就不存在可复现的“97%”。FIDO 要求先定义 verification transaction 的结束点、最大尝试次数和超时，并在 transaction 层统计 FAR/FRR；这个原则说明评测单位必须来自实际交互，而不是由数据标注便利性决定。[FIDO Biometrics Requirements v4.1，3.4.1](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#verification-transactions)

### 2.2 aggregate accuracy 可以被样本比例操纵

若测试集中 97% 都是目标人，系统无条件输出“目标人”就有 97% accuracy，但其非目标拒绝能力为零。相反，非目标占 97% 时，无条件拒绝也有 97%。因此：

```text
accuracy = (TP + TN) / (P + N)
```

还可以写成：

```text
accuracy = πtarget × (1 - FRR) + (1 - πtarget) × (1 - FAR)
```

它无法脱离测试集的 target/non-target mixture 解释。真实业务 mixture 又未必等于测试 mixture。NIST SRE 不用样本表面比例替代业务先验，而是显式以 `PTarget`、误拒成本和误接成本定义检测代价：[NIST SRE24 Evaluation Plan，Performance Measurement](https://www.nist.gov/system/files/documents/2024/06/11/NIST_2024_Speaker_Recognition_Evaluation_Plan.pdf)

```text
CDet(t) = Cmiss × Ptarget × Pmiss(t)
        + Cfa   × (1 - Ptarget) × Pfa(t)
```

所以，先定一个 accuracy 再凑正负样本没有风险语义。正确顺序是先定义系统会采取什么动作、两种错误造成什么后果、目标事件在该动作发生时多常见，再决定工作点和评测精度。

### 2.3 点估计不是可证明的要求

即使“97%”被明确成 `FRR <= 3%`，观察到 97% 也不等于真实水平至少为 97%；有限样本还有抽样不确定性。FIDO 的正式要求以置信区间上界判断 FAR/FRR，并指出供应商实际开发目标必须严于认证门槛，以抵御不同测试之间的自然波动。[FIDO v4.1，3.4 与 5.1.3](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#biometric-performance-levels)

本文不建议照搬 FIDO 的置信度或样本数，而是采用其更重要的方法：**预先定义统计判据，用上界/下界或精度要求决定样本量，不能用观测点值自证。**

## 3. 先把 use case 分成独立评测轨

| 轨道 | 产品问题 | 主要真值 | 主指标 | 当前 embedding 分数能否单独回答 |
| --- | --- | --- | --- | --- |
| A. 单说话人验证 | 已切好的单人 final 是否来自机主 | target / non-target identity | FAR、FRR、DET、DCF、coverage | 可以作为 baseline |
| B. 非重叠目标人过滤 | 轮流讲话时哪些 turn/final 应保留 | 每个 turn 的身份与边界 | turn/frame target miss、non-target leakage、目标 CER/WER | 有机会，但依赖切段、时长和阈值 |
| C. 重叠目标人 ASR | 同时讲话时能否只转出目标人的字 | 每位说话人的时间对齐文本 | target CER/WER、干扰人插入/泄漏、overlap ratio 分桶 | 不可以；需要提取/分离/TS-ASR 能力 |
| D. 安全/反欺骗 | 回放、TTS/VC 或注入能否冒充目标人 | bona fide / attack、攻击种类 | IAPAR 或 spoof FAR、t-DCF/a-DCF、coverage | 不可以；需要独立 PAD/系统安全链路 |

NIST SRE21 的 verification trial 是“目标人的 enrollment + test segment”，任务仅判断目标人是否出现在 test 中；它不要求恢复目标人的文字或把重叠字归属给某人。[NIST SRE21，Task Definition](https://www.nist.gov/system/files/documents/2021/07/12/2021_SRE_Evaluation_Plan_V5.pdf)

VoxSRC 也把单说话人 verification 和多说话人 diarization 放在不同轨道、不同测试集和不同指标中；测试数据只用于报告，禁止调参，并限制盲测提交次数以防止过拟合。[VoxSRC 2020 protocol](https://www.robots.ox.ac.uk/~vgg/data/voxceleb/competition2020.html)

Google 的 VoiceFilter-Lite 是为重叠语音专门训练的 speaker-conditioned separation 前端。论文用 WER 分别验证 clean、非语音噪声、语音干扰及混响，并把“不伤害其他声学条件”列为上线条件；这不是普通相似度阈值能继承的能力。[VoiceFilter-Lite 原始论文](https://www.interspeech2020.org/uploadfile/pdf/Wed-2-5-4.pdf)

如果产品涉及认证或对抗，应把攻击轨与 zero-effort non-target 分开。ASVspoof 2021 把 bona fide target、bona fide non-target 和 spoof 风险通过专门的 t-DCF 连接，并对回放、TTS/VC、传输和真实房间条件建立独立协议；普通 FAR 不包含这些攻击。[ASVspoof 2021 Evaluation Plan](https://www.asvspoof.org/asvspoof2021/asvspoof2021_evaluation_plan.pdf)

还有一条必须谨慎表达的用途边界：NIST SP 800-63B-4 在其美国政府网络数字身份认证范围内明确禁止 voice biometric comparison；官方同时说明该规范无意约束其范围之外的系统。这不是“所有警务声纹都禁止”，但足以说明当前相似度 SDK 不能未经独立安全评测就包装成通用身份认证器。[NIST SP 800-63B-4，3.2.3.2](https://pages.nist.gov/800-63-4/sp800-63b.html#sec3)

## 4. 预注册协议：采集前必须冻结什么

预注册不是学术仪式，而是防止“看见结果以后改分母、挑阈值、删难例”的工程控制。建议在采集正式 dev/blind 前形成一份版本化 JSON/YAML 与人类可读文档，并由产品、算法、测试、业务风险负责人共同签字。

### 4.1 用途和系统边界

必须写清：

1. 系统动作：只显示相似度、标记“疑似机主”、自动抑制非机主文本、删除录音、还是身份认证；
2. 决策单位：固定窗口、native segment、公开 final、turn、session 或一次完整业务 transaction；
3. 目标假设：目标人在片段中存在，还是整段只由目标人讲话；
4. enrollment 流程：段数、跨 session 要求、最短有效语音、质量失败和重录政策；
5. 无分数/低质量策略：拒绝、保留、重试或 abstain；
6. 可接受回退：是否保留完整 ASR/原音，是否允许人工确认；
7. 明确排除的能力：例如第一阶段不评估重叠逐字归属或主动攻击。

如果动作是“自动删除非机主内容”，误拒会造成潜在证据丢失；如果动作是“只上传机主内容”，误接会造成非目标内容泄漏。两者的成本排序相反，不能共享一句“准确率越高越好”。

### 4.2 prior、cost 与敏感性范围

优先从业务日志或小规模观察研究估计：

- `Ptarget`：实际决策单位中目标事件的频率，而不是测试集人为正负比例；
- `Cmiss`：漏掉目标语音的相对损失；
- `Cfa`：把非目标当目标的相对损失；
- 可选 `Cabstain`：不给决定/请求重试的损失；
- 安全轨另有 `Pspoof` 和 spoof false-accept cost。

若业务现在无法给出可信先验和成本，不应伪造一个“最佳阈值”。应预注册一个有业务解释的 prior/cost sensitivity grid，报告完整 DET 与每个格点的 DCF，再由风险所有者选部署策略。原始 `Cllr` 论文证明 speaker detection 的 Bayes 决策必然依赖 target prior 和错误成本，并把 discrimination 与 calibration 分开评测。[Application-independent evaluation of speaker detection](https://doi.org/10.1016/j.csl.2005.08.001)

### 4.3 系统版本和变化控制

冻结并哈希：

- 模型和声纹模板格式；
- 采样率、通道、增益、AEC/AGC/降噪和重采样；
- VAD、切段、最短时长和无分数规则；
- enrollment 聚合、score normalization、calibrator 和阈值；
- Harmony/Android scorer 实现、SDK/HAR/HAP、OS 与设备型号；
- 评测代码、trial list、随机种子和容器/可复现实验环境。

模型不变但 scorer 从 whole-segment 改成 max-window、VAD 边界改变或平台预处理改变，都可能改变分数分布，必须视作新系统版本，而不是继续沿用旧阈值。

## 5. 数据集结构：不是一个“大杂烩”，而是四层证据

### 5.1 Pilot：表征方差，不做商用 PASS/FAIL

Pilot 的任务是：

- 找出交通现场的主要条件轴；
- 估计 speaker/session 内相关性、FAR/FRR 大致区域和无分数率；
- 发现采集、标注和 SDK 输出契约问题；
- 为正式样本量的 cluster-aware simulation 提供参数。

Pilot 可以迭代，身份可以与后续 dev/blind 完全隔离。它不产生最终对外精度声明。

### 5.2 Dev/calibration：允许调参，但不可冒充验收

Dev 用于：

- 选择切段/质量策略；
- 训练 score calibrator；
- 选择一个或多个预注册工作点；
- 确定条件分桶和样本量；
- 冻结系统版本与评测代码。

Dev 结果可以报告为开发证据，但不能当作 blind performance。BOSARIS 原始论文指出，低错误率工作点的 calibration 和 evaluation 都需要很大的 trial 集；开发集反复选择最优阈值后得到的 minDCF 是乐观值。[BOSARIS Toolkit 原始论文](https://arxiv.org/abs/1304.2865)

### 5.3 Blind：只验证冻结主张

Blind 的身份、session、源录音和标签对开发团队不可见。最好由独立数据保管人运行冻结容器或安装包，只回传已预注册的聚合结果。NIST 2024 SRSE 采用更强的 sequestered 设计：数据在评测期间和之后都不向参与者开放，由评测方控制初始化、enrollment、target/non-target trials 和输出处理。[NIST Speaker Recognition Sequestered Evaluation](https://pages.nist.gov/srse/)

### 5.4 运营监测：回答上线后的 drift

Blind 只覆盖一个版本和一组条件。上线后应持续监测：

- score/质量/无分数分布漂移；
- 设备、OS、固件、季节、地点和噪声分桶；
- 人工复核样本中的 FAR/FRR proxy；
- enrollment 老化与更新；
- 任何阈值或预处理变更后的再验证触发条件。

监测集不能静默并入原 blind，也不能用线上挑出的“好例”刷新历史结论。

## 6. 防泄漏分割与 trial 设计

### 6.1 三种隔离必须同时满足

1. **speaker-disjoint**：pilot、dev/calibration、blind 使用不同身份。这样阈值和 calibrator 的验证对象才是未见用户，而不是开发时已经观察过分数分布的人。
2. **session-disjoint**：同一 split 内，mated trial 的 enrollment 与 probe 来自不同录音 session，优先跨日期/地点；否则系统可能利用通道、背景或同一嗓音状态，而非稳定身份特征。
3. **source-disjoint**：同一原始录音的裁剪、增强、混音衍生物只属于一个 split；不能把一段原音的不同窗口分进 dev 和 blind。

注意：speaker-disjoint 指 split 之间身份不重叠。每个 verification split 内，为形成 mated trial，enrollment 和 probe 当然来自同一个人，但必须 session/source-disjoint。

### 6.2 每个身份需要的录制结构

不要先固定“每人 20 条”之类数字；先固定能识别方差的结构：

- 至少一个独立 enrollment session；
- 多个 probe session，覆盖不同日期/位置/说话状态；
- 每个 session 含自然任务语音，而不只是固定口令；
- 目标 probe 与 zero-effort non-target probe；
- 困难非目标：在目标人口中按性别、年龄段、方言/口音和音色相似度分层，而不是只随机配对；
- 短句、长句、低音量、转头、走动和距离变化；
- 所有失败、重录和被排除样本保留审计记录。

### 6.3 正负 trial 不靠笛卡尔积“扩容”

同一 speaker 被用于大量 target/non-target pairs 时，trial 高度相关。NISTIR 7884 明确指出 speaker recognition 数据的依赖主要来自同一受试者被重复使用，并采用两层 bootstrap：先重采样 speaker set，再重采样 set 内 scores。[NISTIR 7884](https://nvlpubs.nist.gov/nistpubs/ir/2012/NIST.IR.7884.pdf)

因此，`N` 万个 pair 不等于 `N` 万个独立证据。样本量、置信区间和模型比较必须保留 speaker/session cluster，不能只用普通二项分布把每个 pair 当独立样本。

## 7. 交通域与办公室域怎么设计

### 7.1 主结论只来自 intended environment

交通执法目标域至少应记录并分层：

- 真实交付设备、麦克风位置、佩戴/手持方式；
- 室内车厢、路侧、路口、停车场等位置；
- 静止/行驶、开窗/关窗、警笛/喇叭/发动机/风噪/人群；
- 目标人与设备距离、朝向、走动；
- 语言、方言、语速、情绪、身体状态；
- 目标/非目标相对响度、turn duration；
- 对 overlap 轨记录 overlap ratio、SIR/SNR 和各说话人独立参考文本。

FIDO 的测试要求虽然针对认证，但其环境原则具有普适性：测试始终要考虑 intended environment，环境定义很宽时可能需要多次测试或更多受试者；报告还必须写明设备、场景、人口、时间间隔、阈值、影响性能的因素和不确定性。[FIDO v4.1，Test Environment 与 Reporting](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#test-environment)

ISO/IEC 29197 专门要求先建立 reference environment/baseline，再定义、测量和记录环境变化及其性能影响。因此办公室最合理的角色是 reference environment，交通现场是 target environment；跨域差异本身就是结果，不能平均掉。[ISO/IEC 29197](https://www.iso.org/standard/45276.html)

CN-Celeb 原始研究把 speaking style、身体状态、录音设备、背景噪声等跨 session 变化列为 speaker recognition 的关键困难，并显示跨 genre mismatch 会显著恶化性能。这说明办公室结果外推交通现场没有技术依据。[CN-Celeb multi-genre 原始论文](https://www.cnceleb.org/static/CN-Celeb_Multi-Genre_Speaker_Recognition.pdf)

### 7.2 办公室应作为 paired control，而非混入总体

推荐让一个预注册子样本在同一设备、近似同一脚本下分别完成办公室和交通采集，且顺序随机/平衡。分别报告：

```text
office FAR/FRR/coverage
traffic FAR/FRR/coverage
paired score shift and error transition
condition × identity random effects / cluster bootstrap CI
```

这样能回答“问题来自域偏移还是一般不可分”。把办公室和交通样本混在一个总体里会用容易条件稀释困难条件，失去诊断价值。

## 8. 指标体系与无分数策略

### 8.1 轨 A：单说话人 verification

主报告：

- FAR 与 FRR，在同一个冻结阈值；
- FAR/FRR 的 speaker/session-cluster bootstrap 置信区间；
- coverage、无分数率、FTE/FTA 或 SDK 对应的“样本不足”率；
- actual DCF，绑定预注册 prior/cost 和冻结阈值；
- 按设备、距离、时长、噪声、方言、性别/年龄段等分桶的上述指标；
- latency、RTF、资源与失败恢复。

诊断报告：

- DET/ROC；
- EER；
- minDCF；
- 若输出经校准 LLR，报告 Cllr 与 calibration loss。

`minDCF` 和 EER 都是在结果上扫阈值得到的能力诊断，不能替代部署阈值。NIST SRE21 同时报告固定 LLR 决策阈值下的 actual cost 和事后最优的 minimum cost，二者分别反映部署表现与可分性上限。[NIST SRE21，Performance Measurement](https://www.nist.gov/system/files/documents/2021/07/12/2021_SRE_Evaluation_Plan_V5.pdf)

### 8.2 coverage 不能被静默删除

“没有 `speakerSimilarity`”不是可随手排除的数据清洗项。至少报告：

```text
coverage = produced-valid-score / all in-scope decision units
```

同时按照预注册产品策略给出端到端指标：

- no-score 当 reject 时的 FRR/FAR；
- no-score 当 abstain 时的 abstain rate 与剩余 FAR/FRR；
- retry 时的最终 transaction FAR/FRR、平均尝试次数和延迟。

FIDO 将 failure-to-acquire 作为独立性能量，要求记录所有 FTA，并在完整 verification transaction 仍不能成功时计入 false reject；这能防止系统通过拒绝困难输入来美化已出分样本的 FAR/FRR。[FIDO v4.1，FTA 与 FRR](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#false-reject-rate-frr)

### 8.3 轨 B：轮流讲话过滤

除轨 A 的 score 指标外，还要在端到端输出层报告：

- target turn recall / miss；
- non-target turn leakage / false keep；
- duration-weighted target miss 与 non-target leakage；
- target CER/WER；
- 被保留文本中的 non-target 字/词插入率；
- turn 边界截断、首次决定延迟、abstain/无分数率。

严禁用“整段里出现过目标人的声音”作为“整段文字都属于目标人”的真值。

### 8.4 轨 C：重叠目标说话人 ASR

单独报告：

- target CER/WER；
- non-target lexical leakage/insertion；
- 按 overlap ratio、SIR/SNR、人数、距离和混响分桶；
- target-only clean、target + 非语音噪声、target + 非重叠说话人、target + 重叠说话人四类；
- 无重叠/非语音条件相对 baseline 的退化，避免“为 overlap 优化但伤害常规场景”。

应同时保留两类数据：真实交通重叠（外部有效性）和由独立干净源构造、拥有逐说话人真值的受控混音（精确诊断）。两者分别报告，不互相替代。

## 9. 样本量：用 cluster-aware power/precision analysis 决定

### 9.1 Pilot 之后再计算正式规模

推荐流程：

1. 从 pilot 估计每个主轨/关键分桶的错误率、无分数率、speaker 间方差、session 内相关性；
2. 预注册希望达到的统计精度，例如 FAR/FRR 一侧 95% CI 上界宽度、DCF CI 宽度，或两个版本最小有意义差异 `δ`；
3. 以 speaker 为一级、session/transaction 为二级做分层重采样或层级模型模拟；
4. 对候选的 speaker 数、每人 session 数和每 session transactions 数，估计达到精度或 80%/90% power 的概率；
5. 选择能同时满足主指标和最高风险分桶的最小设计，并预留失访、FTE/FTA 和无效录音。

这种方法会回答“再录同一个人的更多句子”和“增加新的人”哪个更有价值；简单把 pair 数做大回答不了这个问题。

### 9.2 Rule of Three 只作为零错误 sanity check

当独立事件中观测到零错误时，95% 单侧上界近似 `3/N`。FIDO 将该规则用于低 FAR 设计，同时在非零错误和重复交易时采用按 subject/transaction 的 bootstrap。[FIDO v4.1，Rule of 3 与 Bootstrapping](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#statistics-and-test-size)

本项目不能把所有 non-target 笛卡尔积直接代入 `N`，因为同一 speaker/session 被重复使用。它只适合作为“即使假设独立，当前量级也明显不够”的下界检查；正式区间以 cluster-aware 方法为准。

生物识别样本量原始研究也明确说明，受试者内多次交易的相关性会改变方差和所需人数；“少数人每人很多次”不能按独立试验换算成“很多人每人一次”。因此 power simulation 应优先决定新增 speaker 还是新增 session，而不是只最大化 pair 数。[Schuckers et al., Test Sample Size and Statistical Dependency](https://myslu.stlawu.edu/~msch/biometrics/papers/SchuckersTestSampleSizev2.pdf)

## 10. 固定工作点与 blind test 管理

### 10.1 Dev 上冻结，blind 上只执行

在开启 blind 前冻结：

- 主系统和最多若干个事先声明的对照系统；
- 阈值、calibrator、条件感知规则和无分数策略；
- primary metric、次要指标、分桶、排除规则、CI 方法；
- trial 生成算法、每人权重、停止规则；
- 成功/失败/不确定结论的文字模板。

若使用多个条件阈值，必须在 dev 上写成可执行规则并冻结；不能在 blind 看到哪一桶差以后给该桶单独调阈值。FIDO 的正式测试要求 FAR 与 FRR 使用相同且在测试期间固定的工作点。[FIDO v4.1，3.4.2–3.4.3](https://fidoalliance.org/specs/biometric/requirements/Biometrics-Requirements-v4.1-fd-20250106.html#false-accept-rate-far)

### 10.2 推荐的盲测操作控制

1. 独立保管 labels、身份映射和原始媒体；
2. 开发团队只在 validation/dev 上确认可运行；
3. 交付带哈希的模型、配置、阈值、容器/安装包和 output schema；
4. 评测方自动运行全部 trials，禁止人工试听后重跑单例；
5. 主结论只接受一次正式运行；技术性 invalidation 条件必须事先定义并完整留痕；
6. 一旦查看 blind 标签或按 blind 结果改系统，该集合永久降级为 dev；下一次声明需要新的 blind identities/sessions；
7. 对照版本在完全相同 trials 上做 paired、cluster-aware 比较；
8. 报告全部预注册主指标、关键分桶、置信区间、失败样本类别和 protocol deviations。

VoxSRC 明确规定 test 只能用于报告、不能训练或调参，并限制提交次数防止 test overfitting；ASVspoof 2021 使用有标签 dev、无标签 eval，并禁止在 eval 上做自适应或 score normalization；NIST SRSE 更进一步让测试数据永久隔离。内部商用验收应尽量采用后一种执行方式。[VoxSRC 2020](https://www.robots.ox.ac.uk/~vgg/data/voxceleb/competition2020.html) [ASVspoof 2021](https://www.asvspoof.org/asvspoof2021/asvspoof2021_evaluation_plan.pdf) [NIST SRSE](https://pages.nist.gov/srse/)

### 10.3 blind 之后如何解释

- **通过预注册判据**：只对已覆盖的人群、设备、场景、软件版本和产品动作作声明；
- **未通过**：报告差距和失败桶，blind 降级为诊断集，优化后另建新 blind；
- **区间过宽**：结论是 inconclusive，不是“接近通过”；按预注册扩样规则增加独立 speaker/session；
- **只在 office 通过**：只能声明 office 域表现，不能声明交通可用；
- **verification 通过但 overlap 失败**：单说话人能力成立，重叠能力不成立，二者不能平均。

## 11. 对当前 `evaluation/voiceprint_traffic` 规范的只读审计

当前规范已经完成了最重要的方向修正：删除固定 `97%/70%` 和通用人数门槛；加入 use case、prior/cost、FAR/FRR/coverage/DCF、pilot power analysis、speaker/session/source 隔离、traffic-domain blind、overlap 独立轨和 single-pass blind。`validate_manifest.py` 也已经检查 speaker/source/session 跨 split 泄漏、enrollment/probe session 复用、配置化人数/trial/session 门槛和 unseen blind site。这一版可以作为采集设计的可靠骨架。

仍需修正的事项如下；这些是协议可复现性和正式验收能力缺口，不代表要立刻修改本目录中的文件。

### 11.1 P0：正式 blind 前必须补齐

1. **冻结工作点仍只有描述，没有可执行值。** `protocol.template.json` 只有 `target_prior_source`、两个 cost 和 `threshold_selection_split`，缺少 numeric prior/cost（或 sensitivity grid）、score scale、threshold、calibrator/hash、no-score 的 FAR/FRR 计入规则。当前模板无法独立复算 actual DCF。
2. **缺少完整 system card/hash。** README 要求冻结模型、scorer、注册、平台和文本归一化，但 protocol/manifest 只有 `sdk_version` 字符串。至少要绑定模型/HAR/HAP、scorer 代码、VAD/切段、enrollment aggregation、calibrator、metric code 和 platform build 的哈希。
3. **没有机器可读的性能判据。** `primary_metrics` 是自由字符串，模板没有每个指标的 estimand、方向、CI 类型、通过边界、关键最差桶和 coverage 下限。当前 acceptance validator 只能证明“数据规模符合配置”，不能判定冻结系统的性能；这与 README 的免责声明一致，但正式项目还需要独立 frozen scorer/gate。
4. **overlap 真值不足以精确评 overlap-only 文本。** manifest 有 turn 文本和 overlap region，却没有 time-aligned token/字符、`SIR`、受控混音的独立 source/reference 映射。它能验证“两人确实同时有声”，但难以准确计算重叠区 target CER 与 non-target lexical leakage。应扩展独立 overlap schema，而不是挤进普通 SV trial。
5. **blind 的 single-pass 目前只是声明。** protocol 还需记录 data custodian、label/media access policy、sealed trial/manifest hashes、提交 artifact hash、允许的 technical invalidation 条件、正式 run ID 和结果解封流程；否则“只运行一次”无法审计。

### 11.2 P1：pilot 前后结构化完善

1. `evidence_requirements.basis` 目前是自由文本。建议结构化保存 pilot 版本、目标 CI 宽度、最小有意义差异、power、假设的 cluster/ICC、模拟次数、代码哈希和 attrition/FTA 预留。
2. `cluster_keys=[target_speaker_id, session_id]` 没有定义是 joint-key bootstrap 还是 speaker→session/transaction 的嵌套 bootstrap，也没有 reps、seed、单侧/双侧和 trial weighting。正式 scorer 必须写死 estimand 与重采样算法。
3. 规范要求跨日，但 validator 只数 probe dates，没有验证 enrollment 与 probe 日期分离或最小时间间隔；不同 session 仍可能发生在同一天同一地点。
4. `require_unseen_blind_site` 只能防止地点完全复用，不能证明 blind 代表实际部署。protocol 还需绑定 target-population frame、场景/设备/时长/噪声 strata 权重、困难桶最低证据量，并同时报告 deployment-weighted 与 worst-bucket 结果。
5. 办公室/交通配对目前没有强制 `pair_id`；`prompt_id` 不能唯一表达同人、同内容、同设备的 paired design。若要做 paired domain-shift inference，应增加配对键和采集顺序字段。
6. `annotation` 在 schema 中可选，formal acceptance 也没有强制双标/裁决比例、身份映射复核或一致性判据。应在 protocol 中结构化这些门禁，并把 protected subject registry 的版本/hash 绑定到 dataset。

结论：当前规范已经足以启动合规准备和 pilot 设计，但还不足以直接运行“可审计的商用 blind gate”。最先补的是可执行工作点、系统哈希、机器可读性能判据、overlap 真值和 blind custody；其余项可由 pilot 的统计结果驱动完善。

## 12. 推荐的实际执行顺序

1. **先完成 use-case workshop**：冻结四轨中的范围、产品动作、决策单位、无分数策略和风险后果；客户的 97%/70% 只放在“外部期望”栏，不作为协议输入。
2. **做小规模双域 pilot**：真实设备采集交通主域和办公室 paired control，同时包含单说话人、轮流讲话和重叠；先验证标注和评测链路。
3. **运行当前 SDK baseline**：保留 raw `speakerSimilarity`、出分资格、PCM/有效语音时长、final/turn 对齐、平台和完整版本信息；不要先做 0–1 映射来“改善”结果。
4. **做方差与 power analysis**：按 speaker/session 聚类，决定 dev 和 blind 的人数、session 与 trial 分配，而不是按任意准确率倒推固定条数。
5. **在 dev 上优化并冻结**：先处理跨端 scorer 语义、enrollment、质量门控、校准和阈值；重叠轨若 baseline 不可行，单独立项 target-speaker extraction/TS-ASR。
6. **独立运行 blind**：固定工作点、一次执行、全量报告；blind 结果决定证据边界，不倒逼修改分母或指标。
7. **上线后监控与版本化再验证**：设备、OS、模型、VAD、切段、校准器或阈值变化均触发影响评估。

## 13. 最终应交付的评测资产

- `evaluation_protocol.yaml`：上述预注册字段；
- `manifest.jsonl`：speaker/session/source/domain/设备/声学条件/时间对齐真值；
- `trials.tsv`：固定 target/non-target/overlap/attack trials；
- `dataset_card.md`：目标人口、采集流程、合规、已知偏差和适用边界；
- `system_card.json`：模型、scorer、预处理、enrollment、threshold/calibrator 哈希；
- `scorer/`：固定指标与 cluster bootstrap/power simulation；
- `blind_run_log.jsonl`：逐 trial 输出和执行审计；
- `report.md`：actual 工作点、诊断曲线、coverage、分桶、CI、protocol deviations 和结论边界。

在这些资产建立之前，“达到商用水准”没有可审计含义；建立以后，即使结果不好，也能准确区分是 domain shift、短时长、无分数、切段、校准、embedding 可分性，还是 overlap 架构缺失，而不是继续围绕一个任意百分比争论。
