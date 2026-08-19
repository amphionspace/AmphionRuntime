# HarmonyOS 离线 ASR 修改、问题定位与解决方案汇总

日期：2026-08-19  
分支：`codex/fix-harmony-offline-long-audio`  
核心修复提交：`0acd153 fix(harmony): bound offline audio queue and preserve ASR boundaries`

## 1. 背景与目标

本次修改针对 Amphion HarmonyOS 离线语音识别的三个主要问题：

1. 长音频不按实时速度、快速批量送入 PCM 后，App 长时间没有结果，看起来像 ASR 卡死。
2. 长语音在约 20 秒处自动生成 final，partial 转 final 的边界附近出现文字遗漏。
3. App 主动结束旧 session 并创建新 session 时，持续到达的 PCM 可能落在两个 session 之间。

目标是在保持离线推理快于实时速度的前提下限制队列规模，保持结果持续可见，并减少强制端点和 session 轮换造成的边界丢字。

## 2. 修改的程序

### 2.1 SDK 音频调度器

文件：

```text
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioDispatcher.ts
```

主要修改：

- 将“每一帧 PCM 创建一条独立 Promise 链”改为单一 FIFO 队列和统一排空循环。
- 默认队列高水位为 2 MiB，低水位为 1 MiB。
- 队列超过高水位后暂停生产端，下降到低水位后再继续提交。
- PCM 在入队时复制，避免调用方复用采集缓冲区时覆盖尚未处理的帧。
- `finish()` 进入同一 FIFO，保证所有已接收 PCM 都处理完成后才结束。
- `cancel()` 或异常时释放未处理 PCM，并唤醒所有等待队列容量的调用方。
- 提供排队字节数、排队帧数、高低水位和可接收状态等统计。

解决的问题：长音频快速投帧时，大量 PCM 副本和 Promise 同时积压，引起高内存、长时间等待和“假卡死”。

### 2.2 SDK 公开模型和接口

文件：

```text
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DingqiaoModels.ets
```

新增接口：

```ts
writeAudioAsync(sessionId: string, audio: ArrayBuffer): Promise<boolean>;
getAudioQueueStats(): AudioQueueStats;
```

`AudioQueueStats` 提供以下信息：

- 已提交字节数；
- 已处理字节数；
- 当前排队字节数；
- 当前排队帧数；
- 队列高、低水位；
- 当前是否仍接受输入。

原有 `writeAudio()` 继续保留，以兼容实时麦克风等已有调用方；离线文件和 burst 测试改用可等待的 `writeAudioAsync()`。

### 2.3 SDK 识别引擎

文件：

```text
asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets
```

主要修改：

- 实现 `writeAudioAsync()` 并接入有界背压队列。
- 实现 `getAudioQueueStats()`。
- 新增启动参数 `extraParams.endpointMaxUtteranceMs`。
- 将该参数映射到 sherpa-onnx 的 `rule3MinUtteranceLengthSec`。
- 参数限制为 10,000～120,000 ms。
- SDK 默认仍为 20,000 ms，以兼容已有调用方。
- 长文本、PTT 和 burst 测试场景配置为 55,000 ms。

55 秒表示连续语音的强制切段上限，不表示所有语句都必须等待 55 秒。若提前出现满足端点条件的静音，仍会在 55 秒之前产生 final。

### 2.4 App 场景配置

文件：

```text
delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/CustomerScenarioProfile.ets
```

当前配置：

| 场景 | `endpointMaxUtteranceMs` |
|---|---:|
| 点击 VAD | 20,000 ms |
| PTT | 55,000 ms |
| 长文本转写 | 55,000 ms |

目的是避免所有场景统一使用 20 秒强制端点，减少连续长句在 20 秒边界处被切断的次数。

### 2.5 App 跨 session PCM 缓冲

新增文件：

```text
delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/SessionRotationBuffer.ts
```

处理以下时间窗口：

```text
旧 session finish
        ↓
等待旧 session final / complete
        ↓
启动新 session
```

修改后的行为：

- 触发 session 轮换的当前帧进入缓冲区。
- 轮换期间后续到达的 PCM 继续进入缓冲区。
- 新 session 启动后按原顺序补写缓冲 PCM。
- 用户在轮换期间停止录音时，也会先处理缓冲的尾部帧再结束。
- 记录缓冲区丢帧数量，便于诊断异常容量场景。

解决的问题：旧 session 已准备结束而新 session 尚未启动时，持续到达的音频帧可能被忽略或送入已结束的 session。

### 2.6 App 主页面

文件：

```text
delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets
```

主要修改：

- 接入 `SessionRotationBuffer`。
- 离线音频输入使用 `writeAudioAsync()`。
- session 轮换期间暂存 PCM，新 session 启动后补写。
- 根据使用场景设置 `endpointMaxUtteranceMs`。
- partial 和 final 分开保存、显示。
- 增加 session 轮换、缓冲和丢帧诊断日志。

### 2.7 手机端压力测试程序

文件：

```text
delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets
```

主要修改：

- burst 模式使用 `writeAudioAsync()`。
- 每 5,000 帧记录一次队列统计。
- burst 模式使用 55 秒强制端点。
- 启用并统计 partial。
- 保存每条 SDK 原始 TEXT 回调，包括 `sessionId`、`elapsedMs`、`isFinal`、`isLast`、原始文本和 UTF-16 十六进制文本。
- 检查最后一条 final、`isLast`、`onComplete` 和原生 stream 生命周期。

### 2.8 PC 测试驱动、自动化测试和文档

修改或新增：

```text
asr/tools/tests/test_harmony_async_audio_dispatch.py
asr/tools/tests/test_harmony_demo_session_rotation.py
delivery/harmony-dingqiao/delivery/run_device_stress.py
delivery/harmony-dingqiao/delivery/test_run_device_stress.py
delivery/harmony-dingqiao/docs/DINGQIAO_INTEGRATION.md
delivery/harmony-dingqiao/docs/语音识别SDK接口.md
docs/LONG_MEETING_OFFLINE_ASR_BURST_TEST_REPORT.md
```

回归测试覆盖：

- 10,000 帧突发提交只启动一个排空循环；
- 高、低水位背压；
- PCM 快照语义；
- `finish()`、`cancel()` 和跨 engine 执行顺序；
- session 轮换期间触发帧、后续帧及停止期间尾帧的顺序和完整性；
- `endpointMaxUtteranceMs` 参数映射；
- SDK 公开接口；
- Windows 下 `hdc.exe` 定位。

相关自动化测试共 70 项通过。

## 3. 问题定位

### 3.1 长音频快速输入后“卡死”

修复前的调用链为：

```text
127,018 个 PCM 帧快速调用 writeAudio()
        ↓
每帧复制 PCM 并创建一个 Promise 任务
        ↓
后台按顺序逐帧处理
        ↓
finish 排在全部 PCM 任务之后
```

42 分 20.36 秒的 WAV 会快速产生约 12.7 万个 PCM 副本和异步任务。调用方已经完成投帧，并不代表 SDK 已经完成推理。

由此产生的表现包括：

- 输入 API 很快返回，但 SDK 仍在后台处理数分钟；
- RSS 峰值接近 933 MiB；
- 调用 `finish()` 后较长时间没有 `onComplete`；
- 等待期间原生 stream 仍然存在；
- 固定 30 秒的测试超时将“仍在处理”误判为“已经卡死”。

延长等待后，同一音频最终能够产生 `isLast` 和唯一一次 `onComplete`，原生 stream 归零。因此定位结论是无界队列积压和测试超时误判，而不是解码线程永久死锁。

### 3.2 长时间没有用户可见文字

修复前的 burst 测试没有显示 partial，只依赖 final 更新界面。

长会议音频约 `25:07.26–35:23.04` 被 VAD 合并为一个约 615.78 秒的端点段。在该端点结束前没有新 final，手机墙钟约 161.57 秒没有新文字。

其组合原因是：

```text
后台队列仍在处理
+ VAD 形成超长端点
+ partial 没有显示
= 用户看到长时间无文字
```

该现象是结果可见性问题，不等同于 ASR 解码器停止工作。

### 3.3 为什么约 20 秒自动转 final

sherpa-onnx 端点规则中的 `rule3MinUtteranceLengthSec` 会在连续语音达到设定长度时触发强制端点。原配置对应约 20 秒，因此即使没有 1.6 秒静音，连续语音达到该上限后仍会转为 final。

静音端点和最长连续语音端点是并列条件，任一条件满足都可以生成 final。

### 3.4 Partial/final 边界文字丢失

最初观察到的表现为：

- 已经转为 final 的上一句话末尾缺少部分文字；
- 下一组 partial/final 的第一句话开头也可能缺少部分文字；
- 拼接后的全文在两个端点之间出现短语残缺或上下文断裂。

变量隔离结果：

1. 相同 20 秒端点下，paced 与 burst 两次运行的 raw final 逐字一致。
2. 说明有界队列和快速投帧节奏没有改变模型输出。
3. 分析直接读取 SDK 原始回调，未经过 App UI 的 partial/final 显示拼接。
4. 将强制端点从 20 秒提高到 55 秒后，原文遗漏字符由 105 个降至 37 个。
5. 两次独立的 55 秒运行输出逐字一致，改善可以重复。

因此当前定位是：20 秒强制端点是边界丢字的重要放大因素；本轮剩余遗漏主要发生在模型/端点输出层，而不是 App UI 文本拼接层。

此外，App 主动轮换 session 时确实存在 PCM 落在旧、新 session 之间的工程风险，因此仍增加了跨 session PCM 缓冲。这项保护解决的是潜在音频帧缺口，与已经确认的模型/端点层剩余识别误差需要区分。

## 4. 当前解决方案

修改后的数据流为：

```text
WAV / 麦克风 PCM
        ↓
writeAudioAsync()
        ↓
有界 FIFO（高水位 2 MiB，低水位 1 MiB）
        ↓
单一排空循环
        ↓
ASR 解码
        ↓
持续 partial
        ↓
静音端点或 55 秒连续语音强制端点
        ↓
final
```

当前方案包括：

1. 使用有界 FIFO 和高低水位背压，限制未处理 PCM 的内存占用。
2. 离线推理仍尽可能快地运行，不按真实播放时间每帧等待 20 ms；只有队列超过水位时才等待。
3. 长文本、PTT 和 burst 场景把连续语音强制端点提高到 55 秒，减少端点数量。
4. 开启 partial，让长端点处理期间仍然有用户可见文字。
5. session 轮换期间缓存 PCM，并在新 session 中按原顺序补写。
6. 将 SDK 原始回调与 App 显示文本分开记录，便于区分模型输出和 UI 拼接错误。
7. 记录队列深度、处理进度、最后回调时间和原生 stream 状态，避免将慢处理再次误判为死锁。

## 5. 真机验证结果

### 5.1 长会议 WAV

输入：

```text
D:\1资料\20260608实习\ASR Datasets\长会议-卡住无识别结果part1\长会议-卡住无识别结果.wav
```

| 指标 | 修复前 | 修改后 |
|---|---:|---:|
| PCM 帧 | 127,018 | 127,018 |
| partial | 0 | 541 |
| final / 非空 final | 66 / 65 | 63 / 62 |
| complete / error | 1 / 0 | 1 / 0 |
| 峰值 RSS | 933.383 MiB | 约 641 MiB |
| 结束时原生 stream | 0 | 0 |

修改后完整音频能够处理完成，SDK 没有 error，生命周期完整。62 个实际 utterance 均得到非空 final，严格口径下“整个有声 utterance 完全无文字”的数量为 0。

峰值 RSS 下降约 31%。队列日志显示待处理 PCM 维持在约 1.07～1.40 MiB，没有随整段音频无限增长。

后续专项复测仍发现 13 个有声 utterance 的首条文字等待不少于 5 秒，最长达到 150.465 秒。因此“无界积压/假卡死”已经解决，但低语音占比、超长端点和结果可见性延迟仍需继续优化。

### 5.2 《阿长与〈山海经〉》边界丢字

输入：

```text
D:\1资料\20260608实习\ASR Datasets\chaohuasishe_02_lu_64kb.mp3
```

| 指标 | 20 秒端点 | 55 秒端点 | 变化 |
|---|---:|---:|---:|
| 非空 final | 46 | 28 | -18（-39.13%） |
| 标准化预测字符 | 2,658 | 2,727 | +69 |
| 正确/等价字符 | 2,401 | 2,463 | +62 |
| 替换 | 213 | 219 | +6 |
| 原文遗漏字符 | 105 | 37 | **-68（-64.76%）** |
| 遗漏片段 | 35 | 14 | **-21（-60.00%）** |
| 最长连续遗漏 | 12 字 | 8 字 | -4 字 |
| 预测插入 | 44 | 45 | +1 |
| 边界前后 5 字内遗漏 | 82 | 29 | **-53（-64.63%）** |
| CER | 13.3137% | 11.0702% | **-2.2435 个百分点** |

边界遗漏字符减少 64.76%，CER 相对改善约 16.85%，并且两次 55 秒运行逐字一致，说明改善稳定且可重复。

问题尚未完全消除：仍有 37 个遗漏字符和 14 个遗漏片段，替换增加 6 个，插入增加 1 个。因此当前结论是“明显改善”，不是“所有识别误差已经修复”。

## 6. 当前结论

| 现象 | 定位结果 | 当前处理 |
|---|---|---|
| 快速输入后像卡死 | 无界 PCM/Promise 队列积压，不是真正死锁 | 有界 FIFO 和背压 |
| `finish()` 很久不完成 | finish 排在全部待处理 PCM 之后 | 同一 FIFO 保序，增加队列统计和合理等待 |
| 内存峰值高 | 大量 PCM 副本和异步任务同时驻留 | 高低水位限制积压规模 |
| 长时间没有文字 | 超长 VAD 端点叠加未显示 partial | 启用 partial，长文本端点参数化 |
| 约 20 秒自动 final | `rule3MinUtteranceLengthSec` 强制端点 | 长文本/PTT/burst 改为 55 秒 |
| final 边界漏字 | 20 秒强制端点显著放大模型/端点层遗漏 | 减少强制端点数量，保留跨边界 PCM |
| session 轮换可能丢音频 | 旧 session 结束到新 session 启动存在帧缺口风险 | `SessionRotationBuffer` 缓冲并补写 |
| 30 秒测试判定失败 | 测试超时把“仍在处理”误判成卡死 | 依据输入时长、队列和生命周期判断 |

## 7. 剩余问题与后续方向

1. 低语音占比或超长 utterance 的首条文字延迟仍可能达到分钟级。
2. 55 秒端点降低了边界丢字，但没有消除模型替换、插入和剩余遗漏。
3. 单次长会议测试的峰值 RSS 仍约 641 MiB，低内存设备可能需要继续优化模型和 native 工作集。
4. 当前只验证了一台 HarmonyOS 设备、一个中英模型包和指定测试音频，尚未覆盖所有设备、语言及异常中断场景。
5. 如需精确判断每一处遗漏对应的音频范围，需要人工时间戳转写或强制对齐；仅靠 final 回调无法可靠定位到 PCM 的逐样本位置。

## 8. 关联报告

- `docs/LONG_MEETING_OFFLINE_ASR_BURST_TEST_REPORT.md`
- `docs/LONG_MEETING_NO_TEXT_SEGMENTS_RETEST_20260819.md`
- `docs/BOUNDARY_TEXT_LOSS_RETEST_20260819.md`
- `docs/MODIFIED_PROGRAM_RETEST_SUMMARY_20260819.md`

真机测试证据保存在本机 `C:\AHR` 下对应的测试输出目录，其中包括 `report.json`、`result.txt`、`hilog.txt`、`memory.csv` 和输入清单。原始音频及测试证据不应直接提交到公共 Git 仓库。
