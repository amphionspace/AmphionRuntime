# 角色分离 encoder 迁移 NPU 的 16 分钟发热对比（2026-10-08，Mate 80 已完成）

结论先行：同一台 Mate 80、同一个诊断构建、同一段 960 秒会议音频，把 Community 说话人 encoder 从 CPU（ORT INT8）切到 Kirin NPU（MindSpore Lite MindIR）之后，**同起点（35.0 °C）跑 16 分钟，前壳升温由 +5.80 °C 降到 +3.52 °C，少升 2.28 °C（−39%）**；进程 CPU 单核等效占用由 234.5% 降到 201.1%；encoder 单窗耗时中位由 308 ms 降到 27.7 ms（11.1×）。ASR 文本逐字相同，角色标签 10 ms 帧级一致率 99.2%。发热有明显缓解，但没有消失：NPU 臂仍在以约 0.18 °C/min 的速度升温，剩余热源是 ASR 解码、分割、特征与聚类，这些仍在 CPU 上。

## 测试环境

| 项 | 值 |
|---|---|
| 设备 | HUAWEI Mate 80 `VYG-AL30`，序列号 `7GK0226326015655`，USB 连接并充电，亮屏 |
| 分支 / 基线提交 | `feat/harmony-diarization-npu-encoder`，基于 `b35dacd1`（main，PR #257 合并点）+ 本分支未提交改动 |
| 构建 | `diagnostics` 模式，`zh_en_only`，HAP SHA-256 `cf6b356c…a595753`（431,811,048 字节），源码指纹 `7303730d…652035` |
| encoder 模型 | CPU 臂：ORT INT8 `community-wespeaker-encoder`；NPU 臂：`community-wespeaker-encoder.fp16.ms`（MindIR，10,661,176 字节，SHA-256 `0adae051…8d83b8`） |
| NNRt 设备 | `NPU_ohos.boot.hardware.kirin9020_v2_0`，`OH_AI_PERFORMANCE_HIGH` |
| 载体 | `run_device_stress.py --mode paced --cycles 1 --files 1 --pace-ms 20 --enable-diarization --capture-diagnostics --sample-interval 1 --post-run-observe 5 --skip-build-install --diarization-encoder {cpu,npu}` |
| 输入 | AISHELL-4 `S_R003S01C01` ch0，源样本 8220800..23580800（513.8–1473.8 s），960 秒 16 kHz 单声道，WAV SHA-256 `66133c62…9167d`（与 `.cache/harmony-community-npu-gitarm64.ocMMdS/implementation-status.md` 核验值一致） |
| ASR 配置 | 4 线程，QoS default，prepack 关闭，spinning 开启 |
| 温度 | `hidumper -s ThermalService -a -t` 每 10 s 一次，取 `shell_front`（前壳）为主指标，同时记录 `shell_back`、`Battery`、`ambient`、`charger` |
| 亮屏 | 测试期间 `power-shell timeout -o 1800000`，结束后已恢复为原值 600000 ms |

## 测试臂与起点

| 臂 | encoder | 起点 shell_front | 起点前冷却 | 说明 |
|---|---|---:|---|---|
| A | CPU | 31.10 °C | 41 s 到稳定（设备此前空闲，环境 24.3 °C） | 冷起点基线 |
| B | NPU | 35.02 °C | A 结束后 1095 s（38.06 → 35.04 °C） | 充电状态下机身降到约 35 °C 后不再下降（`charger` 36.6–37.2 °C 托底），无法回到 31.1 °C |
| C | CPU | 34.91 °C | B 结束后 781 s（37.93 → 35.02 °C） | 与 B 同起点的 CPU 复测，用于公平对比 |

稳定判据：连续 3–5 个样本（10 s 间隔）前壳温度极差 ≤ 0.05–0.12 °C；B、C 另加目标温度 ≤ 35.05 °C。冷却时间已按用户要求逐臂记录。

## 发热结果（shell_front，括号内为相对各自起点的升温）

| 分钟 | A CPU（起 31.10） | C CPU（起 34.91） | B NPU（起 35.02） | C−B |
|---:|---:|---:|---:|---:|
| 0 | 31.10 (+0.00) | 34.91 (+0.00) | 35.02 (+0.00) | -0.11 |
| 1 | 31.88 (+0.78) | 35.49 (+0.59) | 35.08 (+0.06) | +0.42 |
| 2 | 32.81 (+1.70) | 36.17 (+1.26) | 35.40 (+0.38) | +0.77 |
| 3 | 33.47 (+2.37) | 36.67 (+1.76) | 35.70 (+0.68) | +0.97 |
| 4 | 34.13 (+3.03) | 37.13 (+2.23) | 35.97 (+0.95) | +1.16 |
| 5 | 34.69 (+3.58) | 37.58 (+2.67) | 36.26 (+1.24) | +1.32 |
| 6 | 35.21 (+4.10) | 37.97 (+3.07) | 36.54 (+1.52) | +1.44 |
| 7 | 35.60 (+4.50) | 38.20 (+3.30) | 36.76 (+1.74) | +1.45 |
| 8 | 36.07 (+4.96) | 38.51 (+3.61) | 37.03 (+2.01) | +1.48 |
| 9 | 36.43 (+5.32) | 38.82 (+3.92) | 37.26 (+2.24) | +1.56 |
| 10 | 36.81 (+5.71) | 39.14 (+4.23) | 37.48 (+2.46) | +1.66 |
| 11 | 37.16 (+6.06) | 39.38 (+4.48) | 37.63 (+2.61) | +1.75 |
| 12 | 37.52 (+6.42) | 39.72 (+4.82) | 37.82 (+2.80) | +1.90 |
| 13 | 37.84 (+6.74) | 40.01 (+5.10) | 38.00 (+2.98) | +2.01 |
| 14 | 38.19 (+7.09) | 40.30 (+5.40) | 38.22 (+3.21) | +2.08 |
| 15 | 38.48 (+7.38) | 40.54 (+5.64) | 38.40 (+3.38) | +2.14 |
| 16 | 38.82 (+7.72) | 40.70 (+5.80) | 38.54 (+3.52) | +2.16 |

| 指标 | A CPU | C CPU | B NPU |
|---|---:|---:|---:|
| 前壳峰值 | 38.89 °C | 40.74 °C | 38.62 °C |
| 前壳升温（峰值 − 起点） | +7.79 °C | +5.84 °C | +3.60 °C |
| 后壳峰值 | 39.39 °C | 41.24 °C | 39.12 °C |
| 电池温度 | 30 → 39 °C | 35 → 42 °C | 35 → 39 °C |
| 最后 6 分钟升温速率 | 0.34 °C/min | 0.26 °C/min | 0.18 °C/min |

同起点对比（C vs B）是本次的主结论：16 分钟少升 2.28 °C，电池温度少升 3 °C。A 臂起点更冷，升温绝对值最大，但它与 B 不同起点，不能直接相减；A 臂从 35.02 °C 起算的后 637 s 升了 +3.84 °C，B 臂同样 637 s 升了 +2.54 °C，方向与 C/B 一致。

## 负载与功能结果

| 指标 | A CPU | C CPU | B NPU |
|---|---:|---:|---:|
| 载体门禁 | PASS | PASS | PASS |
| 会话时长 | 965.5 s | 965.5 s | 965.4 s |
| partial / final / errors | 1309 / 74 / 0 | 1309 / 74 / 0 | 1309 / 74 / 0 |
| 进程平均 CPU（单核等效） | 232.2% | 234.5% | 201.1% |
| CPU p50 / p95 / 峰值 | 228.7% / 298.1% / 378.7% | 232.4% / 298.3% / 438.7% | 198.0% / 259.1% / 344.9% |
| 占设备总算力 | 19.35% | 19.54% | 16.75% |
| RSS 首 / 尾 / 峰值 | 621 / 653 / 781 MiB | 618 / 652 / 718 MiB | 623 / 659 / 711 MiB |
| encoder 窗口数（诊断导出） | 951 | 951 | 951 |
| encoder 后端 / 设备 | cpu / cpu ×951 | cpu / cpu ×951 | npu / `NPU_ohos.boot.hardware.kirin9020_v2_0` ×951 |
| encoder 单窗耗时 min / 中位 / p95 / max | 303.1 / 309.4 / 457.1 / 608.8 ms | 302.9 / 308.0 / 456.3 / 645.4 ms | 25.7 / 27.7 / 30.7 / 107.0 ms |
| `verify_community_encoder_execution.py` | PASS | PASS | PASS |

951 个窗口 × 约 281 ms 的 encoder 节省，折合约 267 s 的 CPU 时间从 16 分钟会话里移走；进程 CPU 下降约 33 个百分点与此吻合。剩余的约 200% CPU 来自 ASR 流式解码、分割模型、fbank 特征与聚类。

### 输出一致性（B NPU vs A CPU）

- ASR 文本结果（`resultHex`）逐字节相同。
- 公开角色结果：两臂均 9 个窗口、说话人索引集合 {0,1,2,3,-1}；126/127 条语句中有 116 条（824.7 s）窗口、起止时间、文本完全相同，这些语句的主说话人标签 100% 一致；其余差异全部集中在窗口 0，是同一段文本的切分边界不同（例如“考虑到的包括没有做到的，还是中环这一块儿的话，”在 NPU 臂被拆成两条），不是标签翻转。
- 10 ms 帧级主说话人一致率 99.21%。

这与用户 30 秒短片配对观测（63 对 embedding cosine 中位 0.9979、角色区间完全一致）方向一致。它仍不是人工 RTTM 精度门禁；MindIR 状态保持 `converted-not-device-accepted`。

## 过程中的问题

1. **设备被并行占用导致前两次 CPU 臂作废。** 04:26 与 04:48 两次 `diarization-windows` 运行都没有拿到 SUMMARY；hilog 显示同一时间段 demo 进程在执行另一条流水线的 `finish-shutdown-relicense` 运行（产物在 `.cache/harmony-community-npu-gitarm64.ocMMdS/`），UIAbility 单实例被占用，本会话的 want 没有执行。之前记录的“载体在 16.1 分钟被 PROCESS_KILL”与“屏幕超时”判断不成立，本次已改为 `paced` 模式并与用户的短片对比保持同一套参数。
2. **`verify_community_encoder_execution.py` 在 paced 模式误报 `runner-diagnostic-session-count-mismatch`。** 载体在没有 finish-recovery 阶段的模式下写 `recoveryStarts=-1`，验证器把它直接累加进期望会话数（1 + (−1) = 0 ≠ 1）。用户的 30 秒短片恰好因导出事件被环形缓冲裁掉而“通过”。已在验证器中把负哨兵按 0 处理（`max(int(...), 0)`），14 个单元测试通过，三臂重新验证均 PASS。
3. **充电托底。** USB 供电下机身降到约 35 °C 后不再下降（`charger` 传感器 36.6–37.2 °C，`ambient` 读数在 B 臂前升到 28.3 °C），所以 B、C 臂只能在 35 °C 同起点对比，而不是 A 的 31 °C。

## 评估边界

- 证据覆盖：同一 HAP、同一输入、请求后端在 951 个成功窗口上的记录，以及厂商 BuildModel / NPU graph client Init 日志（见 `readonly-native-raw-audit.md`）。不能证明图内全部 58 个算子都在 NPU 执行、无 CPU fallback 子图，也不能证明 FP16 全图计算。
- 内存评估为 INCONCLUSIVE（载体通用判据），三臂 RSS 斜率 3.1–3.3 MiB/min 相近，与 encoder 后端无关。
- `auto` 后端、完整生命周期（finish/shutdown/relicense）在 NPU 路径上的真机验证、人工身份精度门禁、两小时长测仍待做。

## 产物

- 本文随附 `DIARIZATION_NPU_ENCODER_HEAT_20261008.json`：三臂 10 s 温度序列、报告摘要、encoder 执行验证摘要、三次冷却记录。
- 原始运行目录（本机临时区，不入库）：`thermal-pair/out/{cpu,npu,cpu2}/20261008-*-paced-*/`，含 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、`diagnostics/run-*/`。
