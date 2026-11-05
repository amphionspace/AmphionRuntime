# Amphion HarmonyOS ASR 0.3.27 组包前验收摘要（1ac8d93f）

本摘要记录 0.3.27 冻结身份、本版改动与组包前真机证据。受检报告为 `customer-ptt`（必需模式）与
`diarization-windows`（角色归属改由声纹身份决定的直接证据，4 条 ≥ 120 s 的客户现场录音）。
`speaker-vad-turn` 本轮按豁免登记（见"豁免"）。

## 冻结身份

| 项 | 值 |
|---|---|
| 版本 | 0.3.27，版本日期 2026-11-04 |
| 源码提交 | `1ac8d93f`（分支 `release/harmony-0.3.27`，自 `main` 的 #286 合并提交切出，工作区干净）。取代同版本的两次早前冻结：`316135a4`（Release 子包被组包校验拦下：随包 CHANGELOG 当前版本节缺交付边界声明）与 `b84bb51d`（从完整 ZIP 装回的诊断 HAP 报 versionName 0.3.26 / versionCode 326：演示工程 AppScope、根 `oh-package.json5` 与 entry 模块版本未随 0.3.27 同步）。本提交相对 `316135a4` 只多一行 CHANGELOG 与三处版本号（327），SDK 源码、构建输入与原生库完全相同；构建身份绑定提交，故全部构建与真机报告在本提交重做 |
| 基线 | 0.3.26（客户已收到，带 speaker-vad-turn 豁免），源码 `927bda6e` |
| 语种范围 | 中英（ZH_EN） |
| 设备 | 我方测试机（HarmonyOS，arm64-v8a；机型与序列号见外置最终报告） |
| Diagnostics 子包构建模式 | `diagnostics` |
| Release 子包构建模式 | `debug` |
| 签名 | 本地 DevEco 自签证书（`signing-project`），叶证书有效期至 2049-03-16 |
| 授权核验 | 设备白名单文件为空（授权不绑设备），与 0.3.26 口径一致 |
| API 23 编译器 | 独立 OpenHarmony 6.1 es2abc，sha256 `279d82ed…`，与 0.3.23~0.3.26 同一二进制 |
| 原生库 | 与 0.3.26 相同（`libonnxruntime.so` sha256 `57abce89…`，provenance 一致）；sherpa/third_party 自 0.3.26 起零提交 |

## 本版改动（相对客户已收到的 0.3.26）

| 改动 | 文件 | 说明 |
|---|---|---|
| **角色归属改由声纹身份决定，默认开启** | `SpeakerIdentityAssigner.ts`、`SpeakerIdentityResolver.ets`、`DiarizationPcmWindow.ts`、`SpeakerTimeline.ts`、`SpeakerDiarizationSession.ets`、`SpeechRecognizeSdk.ets` | 新增 `SpeakerDiarizationConfig.speakerIdentityMode`（`'voiceprint'` 默认 / `'model'` 回退）与 `SpeakerTurn.modelSpeakerIndex`；嵌入只取每段前 3 s；并入阈值 0.50 |
| **静音不再被转写出"嗯"** | `EffectiveSpeechBuffer.ts`、`Runtime.ets`、`SpeakerTurnFinalizer.ts` | 非空文本需独立声学证据（−74 dBFS 发布门限或 VAD 确认）才发布；两端同步 |
| 原生 Sortformer 模块的跨平台整理 | `sortformer_diarization.cpp` | 日志宏与文件路径加载封装（Android 共用源码）；鸿蒙行为不变；由 HAR 构建时 CMake 编译 |
| 版本与文档 | `oh-package.json5` ×5、`AppScope`、`RuntimeIdentity.ts`、`CHANGELOG.md`、`UPGRADE_0.3.27.md`、接口文档 | 版本 0.3.27 / versionCode 327；压测载体 `speakerIdentityMode` 选项默认改为跟随 SDK |

## 真机证据

### 1. 生命周期与资源（`customer-ptt`，12 cycle）

报告带 diagnostics 构建身份（源码提交 `1ac8d93f`，源码指纹 `f3e2785d…`，与 smoke 构建身份一致）；随包副本为 `reports/customer-ptt-report.json`。

| 项 | 结果 |
|---|---|
| 总判定 | **PASS**（`failures: []`） |
| cycle 状态 | 12/12 全部 PASS |
| SDK 契约 | `sdk=PASS` |
| 空 final 率 | **0.000**（上限 0.05，计数 0） |
| 内存 | `memory=PASS`，RSS 390.4 → 398.6 MiB，增长 8.21 MiB，峰值 417.5 MiB（HWM 426.4 MiB），线程 52 → 48 |
| 原生流 | 12 cycle 观测，泄漏 0 |
| CPU | 单核等效均值 123.6%，p95 158.7% |

### 2. 角色分离链路（`diarization-windows`，4 条客户现场录音 ≥ 120 s，合计 902.2 s）

本提交上一次执行即通过，为受检报告（随包副本 `reports/diarization-windows-dq4-report.json`）。

结果（声纹身份按本版默认开启）：

| 项 | 结果 |
|---|---|
| 总判定 | **PASS**（`failures: []`） |
| cycle 状态 | 4/4 全部 PASS |
| 角色分离生命周期 | `PASS`，4 个会话全部完成 |
| 每条录音的角色结果数 | 4 / 2 / 2 / 2（契约要求 ≥ 2） |
| 结束到最终角色结果 | 1114 / 1334 / 2416 / 1783 ms；推理 RTF 0.255~0.271 |
| 空 final 率 | 0.000 |
| 内存 | 通用判定 PASS；角色分离模式下资源评估为 advisory（`INCONCLUSIVE`，需阶段对齐证据）。RSS 756.8 → 812.4 MiB，增长 55.61 MiB，峰值 878.2 MiB，HWM 915.4 MiB，斜率 4.1 MiB/min（15 分钟窗口内）；线程 76 → 76；CPU 单核等效均值 185.7%，p95 278.7% |

内存读数与 143.8 分钟长跑的观察一致：前段上升、约 805 MB 进入平台、瞬时峰值接近 1 GB；0.3.26 同模式峰值为 711 MB，差额来自默认开启的声纹路径（嵌入已限制为每段前 3 s）。

## 豁免

| 模式 | 理由 |
|---|---|
| `speaker-vad-turn` | 目标说话人夹具在本机不可重建：生成文本断言所需的主机 `sherpa-onnx` 二进制不可用（旧构建缺 `libonnxruntime.1.24.4.dylib`，当前派生树无主机构建）。0.3.26 曾实跑该模式：6 例归属断言全部通过（机主的话在、非机主的话不在），仅载体自设的 1200 ms 收尾预算未达成；该预算此后已按实测放宽到 2000 ms。本版未改动机主识别相关代码（`Runtime.ets` 改动限于"嗯"门禁）。 |

## 过程记录

- 构建身份绑定冻结提交；所有文档与版本改动在第一次构建前完成提交。相对 `316135a4`，本提交只多 CHANGELOG 0.3.27 节的交付边界一行（`validate_asr_sdk_delivery.py` 要求随包 CHANGELOG 当前版本节含"目标说话人增强…不包含…不能启用"）和演示工程三处版本号（`test_release_defaults` 的版本一致性要求），SDK 源码与原生库不变。
- 两次早前冻结的同参数真机结果（保留于各自暂存目录，不随包；SDK 二进制与本提交逐字节同源，作为本轮结果的印证）：
  `316135a4`：`customer-ptt` 12/12 PASS（增长 41.71 MiB、峰值 437.8 MiB）；`diarization-windows` 第三轮 4/4 PASS、角色结果数 4/2/2/2、RSS 增长 60.25 MiB、峰值 855.0 MiB、HWM 942.4 MiB（第一轮 79 s 时 hdc 连接中断、第二轮操作者误判终止，均无报告）。
  `b84bb51d`：`customer-ptt` 12/12 PASS（增长 20.64 MiB、峰值 416.9 MiB）；`diarization-windows` 第二轮 4/4 PASS、4/2/2/2、增长 61.77 MiB、峰值 855.0 MiB、HWM 925.0 MiB（第一轮 696 s 时主机侧一次 `/proc` 读取失败被判"载体已退出"，设备上实际跑完）；从其完整 ZIP 装回的 `customer-ptt --installed-package` 12/12 PASS（增长 16.66 MiB、峰值 415.5 MiB），正是这一步暴露了 Demo HAP 版本号仍为 0.3.26。
- 脱敏门禁对 CHANGELOG、UPGRADE_0.3.27、接口文档、接入文档通过。
- 鸿蒙主机门禁 61 个模块通过；压测脚本单测 73/73；交付校验 24/24；仓库布局/可观测性/版本检查通过。
- Release 子包第一次打包被自包含 HAR 校验拦下：`_bundled/sherpa_onnx` 内的 `libsherpa-onnx-c-api.so` 与 SDK 本地库不一致。
  排查结论：SDK 本地库、诊断 HAP、调试 HAP 以及客户已收到的 0.3.26 内的库四者逐字节相同（sha256 `392ca65a…`，
  2026-10-29 含热词补丁 0036/0037 的构建）；不一致的是 2026-11-02 新建的 sherpa 派生源码树被播种了 2026-10-15 的旧库
  （`630630c0…`，缺这两个补丁）。两棵派生树源码逐文件一致。旧库只进入了 `sherpa_onnx.har`，HAP 打包时被 `amphion_asr`
  的同名库覆盖，**从未到过设备**，诊断身份与两份真机报告不受影响。处置：按 `asr/tools/05_package_har_libs.sh` 把派生树
  HAR 库同步为同一构建（SDK 本地库字节不变），重新执行调试构建与 Release 子包打包。后续应在构建预检中增加"SDK 本地库 ==
  派生树 HAR 库"的一致性检查（列入交付后的工具改进，不进入本版冻结提交）。
