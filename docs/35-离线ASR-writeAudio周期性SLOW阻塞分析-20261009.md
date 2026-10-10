# 离线 ASR writeAudio 周期性 SLOW 阻塞分析

- **分析日期**：2026-10-09
- **数据来源**：
  - `D:\临时文件\1008\slow？.txt`（10-09，App 进程 35549，会议纪要离线 ASR 长会话，SDK 0.2.x）
  - `D:\临时文件\1008\离线分离超时.txt`（10-08，App 进程 40716，会议纪要离线 ASR 长会话，SDK 0.2.x）
  - `D:\临时文件\1008\13版本离线.txt`（10-08 16:58:40–16:59:34，App 进程 37945，会议纪要离线 ASR，SDK 0.3.13）
- **关联报告**：[双机功耗对比测试报告-离线ASR-20261009](./双机功耗对比测试报告-离线ASR-20261009.md)（A 机离线 ASR 会议进程平均占用 1.6 核；被测版本 SDK 0.2.x，仍存在本文周期性阻塞）

## 1. 问题背景

排查离线 ASR 会议场景日志时发现大量 `[WriteAudioPerf] writeAudio SLOW` 告警（单文件 1200+ 条），需要确认其含义、占比与影响，并判断是否为新引入问题。

## 2. 打点机制说明

打点为本项目自埋的性能探针（非系统日志），位于 `common/commoncore/src/main/ets/voice/engine/OfflineAmphionEngine.ets`，开关为 `VoiceDebugConfig.LOG_WRITE_AUDIO_PERF`（debug 包开启，[VoiceDebugConfig.ets:25](../../common/commoncore/src/main/ets/voice/VoiceDebugConfig.ets)），设计目的是定位喂音路径主线程阻塞、确认 OnReadData 超时是否由同步 writeAudio 引起。

### 2.1 三类打点的关系

| 打点 | 测量对象 | 阈值 | 代码位置 |
|---|---|---|---|
| `writeAudio SLOW` | 单帧（640B/20ms）调一次 SDK `writeAudio` 的耗时 | ≥20ms（`WRITE_AUDIO_SLOW_MS`） | `writeAudioTimed()`，L312-340 |
| `writeCallback SLOW` | 整块采集回调总耗时（1280B/40ms，含拆帧、2 次 writeAudio、旁路拷贝） | ≥40ms（`WRITE_CALLBACK_SLOW_MS`） | `noteWriteCallbackCost()`，L342-352 |
| `[ReadDataPerf] handleAudioData SLOW` | 采音读数据回调处理耗时 | — | `AudioRecorder.ets` |

三者同在主线程数据通路执行，同源阻塞会在三个打点同步出现。`writeCallback 耗时 ⊇ Σ writeAudio 耗时`，writeCallback SLOW 基本由其中一次 writeAudio SLOW 传导产生。

### 2.2 日志字段含义

```
[WriteAudioPerf] writeAudio SLOW 58ms, source=live, call#=2300, sinceActive=44514ms, modelReuse=false
```

- `58ms`：该次 writeAudio 调用耗时
- `source`：`live`=实时采音喂入；`flush`=onStart 后 RingBuffer 回灌
- `call#`：本会话第 N 次调用
- `sinceActive`：距会话进入 ACTIVE（实时喂 SDK）的毫秒数
- `modelReuse`：是否命中模型复用

```
[WriteAudioPerf] writeCallback SLOW 96ms, chunk=1280B, state=2, cb#=1150
```

- `chunk`：本块字节数（40ms 音频）；`state=2` 即 ACTIVE（0=STOPPED，1=BUFFERING，2=ACTIVE）；`cb#`：第 N 次回调

## 3. 统计结果

### 3.1 今日日志（slow？.txt）

单会话中段（无会话重置、无 final summary），覆盖 19:35:43 – 20:00:04 约 24.3 分钟，writeAudio 调用 2275 → 75300 累计递增。

| 指标 | 值 |
|---|---|
| 文件内增量 | 73025 帧（50 帧/s，≈1460.5s 音频） |
| SLOW 次数 | 1242（与 summary 慢计数增量完全吻合） |
| **帧数占比** | **1.70%**（1242/73025） |
| 慢调用总耗时 | 86.9s，平均 70ms |
| **阻塞时间占比** | **5.95%**（86.9s/1460.5s） |
| 出现频率 | 每 ~59 帧（约 1.2s）一次 ≈ **0.85 次/秒**，节奏稳定 |
| 耗时分布 | 20–49ms：380 条；50–99ms：701 条；100–119ms：161 条 |
| 伴随 | writeCallback SLOW 981 条；ReadDataPerf SLOW 1248 条 |
| summary 全程 | avg=1ms，max=119ms，modelReuse=false |
| 丢音 / onError | **无 overflow 丢音日志、无 SDK onError** |

### 3.2 昨日日志（离线分离超时.txt）

同为会议纪要长会话中段（进入文件时会话已连续 ACTIVE 约 23 分钟），覆盖 15:10:22 – 15:10:59 约 36.5s。

| 指标 | 值 |
|---|---|
| 文件内增量 | 1825 帧 |
| SLOW 次数 | 33 |
| **帧数占比** | **1.81%**（33/1825） |
| 会话累计占比（summary） | 1.78%（1232/69200 → 1265/71025） |
| 平均单次耗时 | 44.2ms；文件内 max=82ms，会话累计 max=110ms |
| **阻塞时间占比** | **4.0%**（1458ms/36.5s） |
| 出现频率 | 每 ~55 帧 ≈ **0.9 次/秒** |
| 伴随 | writeCallback SLOW 16 条（会话累计 cbSlow 665→681，cbMax=113ms） |
| 丢音 / onError | 无 |

### 3.3 SDK 0.3.13 版本日志（13版本离线.txt）

会议纪要离线 ASR 会话起步段（calls 25 → 1725，约 34.5s 实时喂音，App 进程 37945）。

| 指标 | 值 |
|---|---|
| writeAudio SLOW 明细 | **0 条** |
| writeCallback SLOW 明细 | **0 条** |
| summary slow 累计 | **全程 0**（69 条 periodic 全部为 0） |
| writeAudio 单次 max | **4ms**（avg=0ms） |
| writeCb 单次 max | **4ms** |
| onError / 丢音 | 无 |

约 1700+ 次喂音调用中任何一次都不超过 4ms——若 0.3.13 仍存在 ~1Hz 周期阻塞，该窗口应出现约 30 次 SLOW，实际为 0。

**注意**：该日志窗口较短（会话刚起步 35s），「长会话全程无此问题」的严格结论需 20+ 分钟长测确认；但全程 max=4ms 已可初步判断 0.3.13 未复现该现象。

### 3.4 三日志对比

| 指标 | SDK 0.2.x（10-08 离线分离超时） | SDK 0.2.x（10-09 slow？） | SDK 0.3.13（10-08 13版本离线） |
|---|---|---|---|
| 场景 | 会议纪要离线 ASR 长会话中段 | 同 | 会议纪要离线 ASR 会话起步段 |
| 覆盖喂音 | 1825 帧（~36.5s） | 73025 帧（~1460s） | 1700 帧（~34.5s） |
| writeAudio SLOW | 33 条 | 1242 条 | **0 条** |
| SLOW 帧占比 | 1.81%（会话累计 1.78%） | 1.70% | **0%** |
| writeAudio 单次 max | 110ms | 119ms | **4ms** |
| writeCallback SLOW | 16 条 | 981 条 | **0 条** |
| 阻塞时间占比 | 4.0% | 5.95% | **≈0%** |
| 频率 | ~0.9 次/秒 | ~0.85 次/秒 | **无** |
| 丢音 / onError | 无 | 无 | 无 |

## 4. 定性结论

1. **非偶发，是稳定的周期性阻塞**：约 1Hz 的固定节奏、单次 20~120ms、随会话时长全程稳定存在且无恶化趋势（平均与 max 不随时间递增）。
2. **SDK 0.2.x 系既有问题，0.3.13 已消除**：10-08 与 10-09 两份 0.2.x 日志定量特征高度一致（帧占比 1.7%~1.8%、约每秒 1 次、无丢音）；0.3.13 同场景下喂音耗时全程 ≤4ms，无一次超阈值，疑似 SDK 侧已将每秒批量处理移出 writeAudio 同步路径。
3. **疑似根因**：规律性指向 SDK 0.2.x 内部约每秒一次的批量处理/统计同步执行在 writeAudio 调用路径上；喂音、拆帧、读数三类打点同步出现，佐证为同源的主线程阻塞。

## 5. 影响评估

- **对识别功能：无影响**。慢帧时段消费速度短时落后于生产，由 RingBuffer/SDK 内部缓冲兜底，全程无 overflow 丢音、无识别错误。
- **对性能：主线程约 4%~6% 时间消耗在这些慢调用上**，且每秒一次的忙段（50~120ms）是持续存在的负载模式。
- **对功耗：构成持续负载的一部分**。每秒约 0.85 次、每次 50~120ms 的忙段与功耗报告中「小乔进程平均占用 1.6 核、SoC 稳态 ~60°C」的持续重负载特征相符。**注意**：10-09 功耗测试的被测版本（SDK 0.2.x）仍存在该阻塞；0.3.13 消除该忙段后，离线 ASR 会议的 CPU 占用与功耗结论可能变化。

## 6. 后续建议

1. **升级 0.3.13 后复测功耗对比**：以 SDK 0.3.13 重跑双机功耗测试（同参数），对比小乔进程 CPU 占用（原平均 1.6 核）与 SoC 温度，验证消除周期性忙段后的负载变化；长会话跑 20+ 分钟同时抓 hilog，确认 `writeAudio SLOW` 全程为 0。
2. **双机对比该指标**：复测时同时抓取两台设备 hilog，对比 `summary(periodic)` 的 `slow(>=20ms)=N, max=Nms`，确认忙段是否为两机功耗差异的变量。
3. **向 SDK 供应商反馈/确认**：提供该报告与 0.2.x 原始日志，确认内部 ~1Hz 周期任务在 0.3.13 中的处理方式（异步化/移除），锁定修复依据，防止后续版本回退。
4. **时间对齐分析**（可选）：将 SLOW 时刻与功耗采集的 CPU 频率/占用采样做对齐，验证忙段与频率抬升的相关性（仅对 0.2.x 数据有意义）。
5. **保持现状监控**：当前不构成功能缺陷，无需改动应用侧代码；若后续出现 overflow 丢音或 onError，再重新评估缓冲与喂音策略。

## 7. 附录：分析命令参考

```powershell
# SLOW 明细与耗时分布
Select-String -Path <日志> -Pattern 'writeAudio SLOW (\d+)ms' | ForEach-Object { [int]$_.Matches[0].Groups[1].Value }

# summary 序列（重建会话结构：calls 持续递增=单会话，重置=新会话）
Select-String -Path <日志> -Pattern 'summary\(periodic\): writeAudio calls=(\d+), slow\(>=20ms\)=(\d+)'

# 占比计算（文件内增量法，避免会话累计值受截断影响）
帧占比   = SLOW明细数 / (calls 末值 - calls 首值)
时间占比 = ΣSLOW耗时 / (calls 增量 × 20ms)
```
