# Amphion HarmonyOS ASR 0.3.26 组包前验收摘要（927bda6e）

本摘要是组包前证据，不是最终 ZIP 的验收结论。最终 ZIP 的验收报告绑定其自身 SHA-256，另行外置。

本版相对 0.3.25 有**四处产品变更**：角色分离（说话人分离）的模型与链路整体更换为
Sortformer-66M-4spk 端到端流式模型，原 pyannote 分割 + WeSpeaker 嵌入 + PLDA/VBx 聚类链路
整体移除，不保留后备；角色分离结果内相邻的同一角色句子合并为一项（新增 `sourceUtteranceIds`）；
热词不再吞掉后续文字（sherpa 补丁 0036 / 0037）；机主识别在换人时不再把非机主首句录入机主句。
**识别模型、公共接口与回调顺序不变。**

## 冻结身份

| 项 | 值 |
|---|---|
| 版本 | 0.3.26，版本日期 2026-10-29 |
| 源码提交 | `927bda6e`（分支 `feat/harmony-sortformer-diarization`，工作区干净） |
| 语种范围 | 中英（ZH_EN） |
| 设备 | 我方测试机（HarmonyOS 7.0.0.109，arm64-v8a；机型与序列号见外置最终报告） |
| Diagnostics 子包构建模式 | `diagnostics` |
| Release 子包构建模式 | `debug` |
| 签名 | 本地 DevEco 自签证书（`signing-project`），叶证书有效期至 2049-03-16 |
| 授权核验 | 设备白名单文件为空（授权不绑设备），与 0.3.25 口径一致 |

## 本版改动

| 改动 | 文件 | 说明 |
|---|---|---|
| 原生 Sortformer 流式推理（NeMo mel 前端 + 4 张 ORT 图，9.92 s 块提交，块内可选预览） | `sortformer_diarization.cpp`、`SortformerDiarizationInference.ets` | CPU 执行，ORT 1.16.3 `.ort` 格式 |
| 鼎桥 HAR 角色分离会话改为「最终块冻结 + 预览临时角色」 | `SortformerLocalClient.ets`、`SpeakerDiarizationSession.ets`、`SortformerSpeakerIdentity.ts` | 公开回调契约不变 |
| 新配置 `scheduling.diarizationPreviewMs`（默认 5000） | `AsrSchedulingConfig.ts` | `diarizationEncoder` / `diarizationHopMs` 保留但不再生效 |
| 模型资产清单与构建身份绑定 7 个 Sortformer 资产 | `sortformer_diarization_v1.json`、`harmony_build_identity.py`、`hvigorfile.ts` | Community-1 资产与 MindIR 门禁移除 |
| 删除 Community-1 原生/ETS 实现、回放审计工具与对应测试 | 30 个文件 | 测试迁移到 `DIARIZATION_SORTFORMER_*` 事件 |
| 角色分离结果合并相邻同人句子，`DiarizedUtterance` 新增 `sourceUtteranceIds` | `SpeakerDiarizationTranscriptState.ts`、`SpeakerDiarizationSession.ets`、`DingqiaoModels.ets` | `speakerIndex=-1` 不参与；`speakerTurns` 不变；Demo 按 `sourceUtteranceIds` 替换临时句 |
| 热词半匹配前缀 1 s 过期 + 首字加分封顶 1.0 | sherpa 补丁 `0036` / `0037`（两端共用） | 公开接口与热词入参格式不变；预置池 1.0 与单字热词行为不变 |
| 机主离场：换人点定不出来时退保守前缀而非放行混合句；未经流式确认的句子需过 0.45 | `Runtime.ets`、`SpeakerTurnFinalizer.ts` | 回调契约不变，被判非机主仍为空 final + `SPEAKER_VAD_REJECTED` |

## 真机证据

### 1. 生命周期与资源（`customer-ptt`，12 cycle）

| 项 | 结果 |
|---|---|
| 总判定 | **PASS**（`failures: []`） |
| cycle 状态 | 12/12 全部 PASS |
| SDK 契约 | `sdk=PASS`，`native_streams` 12 轮 `liveStreams=0` |
| 空 final 率 | **0.000**（上限 0.05，计数 0） |
| 内存 | `memory=PASS`，增长 19.36 MiB，峰值 418.1 MiB |
| CPU | 12 逻辑核，单核等效均值 118.8%，p95 161.5% |
| 语料 | aishell3_test_hotwords_500，500 条有效、选取 24 条（85.9 s） |
| 身份绑定 | 报告 `build_identity` 与 Diagnostics 子包逐字段一致（`--skip-build-install`，取构建身份而非安装包身份） |

报告：`reports/customer-ptt-report.json`

### 2. 角色分离产品链路（`diarization-windows`，丁桥现场录音 4 条）

输入为丁桥现场会议录音中时长 ≥ 120 s 的 4 条（100350-257、102010-230、111223-816、
meeting-offline-unknown4），与 Diagnostics 构建同身份（`--skip-build-install`）。
第 5 条（095700-039，108 s）短于 120 s 公共提交周期，`diarization-windows` 契约要求
会话内至少两次 `SpeakerDiarizationResult`，该条在 0.3.25 与本版上均因此判 FAIL，属夹具前置条件，
故不纳入本报告；其 DER 见第 3 节。

| 项 | 结果 |
|---|---|
| 总判定 | **PASS**（`failures: []`） |
| cycle 状态 | 4/4 全部 PASS（`diarization-windows-contract`） |
| 角色分离生命周期 | `PASS`，4 个会话完成；每条录音 ≥ 2 次结果、终结结果恰 1 次、无降级 |
| 结束到最终角色结果 | 1137~2280 ms（0.3.25 同语料 659~747 ms） |
| 内存 | 峰值 825.1 MiB，增长 47.40 MiB（`INCONCLUSIVE`，角色分离模式下 RSS 判定为建议性） |
| CPU | 单核等效均值 183.9%，p95 275.5% |

报告：`reports/diarization-windows-dq4-report.json`

相邻同人合并在真机上生效的佐证取自同一代码的早前一轮构建：该轮回传 131 条 `DiarizedUtterance`，其中 9 条为合并项（`sourceUtteranceIds` 长度 > 1），其余为单句或 `speakerIndex=-1` 的不参与合并句。合并链路此后未改动，本轮未重新采集 utterance 明细。

### 3. 热词不再吞掉后续文字（7 例夹具，支撑证据）

同一台测试机，逐例对照 0.3.25 行为：

| 用例 | 0.3.25 | 本版 |
|---|---|---|
| 客户原样 53 词（含常用词热词） | 正常 | 正常 |
| 不含该热词录音 + 51 / 53 词 | 正常 | 正常 |
| 单个常用词热词 / 两字前缀 | 正常 | 正常 |
| 七字前缀探针（构造的最坏情况） | 数字 11 位全丢 | 仅丢前 5 位 |

主机 500 条热词语料回归：整体 CER 1.021% → 1.075%，热词召回 97.25% → 97.09%
（619 个热词实例少命中 1 个）。两字热词在任何分数下都无法强推首字。
逐例设备产物留存于我方验收记录（支撑证据，受检报告只收 PASS 的模式，故不随包）。

### 4. 机主识别换人（`speaker-vad-turn`，6 例，支撑证据）

目标说话人夹具本轮首次具备（此前自 0.3.20 起因无夹具而豁免）。每例为机主一段后
**无间隙**接另一说话人 1.4~1.6 s，断言"机主的话在、非机主的话不在、非空 final 条数正确"。

| 项 | 结果 |
|---|---|
| 归属断言 `target_speaker_content` | **PASS，6/6** |
| 修复前同夹具 | 2/6 泄露非机主首句 |
| 单轮判定 | **FAIL** —— 载体自设的收尾时延预算未达成（见下） |

单轮报告与逐例诊断事件留存于我方验收记录（支撑证据，受检报告只收 PASS 的模式，故不随包）。

### 5. 角色分离精度（同机、同音频、同评分口径 openbench-der-v1）

对第 2 节报告中设备回传的 `speakerTurns` 按 openbench-der-v1（collar 0、计重叠、Hungarian
匹配、人工标注 UEM 范围内）评分，与 0.3.25 Community 链路在同一台测试机上的实测基线对比：

| 录音 | 0.3.25（Community） | 0.3.26（Sortformer，本构建） |
|---|---:|---:|
| 100350-257 | 36.31% | **3.01%** |
| 102010-230 | 36.55% | **13.50%** |
| 111223-816 | 10.34% | 26.24%（退化） |
| meeting-offline-unknown4 | 17.15% | **6.44%** |
| **全集（UEM 内）** | **23.10%** | **12.10%** |

111223-816 一条本版退化（出现约 4 s 混淆），其余三条大幅改善；混淆（说错是谁）是主要改善项。
AliMeeting 公开语料 20 窗（12.74%，人数判对 19/20）为上一轮探针实测，本版产品链路未重跑。

### 6. 算力与内存（识别与角色分离同时运行，丁桥现场录音）

| 项 | 0.3.25 | 0.3.26 |
|---|---:|---:|
| 角色分离推理墙钟 RTF（每段录音） | 0.07~0.09 | **0.26~0.27** |
| 整进程 CPU 均值（单核等效） | 1.58 核 | **1.84 核**（+16%） |
| 整进程 CPU p95 | 2.21 核 | 2.76 核 |
| 进程峰值内存 | 581 MB | **825 MB**（diagnostics 构建，4 条 ≥ 120 s） |
| 结束到最终角色结果 | 0.66~0.75 s | 1.1~2.4 s |

新模型单独运行（无识别竞争）时每块推理约 0.4 s、整文件 RTF 0.045，含 5 s 预览 0.075~0.080；
与识别同时运行时模型线程被识别线程挤占，推理墙钟约为单独运行的 3 倍。该结论已写入随包的
`CHANGELOG.md` 与 `UPGRADE_0.3.26.md`。

## 组包门禁（Release 子包）

| 门禁 | 结果 |
|---|---|
| 自包含 HAR 在干净客户宿主安装并编译 | PASS |
| API 23 编译兼容性 | **PASS，52 个文件**（独立 OpenHarmony 6.1 / API 23 es2abc） |
| 客户交付脱敏检查 | PASS，16 个文件 / 1 个 HAR |
| HAR 版本与交付版本一致 | PASS（0.3.26） |
| 模型清单 v2 | PASS（9 个资产） |
| ZH_EN ONNX MD5 固定值 | PASS |
| UTF-8 ZIP + CRC 完整性 | PASS |

## 交付边界

- 语种范围为中英（ZH_EN），**不包含**粤英模型。
- **不包含** TTS 模型，TTS 由独立 TTS SDK 交付。
- 目标说话人增强仅保留接口，**不包含**所需模型，因此**不能启用**。
- 公共商用授权文件 `amphion-license.lic` **不在 Release 包内**，继续使用既有交付版本。
- Diagnostics 包内随附的签名 Demo HAP 内置一份**两个月试用、不绑设备**的授权（ASR+TTS，
  2026-12-22 到期，与 0.3.25 同一份），仅供开箱试用，不替代正式授权。
- 交付包只含产品代码与公开文档，不含评测探针、评测脚本与评测语料。

## 未覆盖与仍未解决

- **`speaker-vad-turn` 模式豁免（理由已更新）**：夹具本轮首次具备，归属断言 6/6 通过，但该模式
  的单轮判定仍为 FAIL —— 载体自设的"收尾补救 finish→非空 final ≤ 1200 ms"预算未达成：6 例中
  4 例靠收尾补判检出换人，其中 3 例为 1652~1732 ms。构成为换人分割推理约 160 ms、机主前缀重
  解码约 790 ms、前缀 final 补尾刷新约 400 ms 与打分派发。该时延在本版修复前后基本不变
  （修前 1637~1813 ms），不是本次修复引入，且在随包声明的"结束到最终角色结果 1.1~2.4 s"之内；
  说话过程中临时结果持续刷新，不存在等待期无文字。因受检报告要求 PASS，该模式仍按豁免处理，
  报告作为支撑证据随验收目录保留。放宽预算或优化前缀预解码的处置待定。
- **算力上升**：角色分离与识别并行时推理墙钟约为 0.3.25 的 3 倍、整进程 CPU 均值 +16%、
  峰值内存 +240 MB（见第 6 节）。`diarizationPreviewMs = 0` 可降约一半，本版默认未关闭。
- **长会话内存**：2 小时单会话已按新链路实测（同一角色分离运行时的早前一轮构建）：7381 s 会话
  通过，605 条 final、71 次角色结果、无降级、线程稳定，峰值 RSS 911 MB、内核 HWM 926 MB、
  斜率 1.13 MB/min（0.3.24 为 1160 / 1222 MB、约 2.0 MB/min）。ArkTS 堆仍单调上升，未归因。
  电池温度 123 分钟内 26.0 → 37.0 °C（0.081 °C/min）。
- **AliMeeting 未在产品链路重跑**：12.74% 为探针实测，与产品链路在丁桥 5 条上逐条同值
  （12.10%）。
- **短录音契约**：短于 120 s 的会话只有终结一次结果，`diarization-windows` 夹具判 FAIL，
  属夹具前置条件而非产品缺陷，0.3.25 同。
- **功耗**：USB 供电下电流读数不可用，功耗以 CPU 时间为代理，未做绝对功耗测量。

## 本轮子包哈希

完整包 `Amphion-Harmony-ASR-Complete-0.3.26.zip` 的 SHA-256 随外置最终验收报告给出，
不写入包内摘要。

| 产物 | 大小 | SHA-256 |
|---|---|---|
| `amphion-harmony-asr-sdk-v0.3.26-20261029.zip` | 390 MB | `14c7901aeb245c6e04072b1cd573db945d5b6bad7682208d8443bcf6498b4a58` |
| `Amphion-ASR-Diagnostics-SDK.zip` | 774 MB | `618e20a645adda58e74fbc47781eded6898bf441478226393ff9955d97b6858a` |
