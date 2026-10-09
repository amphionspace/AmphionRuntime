# 角色分离 encoder 上 NPU 的发热矩阵：16 / 30 / 60 分钟真机实测（2026-10-08，Mate 80）

本文回答两个问题，全部为同一台 Mate 80 上的真机实测：

1. 把 Community 说话人 encoder 从 CPU 挪到 Kirin NPU，16 分钟、30 分钟、1 小时连续会议转写各能降多少发热。
2. 能否把 ASR encoder 也挪上 NPU。**结论是不能，而且就算能也会更慢**——证据链见第 6 节。

结论先行（前壳 shell_front，同起点对比）：

| 时长 | CPU encoder 升温 | NPU encoder 升温 | 降幅 | 峰值 CPU→NPU | 进程 CPU 均值 |
|---|---:|---:|---:|---|---:|
| 16 分钟 | +6.86 °C | **+4.79 °C** | **−2.06 °C（−30%）** | 41.14 → 39.17 °C | 235.4% → 204.4% |
| 30 分钟 | +8.90 °C | **+6.11 °C** | **−2.78 °C（−31%）** | 43.20 → 41.07 °C | 240.4% → 208.3% |
| 60 分钟 | +9.26 °C | **+7.13 °C** | **−2.12 °C（−23%）** | 44.90 → 42.59 °C | 249.4% → 212.8% |

三个时长都稳定少升 2 °C 以上，机身峰值低 2.0–2.3 °C，电池峰值低 2–3 °C。识别文本逐字节相同，角色标签帧级一致率 99.2%（16 分钟）/ 100%（30、60 分钟）。

## 1. 测试环境

| 项 | 值 |
|---|---|
| 设备 | HUAWEI Mate 80 `VYG-AL30`，序列号 `7GK0226326015655`，USB 连接并充电，亮屏（`power-shell timeout -o 7200000`） |
| 分支 | `feat/harmony-asr-encoder-npu`（含角色分离 NPU encoder 与 diagnostics 探针），基线提交 `b35dacd1` |
| 构建 | `diagnostics` 模式，`zh_en_only`，六轮共用同一 HAP（同一 source fingerprint），避免跨轮不可比 |
| 角色 encoder（CPU 档） | ORT INT8 `community-wespeaker-encoder` + XNNPACK（4 worker） |
| 角色 encoder（NPU 档） | `community-wespeaker-encoder.fp16.ms`（MindIR，10,661,176 B，SHA-256 `0adae051…8d83b8`），NNRt 设备 `NPU_ohos.boot.hardware.kirin9020_v2_0`，`OH_AI_PERFORMANCE_HIGH` |
| ASR | 同一套 zh-en INT8 zipformer（ORT CPU，4 线程，QoS default，prepack 关闭），两档完全相同 |
| 载体 | `run_device_stress.py --mode paced --cycles 1 --files 1 --pace-ms 20 --enable-diarization --capture-diagnostics --sample-interval 1 --post-run-observe 5 --skip-build-install --diarization-encoder {cpu,npu}` |
| 输入 | AISHELL-4 `S_R003S01C01` ch0，16 kHz 单声道，20 ms 实时喂入 |
| 温度采样 | `hidumper -s ThermalService -a -t`，每 10 s 一次，记录 `shell_front`/`shell_back`/`Battery`/`ambient`/`charger` |

输入片段（每个时长两档用同一文件，逐字节一致）：

| 时长 | 文件 | 样本范围 | SHA-256 |
|---|---|---|---|
| 16 分钟 | `S_R003S01C01_ch0_513800-1473800.wav`（960 s） | 8,220,800–23,580,800 | `66133c62a0f6da69d2b98d96a5d193816e73899fa28340313beb146309c9167d` |
| 30 分钟 | `S_R003S01C01_ch0_0-1800s.wav`（1800 s） | 0–28,800,000 | `8db2f999e08df8bd722960f55c45a505fdd93b3c3a3c87284cead82fbe51e31c` |
| 60 分钟 | `S_R003S01C01_ch0_0-1800s_x2.wav`（3600 s） | 30 分钟片段重复两次 | `3d4b408a8fe502aa046ea1ec6caaee365d6cb91efa24bd23b2b0aabd4c889357` |

60 分钟片段是 30 分钟片段首尾相接，所以 60 分钟档的前半段与 30 分钟档内容完全相同，只有第 1800 s 处有一个拼接点。源音频只有 2220 s，无法提供 3600 s 连续素材。

## 2. 六轮执行顺序与降温记录

每轮开跑之前都把机身降到同一起点。降温判据：目标 `shell_front ≤ 34.0 °C` 且连续 3 个样本（10 s 间隔）极差 ≤ 0.12 °C，上限 2400 s。**六次降温全部用满 2400 s 上限**（状态 `TIMEOUT`）——USB 充电时 `charger` 传感器在 33–37 °C 托底，机身降到 34–35.7 °C 后下降极慢。

| 顺序 | 轮次 | 降温耗时 | 降温起→止 | 本轮起点 |
|---:|---|---:|---|---:|
| 1 | cpu16 | 2406 s | 37.46 → 34.30 °C | 34.28 °C |
| 2 | npu16 | 2406 s | 41.16 → 34.39 °C | 34.38 °C |
| 3 | cpu30 | 2406 s | 39.18 → 34.32 °C | 34.30 °C |
| 4 | npu30 | 2406 s | 43.16 → 34.92 °C | 34.96 °C |
| 5 | cpu60 | 2406 s | 41.02 → 35.66 °C | 35.65 °C |
| 6 | npu60 | 2406 s | 44.16 → 35.48 °C | 35.45 °C |

起点配对质量：16 分钟档相差 0.09 °C，60 分钟档相差 0.19 °C，30 分钟档相差 0.65 °C（NPU 档起点更高，即该档对比对 NPU 不利，而 NPU 仍少升 2.78 °C）。

## 3. 发热结果

### 3.1 汇总

| 轮次 | 起点 | 峰值 | 升温 | 末段 | 后壳峰值 | 电池 | 环境 | 末 6 分钟速率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cpu16 | 34.28 | 41.14 | **+6.86** | 41.14 | 41.64 | 34 → 42 | 28.55 → 28.24 | +0.282 °C/min |
| npu16 | 34.38 | 39.17 | **+4.79** | 39.17 | 39.67 | 34 → 40 | 28.28 → 28.10 | +0.214 °C/min |
| cpu30 | 34.30 | 43.20 | **+8.90** | 43.16 | 43.70 | 34 → 44 | 28.32 → 27.25 | +0.086 °C/min |
| npu30 | 34.96 | 41.07 | **+6.11** | 41.04 | 41.57 | 35 → 42 | 28.17 → 27.70 | +0.093 °C/min |
| cpu60 | 35.65 | 44.90 | **+9.26** | 44.30 | 45.40 | 36 → 45 | 30.70 → 25.02 | −0.031 °C/min |
| npu60 | 35.45 | 42.59 | **+7.13** | 41.56 | 43.09 | 35 → 42 | 28.26 → 26.85 | −0.048 °C/min |

30 分钟档末段速率已降到约 0.09 °C/min，60 分钟档末 6 分钟为负值——两档都已进入平台期（60 分钟档末尾的小幅回落与环境读数下降同步，见 3.3）。

### 3.2 逐分钟曲线（`shell_front`，CPU 档 / NPU 档）

16 分钟：

| 分钟 | 0 | 2 | 5 | 10 | 16 |
|---|---:|---:|---:|---:|---:|
| CPU | 34.28 | 35.58 | 37.33 | 39.32 | 41.06 |
| NPU | 34.38 | 35.27 | 36.29 | 37.80 | 39.11 |
| 差 | −0.09 | +0.31 | +1.04 | +1.52 | **+1.95** |

30 分钟：

| 分钟 | 0 | 5 | 10 | 15 | 20 | 25 | 30 |
|---|---:|---:|---:|---:|---:|---:|---:|
| CPU | 34.30 | 37.28 | 39.26 | 40.79 | 41.96 | 42.67 | 43.11 |
| NPU | 34.96 | 36.72 | 38.05 | 39.06 | 39.87 | 40.45 | 41.07 |
| 差 | −0.65 | +0.56 | +1.21 | +1.73 | +2.09 | +2.22 | **+2.04** |

60 分钟：

| 分钟 | 0 | 10 | 20 | 30 | 40 | 50 | 60 |
|---|---:|---:|---:|---:|---:|---:|---:|
| CPU | 35.65 | 40.15 | 42.68 | 43.34 | 43.88 | 44.52 | 44.70 |
| NPU | 35.45 | 38.92 | 40.48 | 41.43 | 42.14 | 42.31 | 41.74 |
| 差 | +0.19 | +1.23 | +2.20 | +1.91 | +1.74 | +2.21 | **+2.96** |

完整 10 s 采样序列在随附的 `DIARIZATION_NPU_THERMAL_MATRIX_20261008.json`（每轮 `thermalSeries`，含后壳/电池/环境）。

### 3.3 测量条件的诚实说明

- **充电托底**：USB 供电无法断开（hdc 需要连接），`charger` 传感器全程 33–37 °C，因此所有起点只能定在 34–35.7 °C，而非室温。这对两档一致，不影响档间对比，但绝对值不能外推到断电场景。
- **环境漂移**：`ambient` 在 60 分钟档内持续下降（cpu60 30.70 → 25.02 °C，npu60 28.26 → 26.85 °C），这解释了两个 60 分钟档末尾的温度回落。两档起始 ambient 相差 2.4 °C（CPU 档更高，对 CPU 档不利），这是本次六轮里最大的环境不匹配，需要在解读 60 分钟档的 2.12 °C 差值时一并考虑。
- **30 分钟档起点差 0.65 °C**：NPU 档起点更高，属于对 NPU 不利的偏差。

## 4. 负载、内存与功能结果

| 轮次 | 门禁 | 会话时长 | partial/final/errors | CPU 均值 | p50 | p95 | 峰值 | 占设备算力 | RSS 首→尾 | RSS 增长 | RSS 峰值 |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---:|---:|
| cpu16 | PASS | 965 s | 1309 / 74 / 0 | 235.4% | 232.4% | 294.0% | 391.0% | 19.61% | 619 → 658 | 38.8 MB | 728 MB |
| npu16 | PASS | 965 s | 1309 / 74 / 0 | **204.4%** | 201.0% | 266.4% | 318.9% | 17.03% | 621 → 667 | 46.0 MB | 748 MB |
| cpu30 | PASS | 1810 s | 2474 / 130 / 0 | 240.4% | 233.8% | 327.2% | 402.5% | 20.03% | 640 → 732 | 92.9 MB | 889 MB |
| npu30 | PASS | 1810 s | 2474 / 130 / 0 | **208.3%** | 203.2% | 282.5% | 402.8% | 17.35% | 644 → 702 | 57.6 MB | 849 MB |
| cpu60 | **FAIL** | 3621 s | 4947 / 263 / 0 | 249.4% | 239.2% | 354.1% | 456.3% | 20.78% | 661 → 769 | 108.3 MB | 1071 MB |
| npu60 | **FAIL** | 3621 s | 4947 / 263 / 0 | **212.8%** | 205.3% | 302.7% | 391.5% | 17.73% | 676 → 854 | 178.6 MB | 1185 MB |

- CPU 占用三档稳定下降 31–36 个百分点（约 −13%～−15% 相对值），占设备总算力从约 20% 降到约 17%。
- **两个 60 分钟档的门禁都是 FAIL，原因是 RSS 增长超阈值，不是识别失败**：载体的通用阈值为 64 MB，cpu60 增长 108.3 MB、npu60 增长 178.6 MB。SDK 侧 `status=PASS`、空 final 率 0.0%、errors=0。30 分钟档 cpu30 也触发了同一告警（92.9 MB，`generic_status=FAIL`，但整轮判定 PASS）。
- **NPU 档在 60 分钟上的 RSS 增长比 CPU 档更大**（178.6 vs 108.3 MB，峰值 1185 vs 1071 MB）。16/30 分钟档则相反或接近。这是一条独立于发热的待查项，不能用"NPU 更省内存"概括，见第 7 节。

### 4.1 encoder 执行核验

每轮都用 `verify_community_encoder_execution.py` 对 diagnostics 导出做逐窗核验：

| 轮次 | 窗口数 | 后端/设备（逐窗） | encoder 单窗 min / 中位 / p95 / max | 窗口检查 | 整体 |
|---|---:|---|---|---|---|
| cpu16 | 951 | cpu ×951 | 303.3 / 307.7 / 460.8 / 652.3 ms | PASS | PASS |
| npu16 | 951 | `NPU_…kirin9020_v2_0` ×951 | 25.7 / 27.7 / 30.8 / 114.8 ms | PASS | PASS |
| cpu30 | 1791 | cpu ×1791 | 302.6 / 309.0 / 486.0 / 657.1 ms | PASS | PASS |
| npu30 | 1791 | `NPU_…kirin9020_v2_0` ×1791 | 25.5 / 27.7 / 30.9 / 102.0 ms | PASS | PASS |
| cpu60 | 3591 | cpu ×3591 | 303.2 / 326.4 / 495.4 / 692.3 ms | PASS | FAIL※ |
| npu60 | 3591 | `NPU_…kirin9020_v2_0` ×3591 | 25.3 / 27.6 / 30.5 / 48.6 ms | PASS | FAIL※ |

※ 60 分钟两档的 `FAIL` 唯一错误码是 `runner-reported-failure`，即继承了载体整轮的 RSS 门禁失败；`windowChecksStatus` 均为 `PASS`，3591 个窗口的后端与设备逐窗正确。

encoder 单窗中位耗时 **307.7 → 27.7 ms（11.1×）**，三个时长完全稳定。60 分钟 CPU 档中位涨到 326.4 ms、p95 涨到 495.4 ms（热降频），而 NPU 档三档中位都是 27.6–27.7 ms、p95 30.5–30.9 ms，**不随时长和温度退化**；NPU 档的 max 有偶发尖峰（16 分钟 114.8 ms、30 分钟 102.0 ms、60 分钟 48.6 ms），属个别窗口，未影响中位与 p95。

### 4.2 输出一致性（NPU 档 vs CPU 档）

| 时长 | ASR 文本 | 公开窗口数 | 语句数 | 完全匹配语句 | 这些语句的主说话人一致率 | 10 ms 帧级一致率 | 说话人集合 |
|---|---|---|---|---|---|---|---|
| 16 分钟 | 逐字节相同 | 9 / 9 | 126 / 127 | 116（825 s） | 100.00% | 99.21% | 同为 {0,1,2,3,-1} |
| 30 分钟 | 逐字节相同 | 17 / 17 | 211 / 210 | 209（1615 s） | 100.00% | 100.00% | 同为 {0,1,2,3,-1} |
| 60 分钟 | 逐字节相同 | 32 / 32 | 417 / 417 | 414（3229 s） | 100.00% | 100.00% | 同为 {0,1,2,3,-1} |

差异只出现在少数语句的文本切分边界（同一段文本被拆成不同条数），不是标签翻转。这不替代人工 RTTM 精度门禁，MindIR 状态仍为 `converted-not-device-accepted`。

## 5. 结论

1. 角色分离 encoder 上 NPU 在三个时长上都稳定降温 2.07–2.79 °C（相对降幅 23–31%），峰值低 2.1–2.3 °C，电池峰值低 2–3 °C，进程 CPU 低 31–36 个百分点。
2. 降温效果不随时长衰减；30 和 60 分钟都已进入平台期，NPU 档的平台比 CPU 档低约 2–3 °C（60 分钟档的 ambient 起点差 2.4 °C 对 CPU 档不利，解读该档差值时需计入）。
3. 热降频只打击 CPU 档：60 分钟 CPU 档 encoder 中位耗时从 307.7 升到 326.4 ms、p95 升到 495.4 ms，NPU 档三档中位 27.6–27.7 ms 不变。
4. 识别结果不变（文本逐字节相同），角色结果 30/60 分钟帧级完全一致。
5. 发热并未解决，只是缓解：NPU 档 60 分钟仍到 42.59 °C。剩余热源是 ASR——见下一节的归因与尝试。

## 6. 为什么没有"ASR encoder 也在 NPU"这一档

### 6.1 CPU 消耗归因（16 分钟 NPU 档，951 个窗口的诊断日志）

整轮约 1940 CPU·秒（均值 204.4% 单核等效）。拆开：

| 组成 | 该会话累计 | 占总 CPU |
|---|---:|---:|
| **ASR（zipformer 流式解码）+ 框架/诊断日志** | ~1730 CPU·s | **~89%** |
| 角色分割 segmentation（ORT 单线程） | 94.4 s | 4.9% |
| 聚类 AHC/VBx（`clusterElapsedMs`，72 次，中位 657 ms） | 61.0 s | 3.1% |
| fbank 特征 | 23.2 s | 1.2% |
| 说话人 encoder（已在 NPU） | 26.7 s | 1.4% |
| 池化/统计 | 5.8 s | 0.3% |

角色分离链路现在只剩约 11% 的 CPU，继续优化空间很小；大头是 ASR。

### 6.2 尝试把 ASR encoder 搬上 NPU：逐步证据

ASR encoder 是 zipformer2（`decode_chunk_len=64`、`T=77`、`num_encoder_layers=2,2,4,5,4,2`、`encoder_dims=256,384,512,768,512,256`），12,235 节点、117 输入 / 117 输出（116 个 cached state）。

| 步骤 | 结果 | 证据 |
|---|---|---|
| 交付用 INT8 encoder 直接转 MindIR | **失败** | `UNSUPPORTED OP LIST: ONNX DynamicQuantizeLinear / MatMulInteger`——MindSpore Lite 2.7.0 的 ONNX 前端不接受动态量化（`MatMulInteger` ×344、`DynamicQuantizeLinear` ×312） |
| 反量化 INT8 → FP32（`asr/tools/dequantize_asr_encoder.py`，344 组改写） | 成功 | encoder_out 与 INT8 图 cosine 0.99993 |
| 取得上游原生 FP32（`encoder.upstream.fp32.onnx`，616,801,465 B，SHA-256 `8c2e6368…e474ed`） | 成功 | 与反量化版**结构逐项相同**（10,891 节点、每种算子计数一致、117 进 117 出、同 opset），encoder_out cosine 0.99985 → 交付 INT8 实为同源量化 |
| 逐算子族探测 HiAI 接受度（自造固定形状微模型，上机逐个 build+Predict） | 见下 | 接受：MatMul（含 batched）、Softmax、带 bool mask 的完整注意力（0.37 ms）、BiasNorm、SwooshL/R、Sigmoid、Tanh、ReduceSum、Conv（2-D 与 depthwise 1-D）、Transpose/Reshape/Concat/Slice/Gather/Range/Tile/Expand/ConstantOfShape/Where、int32 `Equal`、int64 `Greater`、bool 的 Unsqueeze/Expand/Slice/Concat。**拒绝**：`GatherElements`（任何索引类型）、**float** `Equal`、**float** `LessOrEqual`、恒等 `Cast`（bool→bool）、以及 `Shape`→`Gather`→`Concat`→`Reshape` 动态形状链 |
| 修掉全部拒绝项（`asr/tools/rewrite_asr_encoder_npu_ops.py`） | 成功 | `GatherElements` ×19 → `Reshape+Mul+Add+Gather`（数值精确）；95 处 softplus 溢出保护 `where(log1p(exp z)==+inf, z, ·)` → 稳定式 `max(z,0)+log1p(exp(-|z|))`；恒等 `Cast` ×107 删除；`LessOrEqual` → `Greater+Not`；`Shape` ×574 与 2,582 个常量节点静态折叠。节点 10,891 → 3,766，117 个输出最大差 7.9e-4 |
| 改写后整图在 Kirin NPU 上 build | **失败** | `NNRt: Authentication failed, input model cannot run by npu` → `OH_NNCompilation_Build failed` → `MS_LITE: BuildKirinNPUModel# Create full model kernel failed`，build 287 ms |
| 前缀二分定位边界 | **容量上限** | 前 **741** 节点通过（≈19 层里的前 3.7 层），第 742 节点起整模型被拒。第一个被拒节点是 `Conv /causal_conv_6/Conv`（depthwise，group=384，kernel=16），而**完全相同的卷积在节点 559 和 621 是通过的** → 不是算子不支持，是模型规模过线 |
| 被接受前缀的两端实测（741 节点，20.7 MB MindIR） | **NPU 更慢** | NPU 中位 **39.58 ms**（min 36.41 / max 65.13，build 889 ms）；MS Lite CPU 中位 **23.28 ms**（min 18.82 / max 41.94，build 56 ms）→ **NPU 慢 1.70×** |

反量化版与上游原生 FP32 两条路径给出**完全一致**的结论（边界 749 vs 741 节点、同一个被拒节点、NPU/CPU 比 1.59 vs 1.70）。

上游原生 FP32（`encoder.upstream.fp32.onnx`，616,801,465 B，SHA-256 `8c2e6368…e474ed`，producer `pytorch 2.5.1`）的真机复核逐项记录：

| 环节 | 实测 |
|---|---|
| 改写 | 19 `GatherElements` + 1 `LessOrEqual` + 95 softplus 保护 + 107 恒等 `Cast` + 574 `Shape` 折叠 + 2,582 常量折叠 → 3,766 节点，117 输出最大差 7.9e-4 |
| 转 MindIR | `CONVERT RESULT SUCCESS`，308,088,480 B |
| 整图 NPU build | **FAIL**，`stage=build code=-1 buildMs=287.2` |
| 前缀 741 / 742 | **PASS**（build 851.9 ms）／ **FAIL**（build 450.1 ms） |
| 前缀 741 两端 | NPU 中位 39.58 ms（min 36.41 / max 65.13，build 888.8 ms）；CPU 中位 23.28 ms（min 18.82 / max 41.94，build 55.9 ms）→ **1.70×** |

需要说明：**六轮发热测试不使用这份 FP32**。ASR encoder 上不了 NPU，没有可替换的对象；而把交付用的 INT8 ASR encoder 换成 FP32/MindIR 的 CPU 路径会移动两档共享的 ASR 基线，那样测的就不再是"分离 encoder 后端"这一个变量。六轮里 ASR 始终是同一套 zh-en INT8 zipformer（ORT CPU，4 线程）。

### 6.3 为什么 zipformer 在 NPU 上更慢，而说话人 encoder 快 11 倍

说话人 encoder 是一次性的大密集前向：输入 `[1,998,80]` → 输出 `[1,2560,125]`，单次 Predict 把整段 fbank 算完。zipformer 的一个 chunk 只有 T=77 帧，19 层里全是小张量的 matmul、slice、逐元素操作，算子下发与 NPU↔CPU 数据搬运的固定开销盖过算力收益。这也解释了为什么 conv 子采样前端（59 节点）在 NPU 上是 0.80 ms vs CPU 2.58 ms（快），而整层堆叠起来就反过来。

### 6.4 结论

**这台设备上 ASR encoder 不能也不值得上 NPU**：整图被 HiAI 拒绝（容量上限），而被接受的前 3.7 层在 NPU 上比 CPU 慢 1.70×，拆分执行只会更慢更热，且需要在 sherpa 的 encoder 调用路径里跨两套 runtime 搬运 25 进 32 出的 state，工程代价高、收益为负。MindSpore Lite 的 NNRT delegate 是整模型 offload（`CreateFullModelKernel`），也不会自动做 CPU/NPU 切分。

## 7. 待办

- **60 分钟 RSS 增长**：两档都超过载体 64 MB 阈值（cpu60 108.3 MB，npu60 178.6 MB），NPU 档更高。需要带相位对齐证据的内存排查，这是本次六轮唯一的 FAIL 原因。
- **角色精度门禁**：帧级一致率只说明两档等价，不等于精度合格。MindIR 仍为 `converted-not-device-accepted`，需要 12 例冻结 RTTM 与人工打分。
- **`auto` 后端**与 NPU 路径上的完整生命周期（finish/shutdown/relicense）真机验证仍为 PENDING。
- **断电场景的绝对温度**：本次全程 USB 充电，`charger` 33–37 °C 托底，绝对值不能外推。
- 若将来设备或 MindSpore Lite 支持按子图 offload，前缀二分的工具与设备探针都已就位，可直接复测。

## 8. 产物

| 文件 | 内容 | 所在分支 |
|---|---|---|
| `DIARIZATION_NPU_THERMAL_MATRIX_20261008.json` | 六轮完整 10 s 温度序列（前壳/后壳/电池/环境）、六次降温曲线、载体报告摘要、encoder 逐窗核验摘要 | main |
| `ASR_ENCODER_NPU_FEASIBILITY_20261008.json` | ASR encoder 上 NPU 的逐步证据：算子探测全表、改写计数、二分边界、两端耗时、上游 FP32 复核 | main |
| `DIARIZATION_NPU_ENCODER_HEAT_20261008.md` / `.json` | 当日早先的 16 分钟三臂对比（含冷起点 31 °C 的 CPU 臂），方法学与本文一致 | main |
| `asr/tools/convert_community_encoder.py` / `verify_community_encoder_mindir.py` | 说话人 encoder 的 MindIR 转换与校验工具 | main |
| `delivery/harmony-dingqiao/delivery/verify_community_encoder_execution.py` | encoder 逐窗后端核验（第 4.1 节数据由它产出） | main |
| `asr/tools/dequantize_asr_encoder.py` / `rewrite_asr_encoder_npu_ops.py` | ASR encoder 的反量化与算子改写工具（各带 10 / 16 个单测） | `feat/harmony-asr-encoder-npu` |
| `asr/harmony/sdk/src/main/cpp/mindspore_probe.cpp` + `MindSporeProbe.ets` + demo `MindirProbe.ets` | diagnostics-only 的 MindIR 后端探针（`--ps mindirProbe`），第 6 节的 NPU 接受度与延迟数据由它产出 | `feat/harmony-asr-encoder-npu` |

第 6 节的证据由探针产出，而探针与两个图改写工具**未随说话人 encoder 合入 main**：它们只服务于已判定不可行的 ASR encoder 实验，留在 `feat/harmony-asr-encoder-npu` 分支备查。

原始运行目录（本机临时区，不入库）：`thermal-pair/out/{cpu16,npu16,cpu30,npu30,cpu60,npu60}/20261008-*-paced-*/`，含 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、`diagnostics/run-*/`。
