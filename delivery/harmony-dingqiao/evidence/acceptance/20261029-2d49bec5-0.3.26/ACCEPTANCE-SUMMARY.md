# Amphion HarmonyOS ASR 0.3.26 组包前验收摘要（2d49bec5）

本摘要是组包前证据，不是最终 ZIP 的验收结论。最终 ZIP 的验收报告绑定其自身 SHA-256，另行外置。

本版相对 0.3.25 有**两处产品变更**：角色分离（说话人分离）的模型与链路整体更换为
Sortformer-66M-4spk 端到端流式模型，原 pyannote 分割 + WeSpeaker 嵌入 + PLDA/VBx 聚类链路
整体移除，不保留后备；角色分离结果内相邻的同一角色句子合并为一项（新增 `sourceUtteranceIds`）。
**识别模型、热词、公共接口与回调顺序不变。**

## 冻结身份

| 项 | 值 |
|---|---|
| 版本 | 0.3.26，版本日期 2026-10-29 |
| 源码提交 | `2d49bec5`（分支 `feat/harmony-sortformer-diarization`，工作区干净） |
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

## 真机证据

### 1. 生命周期与资源（`customer-ptt`，12 cycle）

| 项 | 结果 |
|---|---|
| 总判定 | **PASS**（`failures: []`） |
| cycle 状态 | 12/12 全部 PASS |
| SDK 契约 | `sdk=PASS`，`native_streams` 12 轮 `liveStreams=0` |
| 空 final 率 | **0.000**（上限 0.05，计数 0） |
| 内存 | `memory=PASS`，增长 13.23 MiB，峰值 419.1 MiB |
| CPU | 12 逻辑核，单核等效均值 122.5%，p95 160.1% |
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
| 结束到最终角色结果 | 1147~2155 ms（0.3.25 同语料 659~747 ms） |
| 内存 | 峰值 804.3 MiB，增长 45.50 MiB（`INCONCLUSIVE`，角色分离模式下 RSS 判定为建议性） |
| CPU | 单核等效均值 183.0%，p95 283.8% |

报告：`reports/diarization-windows-dq4-report.json`

该报告回传的窗口结果中共 131 条 `DiarizedUtterance`，其中 9 条为相邻同人句子合并项（`sourceUtteranceIds` 长度 > 1），其余为单句或 `speakerIndex=-1` 的不参与合并句，可作为合并功能在真机上生效的佐证。

### 3. 角色分离精度（同机、同音频、同评分口径 openbench-der-v1）

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

### 4. 算力与内存（识别与角色分离同时运行，丁桥 5 条）

| 项 | 0.3.25 | 0.3.26 |
|---|---:|---:|
| 角色分离推理墙钟 RTF（每段录音） | 0.07~0.09 | **0.25~0.27** |
| 整进程 CPU 均值（单核等效） | 1.58 核 | **1.76 核**（+11%） |
| 整进程 CPU p95 | 2.21 核 | 2.68 核 |
| 进程峰值内存 | 581 MB | **711 MB**（debug 构建，5 条）/ 804 MB（diagnostics 构建，4 条） |
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

- **`speaker-vad-turn` 模式豁免**：该模式需要客户目标说话人夹具，本检出与受控数据包中均不存在，
  无法产出有效证据。本版未改动该模式，沿用 0.3.20–0.3.25 的同一豁免。
- **算力上升**：角色分离与识别并行时推理墙钟约为 0.3.25 的 3 倍、整进程 CPU 均值 +11%、
  峰值内存 +130~220 MB（见第 4 节）。`diarizationPreviewMs = 0` 可降约一半，本版默认未关闭。
- **长会话内存**：2 小时会话未按新链路复测（0.3.25 记录峰值约 1.1 GB）；本版 17 分钟会议语料
  上峰值 711 MB。
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
| `amphion-harmony-asr-sdk-v0.3.26-20261029.zip` | 390 MB | `b3ceee1cb5cee3e5adbb9a11243e89c0e67451cffcc2929198829218090e1339` |
| `Amphion-ASR-Diagnostics-SDK.zip` | 774 MB | `8bc78869ffeae3d941368991018eb68a4785c71fcd4f1b82b673816abc5a3ed6` |
