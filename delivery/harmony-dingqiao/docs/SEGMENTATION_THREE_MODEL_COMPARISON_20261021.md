# 三个角色分离模型同机实测对比：Community-1 / Conformer ep5 / NMNet 学生

2026-10-21。同一台设备、同一段语料、同一套参数，一次跑完三个模型。

**结论：ep5 以 1.85× 的计算代价换来分割网络升级，仍在实时预算内；nmnet 9.13× 不可用。目前没有任何一个候选在精度上被证明优于 Community-1。**

| 项 | 值 |
| --- | --- |
| 设备 | HUAWEI nova 15（PSN-AL00），麒麟 8020，`6CT9K26130017501` |
| 系统 | OpenHarmony-6.0.2.130 |
| 载体 | demo 0.3.24 diagnostics |
| 语料 | `dingqiao-meeting-20260918`，5 段真实客户会议，16 kHz 单声道，共 1010.6 s |
| 参数 | `--mode diarization-windows --enable-diarization --files 0 --cycles 5` |
| 代码基线 | `10aa01f6`（= `main`）；nmnet 轮为 `4bfff185`（`perf/nmnet-student-diarization`） |

---

## 1. 关于 NPU

**这台设备有可用 NPU，但分割网络用不上它。**

encoder 实测解析到 `NPU_ohos.boot.hardware.kirin8020_v2_0`，三轮中 Community 路线的 encoder 均值稳定在 18~19 ms，确认 NNRt 通路正常。

分割网络无法迁移，三条独立证据：

1. `asr/harmony/sdk/src/main/cpp/speaker_turn_segmenter.cpp` 是纯 ORT CPU —— 第 70 行 `Ort::SessionOptions` 未注册任何 execution provider，第 98 行 `Ort::MemoryInfo::CreateCpu`。**SDK 里根本不存在分割走 NPU 的代码路径**，而 encoder 另有一整套 MindSpore Lite / NNRt 实现（`community_diarization.cpp:167`）。
2. 本机没有 `converter_lite`，ONNX→MindIR 的第一步就做不了。
3. 仓库既往探测记录（`DIARIZATION_NPU_THERMAL_MATRIX_20261008.md` 第 10 节）：分割模型上 NPU「前 3 节点可用、前 8 节点崩溃」，元凶算子（2-D MaxPool / 第二个 InstanceNormalization / LeakyRelu）未定位，4 个双向 LSTM 未测到。

因此三轮的分割全部在 CPU 上跑。这反而使对比更干净：**encoder 同在 NPU、特征与聚类同为 CPU，差异只来自分割网络本身。**

> ep5 是 Conformer，不含 LSTM，所以上条第 3 点的疑似元凶未必适用于它。但在没有 `converter_lite` 和分割 NPU 代码路径之前，这只是未验证的推测。

---

## 2. 计算开销

| 模型 | 窗口 | 单窗 wall | 分割 | 嵌入 | encoder | 计算合计 | RTF | 相对基线 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Community-1**（现网） | 489 | 123.7 ms | 147.6 ms | 23.9 ms | 18.8 ms（NPU） | **75.00 s** | **0.0742** | 1.00× |
| **Conformer ep5** | 489 | 249.6 ms | **389.8 ms** | 25.3 ms | 18.4 ms（NPU） | **138.40 s** | **0.1369** | **1.85×** |
| **NMNet 学生** | 460 | 1488.2 ms | 898.0 ms | 533.2 ms | 510.7 ms（CPU） | **684.59 s** | **0.6774** | **9.13×** |

ep5 这一行最值得看的是**没变的那几列**：嵌入 23.9→25.3 ms、encoder 18.8→18.4 ms，与基线一致。这从运行时侧证实了它确实只替换分割网络，交付说明中「embedding / pooling / 特征 / PLDA 保持原样」属实。

**代价集中在分割一项：147.6 → 389.8 ms，2.64×。** 参数量是 3.57×（5,253,937 vs 1,473,515），耗时增幅低于参数增幅，属次线性。

nmnet 则是整条管线替换：encoder 掉到 CPU（510.7 ms，基线在 NPU 上是 18.4 ms）、分割 898 ms、嵌入 533 ms，没有一项可比。

---

## 3. 资源与功耗

| 模型 | RSS 峰值 | vm_data 峰值 | CPU 均值 | CPU p95 | 功率均值 | 电池温度 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Community-1 | 754.2 MiB | 1450.2 MiB | 193.1% | 263.9% | −328.1 mW | 32.0 °C |
| Conformer ep5 | **799.7 MiB**（+45.5） | 1891.0 MiB | 215.5%（+12%） | 292.3% | −325.1 mW | 34.0 °C |
| NMNet 学生 | **1658.2 MiB**（+904） | 3837.0 MiB | 356.0%（+84%） | 510.8% | −322.3 mW | **38.0 °C** |

ep5 的资源代价很小：RSS 只多 45.5 MiB，远小于模型本身增加的 15.2 MiB 磁盘 + ORT arena 的直觉预期；CPU 只高 12%。

**功率读数不可用于结论**：三者均值在 −322~−328 mW 之间，与 CPU 占用（193% / 215% / 356%）完全不相关。原因是 USB 供电掩盖了电池净放电。**电池温度是更可信的代理**：32 → 34 → 38 °C，与计算量单调一致。

---

## 4. 角色归属

| 模型 | 声学 turn | 公开句 | `-1` 句 | 出现的编号 |
| --- | ---: | ---: | ---: | --- |
| Community-1 | 278 | 53 | 15 | −1, 0, 1, 2, 3 |
| Conformer ep5 | **490** | 51 | 17 | −1, 0, 1, 2, 3 |
| NMNet 学生 | **92** | 46 | 29 | −1, 0, 1, 2, 3 |

ep5 的声学 turn 数是基线的 1.76 倍（490 vs 278），说明它的边界切得更细。但**公开句的 `-1` 数量没有改善**（15 → 17），说明更细的边界没有直接转化为更好的文字归属。

nmnet 的 turn 只有基线的三分之一（92），`-1` 句接近一倍（29），与 Mate 80 上的结论一致。

**这不是精度结论。** 本轮未注册声纹，`-1` 数量只反映「有多少文字拿不到归属」，不反映归属对不对。真正的精度要看 DER，见下节。

---

## 5. 精度：只有 ep5 有第三方口径的数据

| 模型 | DER 证据 |
| --- | --- |
| Community-1 | cn118 基准（交付方评测）：时长加权 **21.27%**，meeting 级 21.18% |
| Conformer ep5 | cn118 同口径：时长加权 **21.85%（+0.58，更差）**，meeting 级 **21.01%（−0.17，略好）**，剔除 aishell4 的 98 条 **20.79%（−0.30，好）** |
| NMNet 学生 | **无**。其迁移文档明写「当前不处理…客户精度结案」「不证明学生角色分离精度」 |

ep5 的分数据集差异很大：`magicdata_ramc` 大幅领先（14.38% vs 20.66%）、`cs_dialogue` 领先，但 `aishell4`、`alimeeting_2023`、`alimeeting_sdm` 落后。

**三项重要限制**：

1. 这是**交付方自测**，口径为 collar=0、计重叠、无 UEM；我们这边没有 cn118 标注语料，**无法独立复现**。
2. ep5 是**训练中途的检查点** —— 原计划 30 epoch，`best_ep5.pt` 只训了 5 个 epoch（step 8965），导出时训练仍在继续，不是收敛结果。
3. 我们自己的客户语料上**没有标注真值**，所以第 4 节只能给归属密度，给不了对错。

---

## 6. ep5 的集成风险（装机前必须处理）

### 6.1 兼容性：已验证通过

| 检查 | 结果 |
| --- | --- |
| SHA256 | `sha256sum -c SHA256SUMS` **OK**，21,215,455 字节，`7c86b1df…` |
| 张量契约 | 名称/dtype/秩/opset 与现用文件一致；589 帧、step 270、receptive field 991 不变，native 侧 `community_cluster.h` 的 589×3 索引无需改动 |
| 窗口样本 | 固定 160000，与 `SpeakerDiarizationLocalClient.ets:9` 的 `WINDOW_SAMPLES = 160000` 吻合 |
| 算子 | 两模型二进制静态比对：ep5 引入 `LayerNormalization`(60)、`Softmax`(12)、`Sigmoid`、`Gemm` 等，弃用 `LSTM`(5)。**全部标准 ONNX 算子，无 contrib/自定义算子**（注意力被拆成 MatMul/Softmax/Div） |
| ORT 版本 | 交付方用 ORT 1.31.0 导出，我们锁 1.16.3。`LayerNormalization` 是 opset 17 标准化，模型 opset 17 ≤ ORT 1.16 支持的 opset 19 |
| ORT 构建 | `asr/tools/harmony_onnxruntime_flags.cmake`：`MINIMAL_BUILD OFF`、`EXTENDED_MINIMAL_BUILD OFF`、`REDUCED_OPS_BUILD OFF`、`DISABLE_CONTRIB_OPS OFF` —— **完整构建、无算子裁剪** |

实测也印证了：ep5 在 ORT 1.16.3 上跑完 489 个窗口、489 次分割，无报错。

### 6.2 Android 升级后旧模型会残留（真实缺陷）

`DingqiaoSpeakerModelAssets.kt:98`：

```kotlin
private fun isReady(file: File, minBytes: Long): Boolean =
    file.isFile && file.canRead() && file.length() >= minBytes
```

只在目标文件**缺失或小于门槛**时才重新解包，**没有任何内容校验**。分割模型门槛是 `SEGMENTATION_MIN_BYTES = 5 MiB`，而旧模型 **5,986,908 字节 > 5 MiB** —— 升级后旧副本被判为"就绪"，**新模型永远不会生效**。

同组另 4 个 community 资产用的是**精确字节数**（如 `"community-wespeaker-encoder.int8.onnx" to 5_468_354L`），只有分割模型用了宽松下限。修法与同组一致即可：改成精确大小。

**鸿蒙不受影响** —— 它经 `Runtime.ets:548` 的 `getRawFileContent` 直接从 rawfile 读，rawfile 随 HAP 整体替换。

### 6.3 许可与 NOTICE 必须同步

装入的**不是** pyannote 权重，文件名沿用只因 SDK 硬编码 `SEGMENTATION_FILENAME`。需改两处：

| 文件 | 现状 |
| --- | --- |
| `shared/models/asr/dingqiao/pyannote-segmentation-3.0.LICENSE` | 当前是 pyannote 的 MIT 正文 |
| `NOTICE` 第 108–119 行（第 7 节） | 写的是 pyannote 的仓库、revision `733a93b…`、(c) 2023 CNRS |

实际模型为 `c1gpu.conformer_segmentation.ConformerSegmentation`，SincNet 结构与 powerset(3,2) 契约沿用 pyannote.audio（MIT），`ConformerLayer` 来自 torchaudio（BSD-2-Clause），权重自训练。交付方 `LICENSE-NOTE.md` 指出其自训练权重的许可策略尚未声明。

### 6.4 交付方的安装脚本在 macOS 上跑不了

`install_to_sdk.sh` 逻辑安全（`--dry-run` 只读、先备份 `.bak`、复制后验 sha256、可 `--restore`），但依赖 GNU 工具：本机 bash 3.2 无 `mapfile`，`stat -c` 是 GNU 语法。本轮改用仓库原生方式安装，仓库内需替换的源文件只有 2 处：

```
shared/models/asr/dingqiao/pyannote-segmentation-3.0.onnx
asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/pyannote-segmentation-3.0.onnx
```

---

## 7. 判定

| 维度 | Community-1 | Conformer ep5 | NMNet 学生 |
| --- | --- | --- | --- |
| 时延 | RTF 0.0742 | RTF 0.1369（1.85×），**仍有约 7 倍余量** | RTF 0.6774（9.13×），**不可用** |
| 内存 | 754 MiB | 800 MiB（+45） | 1658 MiB（+904） |
| 发热 | 32 °C | 34 °C | 38 °C |
| 精度 | 基准 | cn118 口径互有胜负，训练未收敛 | 无数据 |
| 集成 | — | 真·原地替换，native 无需改动 | 整条管线替换，与仓库发布门禁冲突 |

**nmnet：不建议继续。** nova 15 上 9.13× 的结论与 Mate 80 上的 8.14× 一致，换设备不改变量级。

**ep5：可以继续评估，但现在不能上。** 时延与资源代价可接受，集成干净。阻塞项是精度 —— 它是第 5 个 epoch 的中途检查点，cn118 上时长加权口径还比现网差 0.58 个百分点。合理的做法是**等训练收敛后再评一次**，同时在我们自己的客户语料上建立标注，否则我们只能复述交付方的自测数字。

---

## 8. 本轮未覆盖

- **分割网络上 NPU 的可行性未验证**。需要 `converter_lite`、一条分割专用的 MindSpore Lite 会话、以及 Conformer 算子在 NNRt 上的支持度探测。ep5 不含 LSTM，与既往探测的疑似元凶不同，值得单独做一轮，但这是独立工作量。
- **DER 未独立复现**。缺 cn118 标注语料。
- **未注册声纹**，所以第 4 节只有归属密度，没有身份正确率。
- **Android 未装机**，三轮均为鸿蒙。
- **跨设备对比仅供参考**。Mate 80（麒麟 9020 / OpenHarmony-6.1.1.120）上基线 RTF 为 0.0994、nmnet 为 0.8084；nova 15 上对应 0.0742 与 0.6774。两台设备的绝对值不可直接比较，但**相对倍数一致**（8.14× vs 9.13×）。
- **ep5 轮与 nmnet 轮的代码基线不同**：ep5 轮在 `10aa01f6`（含 #36 修复），nmnet 轮在 `4bfff185`（分叉于 #36 之前）。该修复位于文字投影层，不影响分割与推理计时，但会影响第 4 节的 `-1` 句计数。

## 9. 证据

| 轮次 | 产物 |
| --- | --- |
| nova 15 基线 | `.local/perf/nova15-baseline/20261021-051011-diarization-windows-a20c3bc4` |
| nova 15 ep5 | `.local/perf/nova15-ep5/20261021-053408-diarization-windows-91c45c21` |
| nova 15 nmnet | `.local/perf/nova15-nmnet/20261021-055817-diarization-windows-9aa4126d` |

统计口径与 `NMNET_DIARIZATION_BASELINE_20261020.md` 第 14 节一致：窗口分项取 `events.full.ndjson`（**不是** `events.ndjson`）；CPU 由 `process_cpu_ticks` 差分换算为单核等效；功率取 hilog 的 `PowerSampler` 行。

### 为跑通测量所做的临时改动（均未提交）

- 这台设备不在 license 绑定列表，且 `deviceInfo.serial` 需系统权限 `ohos.permission.sec.ACCESS_UDID`，签名 profile 的 `acls` 为空、demo 也未申请，所以 SDK 直接返回 `LICENSE_DEVICE_MISMATCH`（`License.ets:256` 要求白名单非空时必须能读到 SN）。本轮改签一份**不绑定设备**的 license（`deviceHashes = 0`）绕开该检查，并用一个空设备清单满足 `verify_license_device_set.py`。测量结束后 `.secure/` 已还原。
- nmnet 轮沿用 `AMPHION_SKIP_COMMUNITY_MINDIR_GATE`（见 `NMNET_DIARIZATION_BASELINE_20261020.md` 第 13 节），且因 `harmony_build_identity.py` 仍会失败，改为直接 `hdc install` 已签名的 HAP。
- 三轮结束后仓库已还原：分支回到 `main`、分割模型 sha 回到 `057ee564…`、设备清单回到 8 行。
