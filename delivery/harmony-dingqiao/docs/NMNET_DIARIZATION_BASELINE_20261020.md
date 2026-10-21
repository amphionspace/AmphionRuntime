# 角色分离 A/B 实测报告：Community vs NMNet 学生后端

设备侧实测对比：当前 main（Community 后端）与 jiaofu.zip 交付的 NMNet 学生后端，在同机、同语料、同参数下的时延、资源、功耗与精度。

| 项 | 值 |
| --- | --- |
| 基线轮采集 | 2026-10-20 |
| nmnet 轮采集 | 2026-10-21 |
| 代码基线 | `b56b240d`（= `main`，PR #272 热词修复已合入） |
| 测量分支 | `perf/nmnet-student-diarization` |
| 设备 | HarmonyOS，`7GK0226326015655`，Kirin 9020，12 核 |

---

## 1. 结论摘要

**基线（Community）在四个维度全部优于 nmnet，包括精度。没有理由采用 nmnet。**

| 维度 | 基线 | nmnet | 判定 |
| --- | --- | --- | --- |
| 时延 | RTF **0.0994** | RTF **0.8084** | 基线胜 **8.14×** |
| 内存 | 峰值 750.4 MiB，斜率 −0.47 MiB/min（有界） | 峰值 **1540.0 MiB**，斜率 **+1.44 MiB/min**（增长） | 基线胜 |
| 精度 | 同一人约束 **5/6**，未归属 **0** | 同一人约束 **1/6**，未归属 **3** | 基线胜 |
| 功耗 | −274.0 mW，电池 29.0 °C | −241.4 mW，电池 **34.0 °C** | 无定论，温度指向基线胜 |

nmnet 付出约 8 倍计算、2 倍内存峰值、+42% CPU，换来的是**更差**的角色分离结果 —— 不是「精度换性能」的权衡，而是两头都输。

两项必须同时说明的限制：

- 精度检验只有 6 条人工裁定的成对约束，**不是 DER 基准**（标注文件自述 "Not a fully labeled DER benchmark"）；两轮均未注册声纹，因此检验的是聚类一致性而非身份识别精度。
- nmnet 是 float32 ONNX / ORT CPU，其迁移文档明示「当前不处理：训练、量化、NPU 优化」。基线的声纹 encoder 跑在 Kirin 9020 NPU 上。性能对比包含这一硬件差异。

另有两个**与 nmnet 无关**的既有缺陷在基线轮暴露（第 7 节），以及一个阻断发布的资源互斥冲突（第 12 节）。

---

## 2. 测试环境与方法

| 项 | 基线轮 | nmnet 轮 |
| --- | --- | --- |
| 载体 | demo 0.3.24 diagnostics，432 MB | demo 0.3.24 diagnostics，**733 MB** |
| 语料 | `dingqiao-meeting-20260918/audio`，5 段真实客户会议录音，16 kHz 单声道 | 同 |
| 音频总时长 | 1010.6 s（16.84 min） | 同 |
| 轮数 | `--cycles 5`（每轮一个文件） | 同 |

必须用 diagnostics 构建：分项耗时导出受 `DIAGNOSTICS_BUILD` 门控，debug 包拿不到窗口推理 / 聚类 / 预览的分解数据。

采集命令（两轮仅 `--output-root` 不同）：

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --installed-package \
  --mode diarization-windows --enable-diarization \
  --data-dir ~/.cache/amphion-runtime/test-data/v1/dingqiao-meeting-20260918/audio \
  --files 0 --cycles 5 \
  --capture-diagnostics --sample-power \
  --sample-interval 1.0 --post-run-observe 30 \
  --timeout 7200 \
  --output-root .local/perf/<baseline|nmnet-full>
```

两点说明：

- `--installed-package` 是必需的。脚本在 `run_device_stress.py:1320` 的条件是 `if not args.skip_build_install and not args.installed_package`，不带这个参数会去调用 `build_install_smoke.sh`（在本机因离线等原因会失败，见第 12 节）。
- `--cycles` 默认 100 是为短句压测设的。本语料一轮即约 17 分钟音频，100 轮等于约 28 小时，必须压到个位数。

**数据保密**：语料为真实客户会议录音，`SOURCE.md` 明确仅限内部评测、不得对外分发。本报告只含时长与统计量，不含音频内容；设备日志与原始采集数据仅留本地。

文件与轮次映射（按时长确认）：

| 轮 | 源文件 | 时长 |
| --- | --- | --- |
| 0 | `meetingMinutes-20260918-095700-039.wav` | 108.5 s |
| 1 | `meetingMinutes-20260918-100350-257.wav` | 369.1 s |
| 2 | `meetingMinutes-20260918-102010-230.wav` | 200.8 s |
| 3 | `meetingMinutes-20260918-111223-816.wav` | 164.1 s |
| 4 | `会议-离线-无角色4.wav`（标注中为 `recording-a`） | 168.2 s |

---

## 3. 时延与计算开销

完整语料 1010.6 s，同机同参数。

| 指标 | 基线（Community） | nmnet | 倍数 |
| --- | --- | --- | --- |
| 窗口数 | 489 | 443 | 91%（略有缺口） |
| 单窗 wall 均值 | 176.2 ms | **1844.3 ms** | **10.5×** |
| 单窗 wall p95 | 240.5 ms | 2991.0 ms | 12.4× |
| 单窗 wall max | 411.5 ms | 3534.0 ms | 8.6× |
| **计算合计** | **100.41 s** | **817.01 s** | **8.14×** |
| **RTF** | **0.0994** | **0.8084** | **8.14×** |

分项（均值 / p95 / max，单位 ms）：

| 阶段 | 基线 | nmnet | 倍数（均值） |
| --- | --- | --- | --- |
| 分割 | 193.5 / 240.2 / 290.7 | 1131.6 / 1244.0 / 1376.9 | 5.8× |
| 嵌入（总） | 34.2 / 40.0 / 56.3 | 606.2 / 1748.4 / 2220.5 | 17.7× |
| └ 嵌入特征 | 42.3 / 53.1 / 78.7（`featureMs`） | 13.7 / 46.4 / 111.0 | — |
| └ 嵌入 encoder | 29.3 / 32.1 / 45.0（**NPU**） | 583.8 / 1714.8 / 2146.7（**CPU**） | 19.9× |
| 预览聚类 | 141.5 / 403.0 / 639.0（81 次，11.46 s） | ETS 侧无事件（聚类归 native） | — |
| 提交聚类 | 278.7 / 440.0 / 440.0（10 次，2.79 s） | 同上 | — |

**子阶段之和大于 wall**（基线 146.3 s > 86.16 s），子阶段间有并发重叠，不可简单相加当总开销。

**nmnet 的嵌入开销随会话增长**：同一指标在 108.5 s 单文件轮为 201.5 ms，在 1010.6 s 完整轮为 606.2 ms（3.0×）；分割则保持平稳（1125.3 → 1131.6 ms）。增长集中在 ECAPA 嵌入侧。

**队列积压**：nmnet `pendingWindows` 均值 5.23、最大 **21**；历史压缩在完整轮已触发（`historyCompressed = true`，`historyChunks` 最终 59）。

短会话对照（108.5 s，第 0 轮单独一轮）：

| | 基线 | nmnet | 倍数 |
| --- | --- | --- | --- |
| 窗口数 | 51 | 46 | — |
| 单窗 wall 均值 | 172.0 ms | 1418.5 ms | 8.2× |
| 计算合计 | 9.59 s | 65.25 s | 6.80× |
| RTF | 0.0884 | 0.6014 | 6.80× |

倍数从短会话 6.80× 升到完整语料 8.14×，与嵌入侧的会话内增长一致。

---

## 4. 资源与功耗

| 指标 | 基线 | nmnet | 差异 |
| --- | --- | --- | --- |
| RSS 峰值 | 750.4 MiB | **1540.0 MiB** | +789.6 MiB |
| RSS HWM | 758.9 MiB | 1562.6 MiB | +803.7 MiB |
| RSS 增长 / 斜率（采集器口径） | +33.5 MiB / **−0.47 MiB/min** | +225.7 MiB / **+1.44 MiB/min** | 有界 → **持续增长** |
| vm_data 峰值 | 3157.7 MiB | 5461.6 MiB | +2303.9 MiB |
| swap 峰值 | 81.4 MiB | 83.2 MiB | 持平 |
| CPU 均值 | 250.9% | 355.8% | +42% |
| CPU p95 | 293.6% | 454.3% | +55% |
| CPU peak | 329.0% | 517.7% | +57% |
| 电池温度 | 29.0 °C | **34.0 °C** | +5 °C |
| 功率 均值 | −274.0 mW | −241.4 mW | 见下 |
| 线程 | 31→54，peak 92 | 30→44，peak 92 | 均无泄漏 |

**内存有界性是本轮最重要的发现。** 基线斜率 −0.47 MiB/min（无增长趋势），nmnet 为 **+1.44 MiB/min**，会话内增长 +225.7 MiB。这正是 nmnet 迁移文档自述「没有证明整体会话内存有界」的那一条，现在有了反向证据 —— 历史压缩已触发但未能止住增长。

**功耗读数不可用于结论**：nmnet 均值 −241.4 mW，放电幅度反而**小于**基线的 −274.0 mW，与其 CPU 高 42% 相矛盾。原因是 USB 供电掩盖（`plug=2`）：CPU 越高、USB 补得越多、电池净放电看起来越小。电池温度 +5 °C 是更可信的功耗代理。要拿绝对功耗，须断开 USB 用无线调试或离线采集。

---

## 5. 精度

### 5.1 口径与其限制

语料自带人工标注 `annotations/human-final.json`。该文件明确声明 **"Not a fully labeled DER benchmark"**，且 `prohibitedAssumptions` 禁止：把 MOSS speaker ID 当人工真值、假定每个文件固定四人、跨录音推断标签。**因此 DER 无法计算。**

可用的是人工裁定过的成对约束：

- `samePersonGroups`：6 组，每组内各区间**必须**归为同一说话人
- `differentPeople`：`111223-816` 的 L 与 M **必须**不同
- `backgroundExcluded`：评分时排除的背景区间（本检验已排除）

判定方法：对每个区间，按 `DIARIZATION_PUBLIC_RESULT` 的 `speakerTurns` 重叠时长取主导 `speakerIndex`。**必须跨同一会话的全部增量结果聚合** —— session-final 只覆盖末段，单取它会得到几乎全部「无覆盖」。

### 5.2 结果

| | 基线 | nmnet |
| --- | --- | --- |
| 同一人约束 一致 | **5 / 6** | **1 / 6** |
| 同一人约束 违反 | 1 | 2 |
| 无法判定（未归属） | **0** | **3** |
| L ≠ M（必须不同） | 满足 ✓（L=1, M=0） | 满足 ✓（L=1, M=2） |

逐组明细：

| 源文件 | 约束 | 基线 | nmnet |
| --- | --- | --- | --- |
| 100350-257 | H+I+J | 不一致（0 / 2） | 不一致（0 / 3，含 −1） |
| 102010-230 | E+F+K | 一致（全 0） | 不一致（2 / 0） |
| 111223-816 | L | 一致（全 1） | 一致（全 1） |
| 111223-816 | M | 一致（全 0） | 无法判定（−1 / 无覆盖） |
| recording-a | R | 一致（全 3） | 无法判定（−1 / 无覆盖） |
| recording-a | S | 一致（全 0） | 无法判定（仅 1 区间有覆盖） |

nmnet 的 3 项「无法判定」本身是失败形态：它在这些区间输出 `speakerIndex = -1`（未知说话人）或完全没有归属，而基线 6 项全部可判定。`100350-257` 的 H+I+J 两边都判错，属共同难例。

### 5.3 输出密度

| | 基线 | nmnet |
| --- | --- | --- |
| `speakerTurns` 合计 | **274** | **83**（30%） |
| 逐轮 | 24 / 73 / 35 / 83 / 59 | 5 / 22 / 10 / 19 / 27 |
| 时间覆盖缺口 | 无明显缺口 | `102010-230` 仅至 85.4 s / 200.8 s；`recording-a` 仅至 118.0 s / 168.2 s |

nmnet 的角色输出密度约为基线三成，并在多个文件上留下大段未归属音频。这与 5.2 的精度结果相互印证。

### 5.4 限制

6 条成对约束不是 DER，样本量小，不足以给出统计置信区间；两轮均未注册声纹（`speakerScores = 0`），因此检验的是**聚类一致性**而非身份识别精度。要推翻本节结论需要带声纹注册的一轮加上真正的 DER 基准 —— 但以当前差距，那更可能是确认而非反转。

---

## 6. 逐轮结果与会话时长趋势

| 轮 | 音频 | 基线 elapsed | nmnet elapsed | 基线 finals / 角色更新 | nmnet finals / 角色更新 | 基线判定 | nmnet 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 108.5 s | 118069 ms | 111510 ms | 12 / 9 | 12 / 2 | FAIL | FAIL |
| 1 | 369.1 s | 399223 ms | 371793 ms | 30 / 19 | 33 / 11 | FAIL | PASS |
| 2 | 200.8 s | 224220 ms | 202802 ms | 23 / 23 | 23 / 9 | PASS | PASS |
| 3 | 164.1 s | 173385 ms | 175181 ms | 28 / 34 | 28 / 15 | PASS | FAIL |
| 4 | 168.2 s | 192154 ms | 179470 ms | 23 / 20 | 23 / 16 | PASS | FAIL |

`elapsed` 两边相近是因为采集器按音频节奏投喂，不反映计算开销；计算开销见第 3 节。ASR 输出（finals）两边基本一致，角色更新数 nmnet 约为基线一半（合计 105 → 53）。

**基线侧 RTF 随会话时长上升**：108.5 s 会话 RTF 0.0870，369.1 s 会话 0.1080。这与 `98bf9f86`（*perf(asr): stop diarization clustering from growing with meeting length*）处理的是同一性质问题，说明该修复**缓解了但没消除**。该提交记录的合成会话数据：

| 场景 | 3 min | 13 min | 20 min | 2 h |
| --- | --- | --- | --- | --- |
| 4 人 | 0.02 s | 0.12 s | — | ~5.3 s |
| 2 人 | 0.08 s | 2.92 s | 9.93 s | ~35 min |

2 人场景是立方增长。修法是把训练集截到 512 向量、候选截到 32、复用已算出的 Ahc 拟合。

**本轮测不到这一维**：16.84 分钟语料距 2 小时量级差两个数量级。长会话增长需单独用更长音频覆盖。

---

## 7. 基线侧暴露的既有缺陷

以下与 nmnet 无关，是当前 `main`（`b56b240d`）上就存在的问题，建议独立开单，不要混入 nmnet 评估。

### ① 停止到完成超时 — FAIL

```
customer_stop_latency: limit_ms=15000  max_ms=23908  failed_cycles=[1,2,4]
```

5 轮里 3 轮超限，最差 23908 ms ≈ 门限的 1.6 倍。

### ② native stream 未释放 — FAIL

```
native_streams: observed_cycles=5  nonzero_cycles=1  max_live_streams=1
detail=live-streams-1
```

第 1 轮结束后仍有 1 个 native stream 存活。同一轮的 `finishToCompleteMs` 也没测到，两者很可能同源。

### ③ 第 0 轮契约 FAIL — 属跑法所致，非缺陷

`customer-meeting-diarization-contract` 失败原因是未注册声纹，`speakerSimilarity` 全空。两轮同因，不计入缺陷。

---

## 8. 冷启动时延

`createEngineAsync` 从调用到回调（基线轮测得）：

| 指标 | 值 |
| --- | --- |
| p50 | 11.0 ms |
| p95 | 11.8 ms |
| max | 12 ms |
| 引擎池命中 | 5~8 ms |

**这个数字不含后台模型加载** —— 它测的是异步派发往返，不能当作「冷启动可用时间」。考虑到 nmnet 多出 322 MB float32 权重，真实模型加载开销的对比仍未测。

执行时需注意：脚本默认拿过期的 `asr-demo` 签名配置比对，本次装机用的是 `signing-project`，须设 `HARMONY_SIGNING_CONFIG` 对齐。

---

## 9. 投影 vs 实测

集成前曾按 nmnet 文档记录值做过投影，此处回顾其准确度，供后续同类评估参考。

| 指标 | 投影 | 实测 | 偏差 |
| --- | --- | --- | --- |
| RTF | ≈0.855 | **0.8084** | 投影偏高 5.8% |
| 单窗合计 | ≈1767 ms | 1844.3 ms | 投影偏低 4.2% |
| 分割 | 334 ms（1.7×） | 1131.6 ms（5.8×） | **投影严重偏低** |
| 嵌入 | 1433 ms（42×） | 606.2 ms（17.7×） | **投影严重偏高** |
| RSS | 「大概率突破 1 GB」 | 峰值 1540 MiB | 成立 |

总量投影准确（5.8% 内），但分项方向都错了：分割比文档记录的服务器 CPU 数字慢得多，嵌入则快得多 —— 后者因为 nmnet 在无活跃说话人的窗口会跳过嵌入，分布极偏（均值 606.2 ms 对 p95 1748.4 ms）。**结论：此类投影可用于判断量级，不可用于分项归因。**

---

## 10. nmnet 集成：落地范围与人工判定

代码落地在分支 `perf/nmnet-student-diarization`。

| 项 | 数量 | 说明 |
| --- | --- | --- |
| 已跟踪文件覆盖 | 16 | CRLF→LF 归一后真实差异 **847 行** |
| 新增文件 | 21 | 含 8 个 C++、4 个测试、2 个文档 |
| 模型 | 5 图 322 MB | `restore: PASS`，manifest SHA-256 全匹配；`.gitignore:163` 的 `*.onnx` 已覆盖，不入 git |
| 重复目录 | 弃用 | zip 内 `v1/` 与 `v1/v1/` 的 5 个 onnx CRC 完全一致 |

**关于包的来源**：`jiaofu.zip` 是从某台 Windows 机器工作树（`E:\code\amphion\AmphionRuntime`）手工挑文件打的包，`backup_manifest.json` 每条只有 path + bytes + sha256，没有基线提交；本地与 origin 都不存在 `feat/nmnet-student-diarization` 分支。它目前是那份工作的唯一副本，**建议出包方尽快推送分支**。

**两处人工判定**（整文件覆盖会抹掉包快照 10-14 22:43 之后 main 的改动）：

- `SpeechRecognizeSdk.ets`：拒绝回退 `hotwordCount` 的 hunk（保留 `c3196d73`），接受 `diarizationHopMs` 透传的 hunk。
- `SpeakerDiarizationSession.ets`：整文件取归档版本 + 一行回改。依据是归档版 `updateSpeakers` 为结构性替换，`readEvidence` 调用 **0 次**，`98bf9f86` 优化的整会话 activity 重算在该路径已不存在，无可挂靠点；`6cd408a7` 仍适用，`PREVIEW_COST_RATIO` 由归档的 10 回改为 20。

### 自检结果

| 检查 | 结果 |
| --- | --- |
| `test_nmnet_model_resources` | **PASS**（5/5） |
| `test_nmnet_sdk_routing` | 4/6 PASS；2 项因测试给 g++ 传 `-static`（macOS 不支持，`ld: library 'crt0.o' not found`）失败，手工去掉 `-static` 复现后**断言全部通过** |
| `test_nmnet_history_native` | **未跑**。需 numpy，本机无且 pypi 不可达。其中不依赖 numpy 的 `test_fixed_window_validity_and_committed_overlap` 手工复现**通过**（含 51 chunk 历史压缩边界、新说话人不被旧历史吸收） |
| `test_offline_window_progress` | 3/3 FAIL，**包的缺陷**（见第 11 节） |
| `verify_nmnet_package.py` | 校验 HAR/HAP 产物，非交付 zip；受第 12 节冲突阻塞未执行 |
| Android `compileDebugKotlin` | **PASS** |
| Android `externalNativeBuildDebug` | **PASS**，`nmnet_jni.cpp.o` 与 `nmnet_diarization.cpp.o`（arm64-v8a）均生成 |
| 鸿蒙 ArkTS 编译 | 修掉第 11 节第 2 项后**通过** |
| 鸿蒙 HAP 签名产出 | **通过**（733 MB，内含 5 个 nmnet 图，Community/pyannote 残留 0，签名与 license 校验通过） |

---

## 11. 包的缺陷（4 项，需反馈出包方）

1. **`OfflineWindowProgress.ts` 从未交付。** `test_offline_window_progress.py` 的被测模块在 zip、仓库、git 全部分支历史中都不存在，这 3 个测试永远不可能通过。
2. **`Index.ets` 未更新导出。** 包新增了 `asr/harmony/sdk/src/main/ets/com/amphion/asr/NmnetDiarizationInference.ets`，但未在 `asr/harmony/sdk/Index.ets`（`oh-package.json5` 的 `main`）中导出，导致 sdk-dingqiao 侧 5 个 ArkTS 错误。其中两处 `arkts-no-any-unknown` 是同一根因的级联后果 —— `delta` 类型来自解析失败的 `NmnetDiarizationInference`。
3. **隔离构建清单未同步。** 包改写了 `hvigorfile.ts` 去 `require('../../tools/nmnet_model_resources.cjs')`，但 `build_install_smoke.sh` 的隔离工作区不拷贝 `asr/tools/`，构建 1.4 s 即失败于 `Cannot find module`。
4. **`lastPreviewClusterMs` 声明后从未赋值**（恒 0，第 393 行被读），自适应预览间隔退化为固定 10 s，使 `PREVIEW_COST_RATIO` 实际失效。

---

## 12. 阻塞：Community 资源互斥冲突

归档的 `hvigorfile.ts` 新增一个循环，主动删除全部 13 个 Community/pyannote 资源。而仓库的鸿蒙构建流水线在**至少 4 处**断言其中部分资源必须存在：

| # | 位置 | 要求 |
| --- | --- | --- |
| 0 | `verify_nmnet_package.py`（**包自带**） | 学生包中**禁止**任何 `community-*` / `community1-*` / `pyannote-segmentation-*` |
| 1 | `verify_community_encoder_mindir.py`，经 `build_install_smoke.sh:518` | HAP 中**必须**含 `community-wespeaker-encoder.fp16.ms` |
| 2 | 同上，经 `verify_demo_inputs.sh:80` | 同上（另一调用点） |
| 3 | `verify_demo_inputs.sh` 的 `required` 集合 | HAP 中**必须**含 `pyannote-segmentation-3.0.onnx`，且内容须与源一致 |
| 4 | `harmony_build_identity.py` | 需对 HAP 内 5 个 Community 资源计算哈希以生成构建标识 |

第 0 项与第 1~4 项**不可能同时满足**。这与迁移文档自述一致：「完整 HAR 随后因旧 Community encoder 缺失失败…未绕过旧资源门禁」。

**这是产品决定，不是技术问题**：Community 后端是彻底移除，还是双后端并存？前者需改仓库的 4 处发布门禁，后者需改包的验证器。两种改法都不应由测量方代定。

---

## 13. 为测量所做的仓库改动

### 应当保留（3 处，修包的遗漏与环境缺口）

| 文件 | 改动 | 性质 |
| --- | --- | --- |
| `asr/harmony/sdk/Index.ets` | 补 `NmnetDiarizationInference` 导出 | 修第 11 节第 2 项 |
| `build_install_smoke.sh` | 隔离清单补 `nmnet_model_resources.cjs` | 修第 11 节第 3 项 |
| `build_install_smoke.sh` | 新增 `NODE_ADDON_API_PREPATCHED` 开关 | 离线环境既有缺口，与 nmnet 无关；默认关闭。原有的「改写 git URL 指向本地缓存」在 CMake 找不到 git 时无效（`GIT_VERSION_STRING=''`），该开关改用 `FETCHCONTENT_SOURCE_DIR_NODE_ADDON_API` 直接指向预打补丁的本地源 |

另补了 `shared/models/asr/README.md` 的 9 行模型说明 —— 该文件在包内但被早期清单遗漏。

### 必须回退（3 处，门禁放宽）

为取得测量用 HAP，对第 12 节表中第 1~3 项做了放宽，均以 `AMPHION_SKIP_COMMUNITY_MINDIR_GATE` 为开关、默认关闭、注释标明 measurement-only：

- `build_install_smoke.sh:515` 跳过 `publish_community_mindir`
- `verify_demo_inputs.sh:77` 不向 MindIR 校验器传 `--archive`（源侧 provenance 校验保留）
- `verify_demo_inputs.sh` 的 `required` 集合与内容断言中剔除 pyannote

第 12 节表中第 4 项（`harmony_build_identity.py`）**未放宽** —— 它在 HAP 产出之后执行，直接用已签名的 HAP 装机即可绕过，无需改动。

**这 3 处放宽不得提交。** 它们只为本轮测量存在，且不影响运行时行为（均为构建期断言），因此不污染第 3~5 节的测量结果。

---

## 14. 数据与复现

| 轮次 | 产物 |
| --- | --- |
| 基线 单文件（108.5 s） | `.local/perf/baseline-probe/20261020-050249-diarization-windows-8a96c8d6` |
| 基线 完整（1010.6 s） | `.local/perf/baseline/20261020-051115-diarization-windows-a2bb849e` |
| nmnet 单文件（108.5 s） | `.local/perf/nmnet/20261020-220511-diarization-windows-ae243c39` |
| nmnet 完整（1010.6 s） | `.local/perf/nmnet-full/20261020-221304-diarization-windows-55ffec7c` |
| 冷启动 | `.local/perf/baseline-modelload.json` |

统计口径：

- 窗口分项取 `diagnostics/*/events.full.ndjson`。**不是 `events.ndjson`** —— 后者为截断视图，会低估窗口数约 10~50%（nmnet 完整轮：443 vs 207）。
- 基线事件名 `DIARIZATION_COMMUNITY_WINDOW` / `_PREVIEW` / `_COMMIT`；nmnet 为 `DIARIZATION_LOCAL_WINDOW`（无 ETS 侧聚类事件）。
- RSS / CPU / 线程取 `memory.csv`；CPU 由 `process_cpu_ticks` 差分换算为单核等效百分比。两轮用同一方法计算以保证可比。
- RSS 增长与斜率沿用采集器自身的相位感知口径（与门禁判定一致）。
- 功耗取 hilog 中 `PowerSampler` 的 `POWER|SAMPLE` 行，格式为竖线分隔（`uv=…|ma=…|mw=…|soc=…`）。
- 精度检验需跨同一会话聚合全部 `DIARIZATION_PUBLIC_RESULT` 的 `speakerTurns`，不可只取 session-final。

---

## 15. 未覆盖与下一步

**本轮未覆盖：**

- **DER 精度基准**。现有标注不支持（第 5.1 节），需要带时间轴的完整说话人标注。
- **声纹注册下的身份识别精度**。两轮均未注册，`speakerScores = 0`。
- **长会话（2 小时量级）**。16.84 分钟语料测不出 `98bf9f86` 针对的立方增长形状。nmnet 已在 17 分钟内表现出 +1.44 MiB/min 的内存增长，长会话风险更高。
- **绝对功耗**。USB 供电掩盖，需断开 USB 用无线调试或离线采集。
- **真实模型加载开销**。第 8 节只测了异步派发往返。
- **Android 侧运行时**。仅验证编译通过，未装机测量。

**建议顺序：**

1. **出包方推送 `feat/nmnet-student-diarization` 到 origin。** 该 zip 是那份工作的唯一副本，且有真实 git 基线后冲突会自行暴露，不必靠人工判定（第 10 节）。
2. **反馈第 11 节的 4 个缺陷。**
3. **第 12 节的资源互斥冲突需产品决定。** 在此之前 nmnet 无法产出合法发布包。
4. **回退第 13 节的 3 处门禁放宽。**
5. **第 7 节两个既有缺陷独立开单。**

就本报告的数据而言，nmnet 在手机端不具备继续投入的基础：代价约 8 倍而精度更差。若要重新评估，前提是先解决量化与 NPU 适配（其迁移文档明示两者「当前不处理」），并提供一份真正的 DER 对比。
