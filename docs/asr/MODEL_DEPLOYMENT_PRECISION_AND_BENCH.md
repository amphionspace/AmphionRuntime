# 端侧模型：部署精度、编译打包流程与既有性能指标

**整理日期**：2026-10-25
**范围**：端侧 ASR（转写）与 diarization（角色分离）/ 声纹模型。只记录仓库内可复核的事实；
没有实测依据的一律标注「无实测」，不做估算。

> 本文回答四个问题：
> 1. 实际部署时各模型是 INT8 还是 FP32；
> 2. 编译打包要走哪些步骤、每步输出什么；
> 3. 这套流程会产出哪些指标；
> 4. 我们**之前**测过哪些模型侧指标（功耗、时延、内存、热），实测值是多少。

---

## 1. 实际部署精度

### 1.1 结论表

判定依据：① manifest 声明的 `source_name`；② 对部署件做量化算子扫描
（`DynamicQuantizeLinear` / `MatMulInteger` / `MatMulIntegerToFloat` / `QuantizeLinear` /
`DequantizeLinear` 等）；③ 文件体量与 FP32 对应物的比例。

| 模型 | 部署文件 | 源文件 | 体量 | **部署精度** | 判定依据 |
| --- | --- | --- | ---: | --- | --- |
| ASR encoder | `encoder.int8.ort` | `encoder.int8.onnx` | 162.0 MB | **INT8（动态量化）** | 扫到 `DynamicQuantizeLinear`+`MatMulInteger`+`MatMulIntegerToFloat`；FP32 对应物 617 MB（`.cache/asr-encoder-npu/encoder.dequantized.fp32.onnx`），比例 ≈ 1:3.8 |
| ASR decoder | `decoder.ort` | `decoder.onnx` | 17.5 MB | **FP32** | 无量化算子；源文件无 `.int8` 后缀 |
| ASR joiner | `joiner.int8.ort` | **`joiner.onnx`** | 16.4 MB | **FP32** | 无量化算子；**源文件无 `.int8` 后缀，体量与源一致** |
| 标点 | `model.int8.ort` | `model.int8.onnx` | 75.5 MB | **INT8** | 源文件带 `.int8` |
| VAD | `silero_vad.onnx` | 同名 | 0.6 MB | **FP32** | 无量化算子 |
| 分离-分割 | `pyannote-segmentation-3.0.onnx` | 同名 | 6.0 MB | **FP32** | 无量化算子 |
| 分离-speaker encoder | `community-wespeaker-encoder.int8.onnx` | 同名 | 5.5 MB | **INT8（QDQ）** | 扫到 `QuantizeLinear`+`DequantizeLinear` |
| 分离-pooling | `community-wespeaker-pool.fp32.onnx` | 同名 | 5.3 MB | **FP32** | 文件名与算子一致 |
| 分离-特征变换 | `community-feature.f32` | — | 83 KB | **FP32** | 原始浮点数据 |
| 分离-PLDA | `community-plda.f64` | — | 398 KB | **FP64** | 原始双精度数据 |
| 机主声纹 | `eres2net.onnx` | 同名 | 39.6 MB | **FP32** | 无量化算子 |
| 分离-NPU 变体（鸿蒙） | `community-wespeaker-encoder.fp16.ms` | 由 fp32 ONNX 转 | 10.7 MB | **FP16（MindIR）** | 仅在显式指定 NPU 后端时使用，见 1.3 |

### 1.2 两个需要注意的点

**(a) `joiner.int8.ort` 的文件名名不副实。**
manifest 里它的 `source_name` 是 `joiner.onnx`（不带 `.int8`），部署件里扫不到任何量化算子，
体量 16.4 MB 与源文件 16.4 MB 基本一致。若真是 INT8，体量应约为 FP32 的 1/4。
**实际部署的 joiner 是 FP32**，文件名中的 `.int8` 是历史命名遗留。
`delivery/harmony-dingqiao/docs/MODEL_LOAD_PERFORMANCE.md` 第 15 行写的
`joiner.int8.onnx → joiner.int8.ort` 也沿用了这个错误来源名。

**(b) 混合精度而非统一精度。**
转写链路是 **INT8 encoder + FP32 decoder + FP32 joiner**。encoder 占 162 MB / 全链路约 196 MB，
是量化收益的主体；decoder/joiner 体量小，保持 FP32。
分离链路是 **FP32 分割 + INT8 encoder + FP32 pooling + FP32 特征 + FP64 PLDA**。

### 1.3 角色分离 encoder 的后端默认值

`SpeakerDiarizationLocalClient.ets:72` 的 `encoderBackend` 取值为 `cpu` / `npu` / `auto`，
**省略时默认 `cpu`**。因此：

- 生产默认路径 = **CPU + INT8 ONNX**（`community-wespeaker-encoder.int8.onnx`）
- FP16 MindIR（`.ms`）只在显式传 `npu` 或 `auto` 时才可能被加载
- 压测工具 `run_device_stress.py --diarization-encoder` 默认是 `auto`，与 SDK 默认值**不一致**，
  读历史压测报告时要看该字段实际值
- NPU 路径当前不可用：`docs/harmony/ASR_NPU_RETEST_20261023.md` 实测 encoder 被
  `Authentication failed, input model cannot run by npu` 拒绝

---

## 2. 编译打包流程

### 2.1 Android

入口：`asr/tools/delivery/pack_dingqiao_customer_delivery.sh`

| 步骤 | 动作 | 产出/校验 |
| --- | --- | --- |
| 前置 | `asr/tools/04_build_android_so.sh arm64-v8a` | `libsherpa-onnx-jni.so`、`libonnxruntime.so`；校验 NEEDED 依赖 |
| `[1/4]` | build release AAR + 合并 fat AAR | `dingqiao-asr-v<ver>.aar`；逐项校验 native lib、增强资产、ASR 模型资产是否齐全；校验 manifest v2 与 9 个模型资产；校验 pinned ZH_EN ONNX MD5；校验 pinned ITN verbalizer SHA-256 |
| `[2/4]` | build Demo APK（与 fat AAR 对齐） | demo APK |
| `[3/4]` | 组装客户交付树 | SDK/demo/文档/许可 |
| `[4/4]` | 打 zip（UTF-8 EFS） | 交付 zip |

### 2.2 HarmonyOS

入口：`delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh`

关键前置与约束：

- 需要 `HARMONY_API23_ES2ABC` 指向 OpenHarmony 6.1 / API 23 的 `es2abc`
- release 打包要求 worktree 干净（否则需 `--allow-dirty`，但那不是 release 包）
- 需要 `HARMONY_SIGNING_CONFIG` 或 `.secure/harmony-signing.json`
- 用锁目录串行化，防止并发打包
- `--sdk-only` 与 `--asr-only` 互斥

调用的校验器：

- `validate_asr_sdk_delivery.py` —— 交付结构与文案校验
- `harmony_build_identity.py` —— 构建身份（绑定 git HEAD）
- `check_customer_delivery_redaction.py` —— 脱敏检查
- `sanitize_public_har_payload.py` —— HAR 载荷清理
- `filter_zh_en_model_payload.py` —— 模型裁剪（zh-en only）
- `create_normalized_tar.py` —— 可复现归档
- `asr_release_tracker.py` —— 发布台账登记

### 2.3 真机构建/安装/冒烟

入口：`delivery/harmony-dingqiao/delivery/build_install_smoke.sh`

`--build-mode debug|diagnostics`；流程为「构建 → 签名 → 校验 → 安装 → 启动 → 等引擎 ready」。
输出 `build/smoke/build-identity.json`（含 `git_commit`、`model_manifest_sha256`、
`native_sha256`、`source_fingerprint_sha256`、`zh_en_only`）。

校验项包括：HAP 签名/profile/身份/许可/arm64 运行时、HAP 证书链与签名配置是否匹配、
NAPI/C API 符号兼容性、manifest v2 与模型资产、pinned ONNX MD5。

---

## 3. 这套流程产出的指标

### 3.1 打包阶段（正确性门禁，非性能）

体量与哈希、manifest 一致性、pinned 模型 MD5/SHA-256、native 符号兼容性、
签名与许可、脱敏、发布台账登记。**这一层不产出功耗/时延指标。**

### 3.2 真机压测 `run_device_stress.py`

单次运行采集载体进程的 **RSS / VmData / VmSwap / 线程数 / SDK 回调契约 / native 流状态**。
主要指标字段：

- **内存**：`rss_growth_mb`、`rss_slope_mb_per_minute`、三段 RSS 中位数、
  `rss_growth_limit_enforced`
- **时延**：`maximum_endpoint_latency_ms`、`maximum_endpoint_to_final_ms`、
  `maximum_finish_latency_ms`、`maximum_finish_to_final_ms`、`maximum_processing_ms`、
  `finishToCompleteMs`、`finishToFirstNonEmptyResultMs`、`customer_stop_latency`、
  `speech_end_latency` / `speech_end_ms`、`direct_confirmation_ms`、`dispatch_after_ready_ms`、
  `overlapping_decode_wait_ms`
- **吞吐/排队**：`maximum_queued_chunks`、`minimum_buffered_frames`、`chunk_count`、
  `steady_state_chunk_interval_ms`
- **功耗**：`--sample-power` 开启后由 `PowerSampler.ets` 以 1 Hz 记录
  `uv`（微伏）、`ma`（毫安）、`mw`（毫瓦 = uv×1e-6×ma）、`soc`、`charge`、`plug`、
  `battC`（电池温度）。**定位为 diagnostics-only，不作为门禁**
- **正确性**：`completed_sessions`、`empty_finals`、`failed_cycles`、`recovery*` 系列、
  `overall_status`

判定门槛（普通 ASR 默认）：**RSS 增长 ≤ 64 MiB、线程增长 ≤ 2**。
长会话/会议场景不再把 64 MiB 单独作为硬否决，改为比较整个进程头尾窗口，报告记
`rss_growth_limit_enforced=false`，资源结论为 `INCONCLUSIVE`；线程超限仍为 FAIL。
显式传 `--max-rss-growth-mb N` 则恢复硬预算。斜率至少需 60 秒观测。

压测模式覆盖 `burst` / `paced` / `vad-begin` / `voiceprint*` / `cancel` /
`max-duration` / `continuous-long-session` / `reconfigure` / `recreate` / `edge` /
`reentrant` / `target-speaker-enhancement` 等 20+ 种。

### 3.3 模型加载基准 `run_model_load_bench.py` + `ModelLoadBench.ets`

输出一行 `LOADBENCH|version=2|api=createEngineAsync|runId=...|status=...|coldMs=...|poolHitMs=...|fatal=...`，
即**冷加载耗时**与**进程内 pool 命中耗时**。

### 3.4 温度

`PowerSampler` 只给电池温度（`battC`）。**机身温升用的是设备暴露的
`shell_front` / `shell_back` / `shell_frame`**，口径为「机身温升、按起始温度归一化」。

明确不用电池温度：10-04 一轮已证明插 USB 且亮屏时各组 16 分钟都升 9–11 °C，
组间没有可测差别（`docs/speaker/DIARIZATION_BRANCH_HEAT_20261007.md:44`）。

---

## 4. 之前测过的模型侧指标（实测值）

### 4.1 模型加载时延（鸿蒙真机）

来源：`delivery/harmony-dingqiao/docs/MODEL_LOAD_PERFORMANCE.md`
条件：`createEngineAsync`、ORT 1.16.3 / CPU EP / ARM / Fixed / 全图优化、ORT worker 4、
eager warmup 0 samples、进程内 single-flight + pool。

| 阶段 | 冷加载 p50 | 冷加载 p95 | pool hit p50/p95 |
| --- | ---: | ---: | ---: |
| 优化前 ONNX 串行路径 | 3884.5 ms | 4010.55 ms | 不适用 |
| ORT + mmap + 异步并行 + pool | 864 ms | 893.4 ms | 0/1 ms |
| 4 worker | 859 ms | 899 ms | 0/1 ms |
| 跳过冗余 eager warmup | **774.5 ms** | **810.25 ms** | 0/1 ms |

相对初始 p50 降低约 **80.1%**。关键路径是约 155 MiB encoder 的 Session 创建与权重预打包。

单次冷启（凉机、用户实际首启）口径：

| 模型格式 | 冷加载 |
| --- | ---: |
| ORT（优化） | **约 730 ms**（p50 740.5 / p95 774.1；20 轮 648–776 无漂移） |
| ONNX（未优化） | **约 2.6 s**（20 轮 min 2740 / 10 轮 min 2605） |

48 轮真实 WAV burst 回归：48/48 完成、空 final 4.17%、首轮 120 ms、总耗时 21858 ms、
**峰值 RSS 571.863 MiB**（该短跑的 RSS slope 仅作观察，不作泄漏结论）。

### 4.2 角色分离 RTF 与机身温升（鸿蒙真机）

来源：`docs/speaker/DIARIZATION_BRANCH_HEAT_20261007.md`
变更：角色分离窗口 hop 1 s → 2 s（窗口数减半）。

| 指标 | hop=1s | hop=2s | 变化 |
| --- | ---: | ---: | ---: |
| 角色分离 RTF | 0.3065 | 0.1601 | **−47.8%** |
| 机身温升（按起始温度归一化） | 6.16 °C | 4.50 °C | −1.66 °C |
| 整段 DER | 3.12% | 3.23% | +0.11 pp |

两组起始机身温度 26.47 / 27.07 °C。待机 `shell_front` 31.3–31.7 °C，环境 21.3 °C，电量 82%。
同一构建 960 秒对照 RTF 0.30649 → 0.30653（第四位小数内）。

聚类侧另一轮优化（`DIARIZATION_AHC_COST_20260928.md`）：Mate 80 上同一 180 秒片的
18 次聚类总耗时 **8075 ms → 2600 ms**（跳过必定被拒的短段重复拟合）。

### 4.3 语音结束 → final 时延（鸿蒙真机）

来源：`delivery/harmony-dingqiao/docs/SPEECH_END_LATENCY_20260915.md`
USB 基线 PSN-AL00 / OpenHarmony-6.0.2.130，同一客户录音，20 ms 实时输入：
普通 / Speaker VAD 分别为 **1802 ms / 1799 ms**，均判 FAIL。
`vadEnd=1600ms` 约束的是输入音频上的连续静音时长。
Speaker VAD 开启时声学细化阻塞有序音频处理，单次细化约 1503 ms。

### 4.4 角色分离边界时延（鸿蒙真机）

来源：`delivery/harmony-dingqiao/docs/SPEAKER_BOUNDARY_LATENCY_20260916.md`
原现场 20 次 VAD endpoint 均等待约 **1626 ms**；endpoint 后处理 **18–95 ms**。
仅 Demo 开启角色分离时使用 `vadEnd=800`。

### 4.5 TTS 时延与内存（安卓真机，1000 次）

来源：`tts/android/docs/DINGQIAO_V3_ANDROID_1000_STABILITY_TEST_REPORT_20260713.md`

| 指标 | 均值 | P50 | P95 | 最大 |
| --- | ---: | ---: | ---: | ---: |
| 首包 firstPacketMs | 174 ms | 169 ms | 247 ms | 288 ms |
| RTF | 0.23 | 0.21 | 0.25 | 0.93 |
| 电池温度峰值 | 40.4 °C | 41.0 °C | 44.0 °C | 44.0 °C |
| Java heap 峰值 | 126.9 MB | 140.1 MB | 163.9 MB | 313.8 MB |

另一批 199 次（`ANDROID_TTS_BATCH_TEST_REPORT`）首包 p50 345 ms / p90 913 ms / max 1880 ms —
与上表口径不同，需统一后复核。

### 4.6 压测内存实测样例

`DEVICE_STRESS.md`：200 轮、48 条分位语料 burst → 200/200 PASS，空 final 2%，
流存活 0，**RSS +11.09 MiB**，线程变化 0。

### 4.7 分级加载内存（鸿蒙真机，2026-10-25 本次补测）

设备 VYG-AL30，毫秒级采样进程 VmRSS：

| 阶段 | VmRSS |
| --- | ---: |
| app 外壳（ArkTS 运行时 + UI，SDK 未动） | 35.6 MB |
| t=0.25 s | 172.8 MB |
| t=0.77 s 转写就绪 | 181.0 MB（稳定 181.6，峰值 183.4） |
| 切会议纪要 + 开始识别（启用角色分离） | 峰值 **611.8 MB**，末值 599.6 MB |

SDK 可归因增量（转写）≈ **146 MB**。

对照客户要求（框架 ≤20 M / 转写模型 ≤350 M / 加角色分离 ≤400 M）：

- 转写 146 MB → **达标**
- 加角色分离 611.8 MB → **超标约 212 MB（1.53 倍）**
- 框架 ≤20 M → **无法判定**：框架与模型在 0.8 秒内背靠背加载，阶梯上无平台期，
  外部测量切不开。需在 SDK 内部补分段埋点，或提供「只加载框架」的入口

> 存疑待查：分离相关模型文件合计仅约 55 MB
> （eres2net 39.6 + pyannote 6.0 + wespeaker encoder 5.5 + pool 5.3），
> 与实测 +428 MB 增量差距很大，疑有重复加载或缓存未释放。

---

## 5. 没有测过 / 口径缺失

| 项 | 状态 |
| --- | --- |
| 整机功耗（mW / mAh per hour） | `PowerSampler` 有采样能力，但**没有任何已归档的功耗结论**；且定位为 diagnostics-only，无门禁 |
| 推理框架单独的内存占用 | 无分段埋点，外部不可测（见 4.7） |
| TTS 尾包时延 | 无埋点、无数据 |
| TTS MOS | 需人工听审；仓库无历史 MOS 数据；端侧 TTS 也无宿主可运行的导出模型 |
| 机身温升的机型/系统/环境温度 | 10-07 那轮只记了起始机身温度 26.47 / 27.07 °C，机型、系统版本、环境温度均未入库 |
| 停止后收尾时间 | 15 秒收尾门禁从「30 秒内未完成」做到 3.8 秒 PASS；RTF 减半后是否更宽裕是**推论不是测量** |
| INT8 vs FP32 的精度/速度权衡对照 | 无同条件 A/B（没有 FP32 encoder 的端侧实测可对比） |

---

## 6. 复跑方式

```bash
# 1) native 产物
asr/tools/04_build_android_so.sh arm64-v8a

# 2) 鸿蒙：构建 + 签名 + 安装 + 冒烟（含 build-identity）
HARMONY_SIGNING_CONFIG=.secure/harmony-signing-signing-project.json \
NODE_ADDON_API_PREPATCHED="$PWD/.cache/node-addon-api-c679f6f4-patched" \
  ./delivery/harmony-dingqiao/delivery/build_install_smoke.sh \
  --device <serial> --build-mode debug

# 3) 真机压测（含功耗采样、诊断抓取）
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --installed-package --sample-power --capture-diagnostics \
  --diarization-encoder cpu          # 注意：默认是 auto，与 SDK 默认 cpu 不一致

# 4) 模型加载基准
python3 delivery/harmony-dingqiao/delivery/run_model_load_bench.py
```

**已知工具缺陷**（已记录于 PR #275，尚未修复）：

1. `run_device_stress.py:1148` 的 `build_install()` 漏传 `--build-mode diagnostics`，
   导致安装包不写 `events.full.ndjson`，`--capture-diagnostics` 必然 FAIL；
   需先单独跑 `build_install_smoke.sh --build-mode diagnostics` 再用 `--installed-package`
2. `pack_diagnostics_sdk.sh` 在 `INCLUDE_SIGNED_DEMO=true` 时会用自己的未签名
   `assembleHap` 覆盖已签名 HAP，然后又要求签名 HAP；需 `SKIP_BUILD=true`
3. `issue_dingqiao_demo.sh` 硬编码 `-storepass dingqiao2026`
4. `--zh-en-only` 过滤只在 `SDK_ONLY == true` 时生效，导致「zh-en only」与「内包含 demo」互斥
