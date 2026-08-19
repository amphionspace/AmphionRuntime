# Harmony 离线 ASR：`d4998c2` 之后的修改汇总

## 1. 范围

- 基线提交：`d4998c2`
- 基线分支：`codex/fix-harmony-offline-long-audio`
- 当前分支：`codex/optimize-harmony-offline-stalls`
- 当前提交：`4c04844`
- 汇总日期：2026-08-19

基线之后共有三个提交：

```text
491f182 fix(harmony): bound enhancement queues and trace endpoints
5caca5a docs(harmony): record optimized long meeting retest
4c04844 docs(harmony): record optimized boundary loss retest
```

其中 `491f182` 修改程序和自动测试；`5caca5a`、`4c04844` 只增加真机复测报告。

## 2. 总体结论

`d4998c2` 之后的程序修改主要解决或改善以下问题：

1. Dispatcher 的统计值虽然有界，但底层数组仍强引用全部历史 PCM；
2. Target Speaker Enhancement 前置流水线绕过异步背压，且队列进度统计不准确；
3. 长会议出现长时间无文字时，无法判断底层识别是否真正卡死；
4. 队列水位和处理进度缺少可配置、可观测指标；
5. 压力测试的 TEXT 证据缺少 sessionId 和原始文本。

本轮修改没有更换 ASR 模型，也没有再次改变此前已有的 55 秒强制端点策略。真机复测确认 public 识别全文和 final 边界没有变化，主要收益是内存占用下降、增强链路可控和问题定位能力增强。

## 3. Dispatcher 实际 PCM 引用无界

### 3.1 原问题

`SessionAudioDispatcher` 原先只推进 `queueHead`。已处理任务在数组完全排空前仍保留对 `ArrayBuffer` 或 `Float32Array` 的强引用。

因此可能出现：

```text
queueArrayLength=10000
queueHead=9999
queuedChunks=2
queuedBytes=1280
```

队列统计只显示约 1.25 KiB，但底层数组仍引用几乎全部历史 PCM，持续 burst 输入时实际内存会随累计输入量增长。

### 3.2 修改

文件：

```text
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioDispatcher.ts
```

修改内容：

- 队列元素改为可置空类型；
- 取出任务后、等待 native 工作前立即把已消费槽位置为 `undefined`；
- cancel、异常和丢弃路径同样逐槽清理；
- 已消费前缀达到 1024 项且超过数组一半时压缩底层数组；
- 队列统计增加 `retainedSlots`；
- 默认高低水位从 2 MiB/1 MiB 降为 512 KiB/256 KiB。

### 3.3 验证

- 新增 10,000 次连续背压写入回归；
- 不仅检查 `queuedBytes`，还检查底层数组存储峰值小于 2,048 个槽位；
- 排空后底层数组和 PCM 引用归零；
- 长会议真机复测中，峰值 RSS 从 636.645 MiB 降至 555.051 MiB；
- RSS 首尾增长从 67.990 MiB 降至 12.465 MiB。

结论：该问题已经解决。

## 4. Target Speaker Enhancement 绕过背压

### 4.1 原问题

启用 Target Speaker Enhancement 时，PCM 先进入逐块 Promise 处理链。原实现没有前置队列水位限制，并且 `writeAudioAsync()` 在增强路径上直接返回成功。

影响包括：

- 快速输入可能形成大量增强任务和 PCM 积压；
- `getAudioQueueStats()` 无法反映尚未完成增强的 PCM；
- 增强输出写入下游 ASR 时也没有等待 Dispatcher 容量。

### 4.2 修改

文件：

```text
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementStream.ts
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets
```

修改内容：

- 增强流水线改为单泵 FIFO；
- 增加高低水位和容量等待器；
- 记录 submitted、processed、queued、retained 和最大排队块数；
- 消费后清除数组槽位并周期性压缩；
- `writeAudioAsync()` 在增强模式下检查前置队列容量；
- 增强输出通过异步背压写入下游 ASR Dispatcher；
- `finish()` 等待增强队列排空后通知下游结束；
- cancel 和异常释放待处理 PCM，并唤醒容量等待者；
- `getAudioQueueStats()` 在增强模式下返回前置流水线的真实进度。

完整链路为：

```text
调用方 PCM
  -> Target Speaker Enhancement FIFO
  -> ASR Dispatcher
  -> native decode
```

### 4.3 真机专项验证

诊断 HAP 临时注入开源 Conv-TasNet 模型后，在设备 `5JH9K25B14001598` 上执行：

- 输入音频：200 秒；
- PCM 帧：10,000；
- 注入节奏：每个 20 ms 帧等待 12 ms，约为 1.67 倍实时输入速度；
- 增强块：115；
- 最大排队：2 块；
- 单块最大处理耗时：908 ms；
- final/complete：1/1；
- error：0；
- 结束后 native stream：0；
- RSS 首尾变化：-24.33 MiB；
- 内存门禁：PASS。

实际耗时约 159.6 秒，200 秒音频的测试效率提高约 25%。

测试报告总体显示 FAIL，是因为临时长会议语料不满足测试载体固定的“结果必须包含上海”业务文本断言，失败详情为 `target-text-contract`。该失败与队列、生命周期和内存无关。

证据目录：

```text
C:\AHR\results\tse_controlled_acceleration_20260819\20260819-143755-target-speaker-enhancement-0896f600
```

结论：按照当前“非实时但根据设备处理能力适当限速”的测试方式，该问题已经闭环。同步 `writeAudio()` 仍用于实时兼容；离线加速测试应使用 `writeAudioAsync()` 并采用受控加速节奏。

## 5. Native endpoint 与无文字停滞定位

### 5.1 原问题

一个 public final 可能跨越多个 sherpa native segment。空或 tokenless native endpoint 会被公共层抑制并继续累计。

修改前无法区分：

1. 底层数分钟没有 endpoint，识别真正卡死；
2. 底层持续 endpoint，但每个 segment 没有可发布文字；
3. 有文字或 token，但被公共结果策略抑制。

### 5.2 修改

新增文件：

```text
asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeSegmentTracker.ts
```

关联修改：

```text
asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets
asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets
```

每个 native segment 现在独立记录：

- segment 序号；
- 接收 PCM 字节数和音频时长；
- 第一条 partial 的等待时间；
- endpoint 原因；
- native 文本长度和 token 数；
- 是否发布为 public final；
- 一个 public utterance 跨越的 native segment 数；
- 发布前累计抑制的 native endpoint 数。

`AmphionMetrics` 增加：

```text
nativeSegmentCount
suppressedEndpointCount
lastEndpointReason
```

### 5.3 定位结果

长会议最严重的 `24:59.540–35:23.060` 片段并非底层 623.52 秒没有 endpoint。该 public utterance 内部实际出现 244 个 native segment，其中 243 个没有形成可发布文字而被抑制。

因此问题被收敛为：

```text
底层持续 endpoint
  -> 多个 segment 没有 text/token
  -> 公共层抑制空结果
  -> 用户长时间看不到文字
```

这项修改主要用于定位和观测，没有直接提高 ASR 模型的文字输出能力。

## 6. 队列配置和进度指标

新增 session 参数：

```text
extraParams.audioQueueHighWaterBytes
extraParams.audioQueueLowWaterBytes
```

默认值：

```text
highWater = 512 KiB
lowWater  = 256 KiB
```

水位允许配置，但高水位最多为 8 MiB。

`AudioQueueStats` 增加：

```text
processedAudioMs
queuedAudioMs
```

压力测试的 `AUDIO_QUEUE` 日志同时保存：

- submitted/processed/queued bytes；
- queued chunks；
- processed/queued audio milliseconds；
- high/low water bytes。

这些指标用于区分队列仍在推进、输入暂时超过处理速度以及队列真正停止消费。

## 7. TEXT 回调证据

### 7.1 修改

文件：

```text
delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets
```

每条 TEXT 证据现在保存：

```text
sessionId
kind
elapsedMs
isLast
text
textHex
```

同时对反斜线、竖线、回车和换行进行转义。多 session 合并时，sessionId 与文字事件保持同索引传递，以便识别迟到回调归属。

### 7.2 当前遗留问题

真机检查发现 `text=` 落盘时仍存在中文编码截断问题。当前可靠性为：

- `sessionId`：可靠；
- `textHex`：可靠，可以无歧义还原 UTF-16 文本；
- `text=`：字段已经存在，但尚不能保证中文原文可直接读取。

因此这一项只完成了字段和归属信息补齐，UTF-8 原文写入仍需继续修复。

## 8. 自动测试

新增或增强的测试包括：

- Dispatcher 10,000 次写入和实际槽位释放；
- Target Speaker Enhancement 队列水位、槽位压缩、finish 和 cancel；
- Native segment 聚合与 endpoint 抑制计数；
- 队列配置和音频进度指标；
- TEXT sessionId、原文和 UTF-16 hex 字段。

Dispatcher、native segment、有效语音、enhancement、contract/native 边界和设备驱动相关测试合计 83 项通过，`git diff --check`、ArkTS、native 编译和 HAP 打包均通过。

## 9. 长会议复测

报告：

```text
docs/LONG_MEETING_NO_TEXT_SEGMENTS_OPTIMIZED_RETEST_20260819.md
```

主要结果：

| 指标 | 结果 |
| --- | ---: |
| 测试状态 | PASS |
| PCM 帧 | 127,018 |
| partial | 541 |
| final/非空 final | 63/62 |
| complete/error | 1/0 |
| 严格无文字 utterance | 0 |
| 首条文字等待不少于 5 秒 | 13 |
| native segment | 857 |
| 被抑制 native endpoint | 794 |
| 队列峰值 | 503,040 bytes |
| 峰值 RSS | 555.051 MiB |
| RSS 首尾增长 | 12.465 MiB |

与修改前的 55 秒版本相比：

- public 识别全文逐字节相同；
- partial/final 数量相同；
- 13 个长等待片段数量没有减少；
- SDK 单轮耗时下降约 1.93%；
- 峰值 RSS 下降 81.594 MiB；
- RSS 首尾增长下降 55.525 MiB。

结论：本轮显著改善了内存和可观测性，但没有解决弱语音或低语音占比片段长时间无文字的问题。

## 10. 《阿长与〈山海经〉》边界文字复测

报告：

```text
docs/BOUNDARY_TEXT_LOSS_OPTIMIZED_RETEST_20260819.md
```

当前结果：

| 指标 | 20 秒端点基线 | 当前优化版 |
| --- | ---: | ---: |
| 非空 final | 46 | 28 |
| 标准化预测字符 | 2,658 | 2,727 |
| 原文遗漏字符 | 105 | 37 |
| 遗漏连续片段 | 35 | 14 |
| 边界前后 5 字内遗漏 | 82 | 29 |
| CER | 13.3137% | 11.0702% |

相比最初 20 秒强制端点，55 秒端点带来的改善继续稳定存在：

- 遗漏字符减少 68 个，下降 64.76%；
- 遗漏连续片段减少 21 个，下降 60%；
- 边界附近遗漏减少 53 个，下降 64.63%。

但当前优化版与 `d4998c2` 时已经存在的 55 秒端点版本逐字节相同。本轮队列、内存和诊断修改没有进一步改变 ASR 文本或 public final 边界，也没有造成退化。

## 11. 当前状态

| 项目 | 状态 |
| --- | --- |
| Dispatcher 实际 PCM 引用无界 | 已解决 |
| Target Speaker Enhancement 受控加速输入 | 已完成真机验证 |
| 增强队列真实进度统计 | 已完成 |
| Native endpoint/抑制原因可观测 | 已完成 |
| TEXT sessionId 和 textHex | 已完成 |
| TEXT 原始中文 UTF-8 落盘 | 未完成 |
| 长会议弱语音长时间无文字 | 尚未解决，已定位为连续空/tokenless native segment |
| 55 秒端点边界漏字改善 | 保持稳定，本轮无进一步变化 |

## 12. 相关文件

```text
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioDispatcher.ts
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementStream.ts
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets
asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeSegmentTracker.ts
asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets
asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets
delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets
docs/HARMONY_OFFLINE_ASR_FIX_TECHNICAL_SUMMARY_20260819.md
docs/LONG_MEETING_NO_TEXT_SEGMENTS_OPTIMIZED_RETEST_20260819.md
docs/BOUNDARY_TEXT_LOSS_OPTIMIZED_RETEST_20260819.md
```
