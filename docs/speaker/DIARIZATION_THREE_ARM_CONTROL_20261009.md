# 角色分离到底贵多少：ASR-only / 角色分离 CPU / 角色分离 NPU 三档 16 分钟对照（2026-10-09，Mate 80）

本文只回答一个问题：在同一台设备、同一个 HAP、同一段 960 秒会议音频下，**打开角色分离这条链本身要多少代价**，以及把它的 encoder 从 CPU 挪到 NPU 能拿回多少。三档先后连续执行，每档前各自降温，起点对齐到 0.79 °C 以内（第三档受充电托底只到 34.70 °C，见第 1 节）。

结论先行（前壳 `shell_front`，三档起点差 0.79 °C）：

| 档 | 配置 | 起点 | 峰值 | 升温 | 进程 CPU 均值 | 峰值 RSS | 公开角色窗口 |
|---|---|---:|---:|---:|---:|---:|---:|
| `asronly16` | 仅识别，角色分离关闭 | 33.91 | 35.96 | **+2.06** | 181.0% | 567.6 MB | 0 |
| `diarcpu16` | 识别 + 角色分离，encoder 在 CPU | 33.98 | 40.35 | **+6.37** | 234.0% | 715.0 MB | 9 |
| `diarnpu16` | 识别 + 角色分离，encoder 在 NPU | 34.70 | 40.06 | **+5.37** | 203.7% | 760.5 MB | 9 |

- 角色分离（encoder 在 CPU）在识别之上多升 **+4.31 °C**，多占 **+53.0** 个百分点 CPU，多占 **+147.3 MB** 峰值内存。
- 角色分离（encoder 在 NPU）在识别之上多升 **+3.31 °C**，多占 **+22.7** 个百分点 CPU，多占 **+192.9 MB** 峰值内存。
- 同一套角色分离、只换 encoder 后端：NPU 比 CPU 少升 **-1.00 °C**，少占 **-30.3** 个百分点 CPU。

**起点差必须先说清**：三档起点极差 0.79 °C，其中 NPU 档比 CPU 档高 0.72 °C。NPU 档的升温（+5.37 °C）比 CPU 档（+6.37 °C）小 1.00 °C，但它同时比 CPU 档**起点更高**，所以这 1.00 °C 是“起点更高”与“encoder 更快”两个因素叠在一起的结果，从峰值相减无法把两者分开。
用三档**共同覆盖时长**（971 s，即第三档的完整采样跨度）重算升温，起点差的影响被同一口径吸收：

| 档 | 共同窗口起点 | 共同窗口终点 | 共同窗口升温 |
|---|---:|---:|---:|
| `asronly16` | 33.91 | 35.96 | **+2.06** |
| `diarcpu16` | 33.98 | 40.16 | **+6.18** |
| `diarnpu16` | 34.70 | 40.03 | **+5.34** |

同一口径下 NPU 档仍比 CPU 档少升 0.84 °C、比 ASR-only 多升 +3.28 °C；结论方向不变，但 **−1.00 °C 这个具体数字受 0.72 °C 起点差影响，不能当作精确的 encoder 净收益**。

## 1. 三档设计与起点对齐

| 项 | 值 |
|---|---|
| 设备 | HUAWEI Mate 80 `VYG-AL30`，序列号 `7GK0226326015655`，USB 连接并充电，亮屏 |
| 构建 | `diagnostics` / `zh_en_only`，提交 `fac938c0`，源码指纹 `64fd6df3` |
| HAP | `amphion_asr_demo.hap` SHA-256 `a70223a6…`（三档同一个 HAP） |
| 说话人 encoder | `community-wespeaker-encoder.fp16.ms` SHA-256 `0adae051…`（CPU 档为 ORT INT8，NPU 档为同一 MindIR） |
| 输入 | AISHELL-4 `S_R003S01C01` ch0，960 秒 16 kHz 单声道；语料 SHA-256 `777e7922…`（三档同一文件） |
| 载体 | `run_device_stress.py --mode paced --cycles 1 --files 1 --pace-ms 20 --capture-diagnostics --sample-interval 1 --post-run-observe 5 --skip-build-install`，ASR 固定 4 线程 / QoS default / 关 prepack |
| 温度采样 | `hidumper -s ThermalService -a -t`，每 10 s 一次 |
| 降温判据 | `shell_front ≤ 34.0 °C` 且连续 3 样本极差 ≤ 0.12 °C，上限 2400 s |

角色分离档额外参数：`--enable-diarization`，其中 NPU 档再加 `--diarization-encoder npu`。**没有**换构建、没有换输入、没有换 ASR 参数，三档之间唯一的变量就是角色分离与它的 encoder 后端。

起点与降温记录：

| 档 | 降温耗时 | 降温起→止 | 本轮起点 | 起点相对目标 |
|---|---:|---|---:|---:|
| `asronly16` | 31 s（STABLE） | 33.75 → 33.91 °C | 33.91 °C | -0.09 |
| `diarcpu16` | 954 s（STABLE） | 35.96 → 33.98 °C | 33.98 °C | -0.02 |
| `diarnpu16` | 2396 s（TIMEOUT） | 40.20 → 34.67 °C | 34.70 °C | +0.70 |

三档起点极差 0.79 °C：前两档判据满足后自行停止，第三档用满 2396 s 上限仍停在 34.67 °C。降不到 34.0 °C 的原因是 USB 供电无法断开（hdc 需要连接）：`charger` 传感器全程托底，机身降到 34 °C 附近后下降极慢。

## 2. 发热结果

### 2.1 汇总

| 档 | 起点 | 峰值 | 升温 | 末段 | 后壳峰值 | 电池 | 环境 | 充电器 | 末 6 分钟速率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `asronly16` | 33.91 | 35.96 | **+2.06** | 35.96 | 36.46 | 34 → 36 | 28.23 → 28.21 | 34.05 → 36.83 | +0.077 °C/min |
| `diarcpu16` | 33.98 | 40.35 | **+6.37** | 40.22 | 40.85 | 34 → 41 | 28.04 → 27.88 | 34.35 → 42.47 | +0.261 °C/min |
| `diarnpu16` | 34.70 | 40.06 | **+5.37** | 40.05 | 40.56 | 34 → 41 | 28.34 → 29.69 | 34.80 → 42.53 | +0.150 °C/min |

峰值出现在：`asronly16` 第 16.2 分钟；`diarcpu16` 第 14.8 分钟；`diarnpu16` 第 14.7 分钟。

### 2.2 逐分钟前壳曲线

| 分钟 | ASR-only | 角色分离 CPU | 角色分离 NPU | CPU − ASR-only | NPU − ASR-only |
|---:|---:|---:|---:|---:|---:|
| 0 | 33.91 | 33.98 | 34.70 | +0.07 | +0.79 |
| 2 | 34.31 | 35.75 | 35.62 | +1.43 | +1.31 |
| 5 | 34.93 | 37.06 | 37.34 | +2.13 | +2.40 |
| 10 | 35.52 | 38.53 | 38.87 | +3.01 | +3.35 |
| 12 | 35.71 | 39.11 | 39.28 | +3.41 | +3.57 |
| 14 | 35.81 | 39.88 | 39.81 | +4.08 | +4.00 |
| 16 | 35.92 | 40.22 | 40.01 | +4.29 | +4.08 |

把每分钟增量拆开看，三档的升温都集中在前 10 分钟，之后逐段收窄；两条角色分离曲线在整个 16 分钟里都稳定高于 ASR-only，差值不是靠某一段拉开的。

## 3. 负载与内存

| 档 | 门禁 | 会话时长 | partial/final/errors | CPU 均值 | p50 | p95 | 峰值 | 占设备算力 | RSS 首→尾 | RSS 增长 | RSS 峰值 |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---:|---:|
| `asronly16` | PASS | 961 s | 1309 / 74 / 0 | 181.0% | 181.4% | 220.0% | 267.7% | 15.08% | 515 → 542 | 27.3 MB | 567.6 MB |
| `diarcpu16` | PASS | 964 s | 1309 / 74 / 0 | 234.0% | 232.6% | 295.2% | 420.1% | 19.50% | 619 → 654 | 35.9 MB | 715.0 MB |
| `diarnpu16` | PASS | 964 s | 1309 / 74 / 0 | 203.7% | 200.7% | 258.6% | 395.7% | 16.98% | 622 → 673 | 50.7 MB | 760.5 MB |

- 识别负载三档完全相同（1309 partial / 74 final / 0 errors），差别只在角色分离。
- 内存判据：载体的通用阈值是 RSS 增长 ≤ 64 MB。`asronly16` PASS（增长 27.3 MB，PASS）；`diarcpu16` INCONCLUSIVE（增长 35.9 MB，PASS）；`diarnpu16` INCONCLUSIVE（增长 50.7 MB，PASS）。
- 三档都完成了唯一 last → 唯一 complete（completes=1）。
- **峰值内存上 NPU 档反而更高**：NPU 档 760.5 MB，比 CPU 档高 45.6 MB，比 ASR-only 高 192.9 MB。这与既有六轮同向（cpu16 727.7 / npu16 748.4 MB、cpu30 888.6 / npu30 848.8 MB、cpu60 1070.9 / npu60 1185.1 MB，NPU 在两档更高、一档更低），是独立于发热的待查项，不能概括成“NPU 更省内存”。
- 注意区分两件事：**encoder 本身**在 NPU 上单窗 27.6 ms（CPU 307.9 ms），省下的是算力与发热；**角色分离整条链**（分割、聚类、特征、缓冲）与 NPU 运行时的常驻开销是 ASR-only 之上那 +192.9 MB 的主要来源。

## 4. encoder 执行核验

每档都用 `verify_community_encoder_execution.py` 对 diagnostics 导出做逐窗核验：

| 档 | 窗口数 | 后端/设备（逐窗） | encoder 单窗 min / 中位 / p95 / max | 窗口检查 | 整体 |
|---|---:|---|---|---|---|
| `asronly16` | 0 | 不适用（角色分离关闭，不产生 encoder 窗口） | 不适用 | 未运行 | 不适用 |
| `diarcpu16` | 951 | cpu ×951；cpu ×951 | 302.8 / 307.9 / 447.7 / 645.2 ms | PASS | **PASS** |
| `diarnpu16` | 951 | npu ×951；NPU_ohos.boot.hardware.kirin9020_v2_0 ×951 | 25.9 / 27.6 / 30.8 / 71.4 ms | PASS | **PASS** |

两档的核验调用方式（可复现，含两个易踩的口径）：

```
diarcpu16:
  verify_community_encoder_execution.py --run-directory <run>/diagnostics/run-* --report <run>/report.json --build-identity <full build identity from report.json> --requested-backend cpu --require-backend cpu --require-device ''
diarnpu16:
  verify_community_encoder_execution.py --run-directory <run>/diagnostics/run-* --report <run>/report.json --build-identity <full build identity from report.json> --requested-backend npu --require-backend npu --require-device kirin
```

- `--build-identity` 必须用报告根 `report.json` 的完整 `build_identity`；diagnostics 导出里那份只有 4 个键，用它会得到 `captureBinding=INCONCLUSIVE` 且所有 artifact 报 missing。
- `--require-device` 默认 `kirin`；CPU 档的设备名就是 `cpu`，不显式传空串会把 951 个窗口全判成 `wrong-device`。
- NPU 档 `kirinAcceptance=PASS`。

encoder 占用率（用哈希绑定的逐窗 `encoderMs` 乘窗口数除以会话时长）：

| 档 | 公开窗口 | 单窗中位 | 累计占用 | 会话时长 | 占用率 |
|---|---:|---:|---:|---:|---:|
| `asronly16` | 0 | 不适用 | 不适用 | 961 s | 不适用 |
| `diarcpu16` | 951 | 307.9 ms | 292.9 s | 964 s | **30.4%** |
| `diarnpu16` | 951 | 27.6 ms | 26.2 s | 964 s | **2.7%** |

此占用率由本 SDK 自己的逐窗耗时推出，不是硬件计数器读数。设备不开放 NNRt 利用率计数器（`/sys/class/devfreq`、`/sys/devices/platform`、`/sys/kernel/debug` 对 shell 均为 Permission denied，`hidumper -ls` 无 NNRt/NPU/HiAI 服务），因此这是可测的替代口径。

## 5. 识别与角色输出一致性

### 5.1 识别输出

| 档 | 识别文本（resultHex） | 公开窗口 | 语句数 | 说话人集合 | 降级窗口 |
|---|---|---:|---:|---|---:|
| `asronly16` | 逐字节相同（16588 hex 字符） | 0 | 74 | 不适用 | 不适用 |
| `diarcpu16` | 逐字节相同（16588 hex 字符） | 9 | 74 | [-1, 0, 1, 2, 3] | 0 |
| `diarnpu16` | 逐字节相同（16588 hex 字符） | 9 | 74 | [-1, 0, 1, 2, 3] | 0 |

三条 `resultHex` 的 SHA-256 完全一致（`finalChars` 同为 4147），识别输出不受角色分离与 encoder 后端影响。

### 5.2 角色输出（CPU 档 vs NPU 档）

| 项 | 值 |
|---|---|
| 公开窗口数 | 9 / 9 |
| 窗口序号一致 | 是 |
| 窗口起止时间一致 | 是 |
| 语句数 | 126 / 127 |
| 起止时间与文本完全相同的语句 | 116 条 |
| 这些语句的主说话人标签不一致数 | **0** |
| 这些语句的次说话人集合不一致数 | 2 |
| 完全一致语句覆盖时长 | 824.7 s / 853.2 s（96.7%） |
| 说话人索引集合 | [-1, 0, 1, 2, 3] / [-1, 0, 1, 2, 3] |
| 降级窗口 | 0 / 0 |

差异全部落在少数语句的**文本切分边界**上（同一段话被拆成不同条数，例如“考虑到的包括没有做到的，还是中环这一块儿的话，”在 NPU 档被拆成“考虑到的包括没有做到的，”与后续两条），起止时间与文本都相同的 116 条语句里**主说话人标签零不一致**，次说话人集合有 2 条不同。这与既有 16 分钟两臂对比的结论一致（当时 116/127 条相同、帧级一致率 99.21%）。

**这只是两档等价性，不是精度合格**：两档输出相同也可能是同一处错。MindIR 仍为 `converted-not-device-accepted`，人工 RTTM 精度门禁见第 6 节。

## 6. 评估边界与待办

- **充电托底**：全程 USB 供电，`charger` 全程 34.0–42.5 °C 托底，三档起点只能在 34 °C 附近对齐，绝对值不能外推到断电场景。
- **单次 16 分钟**：每档只有一轮，未做重复轮次；结论是方向性配对差值，不是统计置信区间。
- **起点差 0.79 °C，其中 NPU 档比 CPU 档高 0.72 °C**：这是本组最需要在引用时带上的一句话，第 2 节的共同窗口口径已经把方向确认下来，但没有第二轮就无法把“起点更高”与“encoder 更快”完全分开。
- **峰值内存反直觉**：NPU 档比 CPU 档高 45.6 MB。既有六轮里 NPU 档在 16 分钟与 60 分钟更高（+20.7 / +114.2 MB）、30 分钟更低（−39.8 MB），三比一，说明不是偶然，但根因未定位。
- **角色精度门禁**：本组数据只证明三档等价，不证明精度合格；MindIR 仍为 `converted-not-device-accepted`，仍需 12 例冻结 RTTM 与人工打分。
- **60 分钟档没有 ASR-only 基线**：既有 60 分钟对照只有 encoder 两档，缺 ASR-only 就无法把长时发热归因到角色分离；若要闭合这条，需要再补一轮 60 分钟 ASR-only。
- **`auto` 后端与完整生命周期**（finish/shutdown/relicense）在 NPU 路径上的真机验证仍为 PENDING。

## 7. 产物

| 文件 | 内容 | 所在分支 |
|---|---|---|
| `DIARIZATION_THREE_ARM_CONTROL_20261009.json` | 三档完整 10 s 温度序列、三次降温曲线、载体报告摘要、encoder 逐窗核验摘要、配对增量与共同窗口口径 | main |
| `DIARIZATION_NPU_THERMAL_MATRIX_20261008.md` / `.json` | 同一台设备的六轮 encoder 后端矩阵（16/30/60 分钟），本文与之共享温度采样与载体口径 | main |
| `delivery/harmony-dingqiao/delivery/verify_community_encoder_execution.py` | 逐窗核验器；本次在其异常分支补了真实异常输出（原来只打印一句笼统的 invalid/missing，把 `ValueError: missing full diagnostic journal` 这类原因吞掉），判定逻辑未改 | main |

原始运行目录（本机临时区，不入库）：`/private/tmp/claude-501/-Users-momo/73f52aa3-78e5-4ee7-b3cc-19e67ffb06b2/scratchpad`

复现本组数据的最小步骤（三个脚本都在下文的原始运行目录里，按自身路径解析输入输出）：

```
python3 thermal-pair/analyze-three-arm.py     # 读温度序列与 report.json，产出 three-arm-summary.json
zsh    thermal-pair/verify-three-arm.sh       # 两档 encoder 逐窗核验，产出 encoder-verify-*.json
python3 thermal-pair/analyze-three-arm.py     # 再跑一次，把核验结果并入 summary
python3 thermal-pair/render-three-arm-doc.py  # 由 summary 生成本文，表格数字不手抄
```

运行时序（设备本地时间）：三档共用同一天连续执行，每档前按同一判据降温：

- `asronly16`：降温 31 s（STABLE），会话 961 s，runId `20261008-194048-paced-3a704bfb`
- `diarcpu16`：降温 954 s（STABLE），会话 964 s，runId `20261008-201256-paced-377a4dc2`
- `diarnpu16`：降温 2396 s（TIMEOUT），会话 964 s，runId `20261008-210929-paced-bebecd54`

## 8. 口径说明

- 所有温升都是 `峰值 − 本轮起点`，不是相对室温；三档起点已对齐到 0.79 °C 以内。
- 配对差值（CPU − ASR-only、NPU − ASR-only）是同起点直接相减，三档共用同一 HAP、同一输入、同一 ASR 参数。
- 同一 HAP：是；同一源码指纹：是；同一语料：是。

> Front-shell thermals are device-side ThermalService readings; the encoder-execution section covers the carrier's hash-bound per-window export only and does not prove that every graph operator ran on NPU.

