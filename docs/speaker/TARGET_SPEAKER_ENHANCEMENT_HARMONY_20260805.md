# 【实现与真机验证】端侧目标说话人增强（Harmony）

## 1. 结论

Harmony 已实现可选接口 `enableTargetSpeakerEnhancement`。它在现有 ASR 与 Speaker VAD
之前实时处理音频：每 2 秒运行一次双人语音分离，再用已注册声纹从两路结果中选择目标说话人，
相邻结果以 0.25 秒平滑拼接后送入原有 ASR。SDK 对外仍只有一个 session 和一套回调，不新增客户
可见的状态机。

Mate 80 真机上的客户 C1/C2/C3 完整音频均满足业务断言：最终文本包含“上海”，不包含“你好”；
3 个 session 均恰好一次 `isLast`、一次 `onComplete`，错误数为 0。20 ms 实时喂入时，22 个处理块
最慢 1.695 秒，低于 1.75 秒步长，最大排队数为 2。取消推理中的 session 后立即开始下一 session
也通过，旧任务没有产生迟到回调或污染新 session。

2026-08-06 更新：Conv-TasNet 已转为与设备 Runtime 匹配的 ORT 格式并进入源码和正式 HAR；
模型 Session 跨增强会话复用，并由 `unloadModel()` / `unloadRuntime()` 统一释放。第 3～6 节保留
2026-08-05 ONNX 临时包的历史实验数据，第 7 节记录当前正式资产和生命周期。

## 2. 公共接口

调用方在 `StartParams.extraParams` 中设置：

```ts
params.extraParams['enableSpeakerVad'] = true;
params.extraParams['enableTargetSpeakerEnhancement'] = true;
params.extraParams['voiceprintIds'] = ['vp-...'];
```

约束：

- 默认值为 `false`，不开启时走原有 ASR/Speaker VAD 路径。
- 只有布尔值 `true` 才启用；字符串 `"true"`、数字 `1` 不启用。
- 启用时必须同时设置 `enableSpeakerVad=true`，并提供至少一个有效 `voiceprintId`。
- 一个 session 内不能动态切换；需要改变时结束当前 session，再以新参数开始。
- `SpeechRecognitionResult.targetSpeakerEnhancementApplied=true` 表示该结果来自已启用的增强链路。
- 客户不需要配置模型名、分块长度、拼接长度、声纹阈值或线程数，这些属于 SDK 内部实现。

## 3. 实现边界

### 3.1 音频处理

- 输入：16 kHz、单声道、PCM16；调用方仍按现有 20 ms 帧写入。
- SDK 内部：2 秒块（32000 samples）、0.25 秒相邻重叠、1.75 秒步长。
- Conv-TasNet 固定输出两路 2 秒音频；每个块都重新计算两路 ERes2Net 相似度。
- 选择相似度较高且不低于 0.25 的一路；两路均未达到阈值时输出等长静音。
- 相邻块采用余弦形平滑拼接；末块可以补静音参与模型计算，但送给 ASR 的总采样数严格等于调用方
  实际写入的采样数。

### 3.2 线程和会话

- Conv-TasNet 与两路 ERes2Net 评分均在 Harmony 原生后台任务执行，不阻塞 ArkTS 主线程。
- 单个 session 严格串行处理各块，保证输出顺序并限制同时驻留的中间结果。
- `finish(sessionId)` 停止接收新音频，等待已写入音频全部处理和拼接完成，再调用原有 ASR `stop()`。
- `cancel(sessionId)` 立即关闭公开 session；已经开始的原生任务可以自行结束，但结果被丢弃，不产生
  final 或 complete，也不能写入后续 session。
- `onStart` 发出前，增强处理器、公开 session 和全部会话参数都已经发布；调用方可以在
  `onStart` 调用栈内同步 `writeAudio`、`finish` 或 `cancel`。

### 3.3 保持不变的行为

- `isFinal=true` 仍表示一句话或 endpoint 的最终结果；`isLast=true` 仍只表示整个 session 的最后一条。
- 普通识别在显式 `finish` 前不产生 `isLast=true`；正常 session 仍恰好一次 last 后一次 complete。
- `cancel` 不产生 final/complete。
- `speakerSimilarity` 名称和现有可选评分规则不变。
- `maxAudioDuration` 仍按调用方实际写入的 PCM 时长计算，不按增强后的内部块数计算。

## 4. 真机验证

### 4.1 环境和模型身份

- 设备：Huawei Mate 80 `VYG-AL30`，12 GB，12 logical CPUs，`arm64-v8a`。
- 系统：`6.1.0.135(SP8C00E120R5P7)`。
- 测试载体：只构建、安装 `ZH_EN` HAP。
- ORT：交付内置 1.16.3 CPU EP。
- 本次临时注入的 Conv-TasNet：`20,154,131 bytes`，SHA-256
  `22185d8e13bf5251c0eeab09e52099ac76c063cd9a5e5df1f5c242f535f6f151`。
- 该文件与 2026-08-04 诊断试验的 ONNX（SHA-256
  `f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab`）不是同一序列化文件，
  因此本报告单列为新的真机证据，不把结果冒充旧文件的完全复现。

### 4.2 C1/C2/C3 完整音频

最终结果：
[`realtime/report.json`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260805/realtime/report.json)

| 用例 | 最终文本 | 业务断言 | 生命周期 |
|---|---|---|---|
| C1 | 帮我查收明天的景单。然后准备明天去上海。 | 含上海、无你好 | PASS |
| C2 | 我准备明天去北京，我看明去北京的机票。你帮我定一下。坐车去上海。 | 含上海、无你好 | PASS |
| C3 | 我准备去上海，你帮我准备一下。怎么多少钱？ | 含上海、无你好 | PASS |

汇总：`starts=3`、`finals=9`、`completes=3`、`errors=0`、`emptyFinals=0`。每个 session
恰好一次 `isLast`，其后恰好一次 `onComplete`；所有公开 final 均带增强标记。C3 后半句仍有识别
错误，因此本结果证明重叠场景的重要内容被保留，不代表整句准确率已经达到产品终点。

输入按 20 ms 节奏喂入。22 个处理块的最慢耗时为 1.695 秒、95 分位为 1.664 秒，均低于
1.75 秒步长；最大排队数为 2，没有逐块累积。资源观察持续 122.19 秒：

- 峰值 RSS：839.32 MiB；峰值 HWM：857.50 MiB。
- 稳定窗口头部 RSS：722.16 MiB；尾部 RSS：460.78 MiB，增长为 -261.38 MiB。
- 线程数从稳定窗口的 49 回落到 41；未观察到持续增长。
- 当前只证明 12 GB Mate 80 可运行；8 GB 和中端设备尚未验证，不能列入支持范围。

### 4.3 `onStart` 同步调用

结果：
[`onstart/report.json`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260805/onstart/report.json)

增强开启时分别在 `onStart` 调用栈内同步写入 100 个真实 20 ms PCM 帧，然后继续识别、立即
`finish`、立即 `cancel`。三种路径全部通过：继续和结束路径各恰好一次 last/complete；取消路径没有
final/complete；均没有 `NOT_LISTENING` 或其他错误。

### 4.4 取消和立即恢复

结果：
[`cancel-recovery/report.json`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260805/cancel-recovery/report.json)

第一 session 写满 2 秒并启动原生任务后立即 `cancel`；取消返回时没有 final/complete。随后立即启动同配置
的第二 session 并识别完整 C1：旧 session 没有迟到回调，第二 session 正常一次 last 后一次 complete，
业务文本门通过。

### 4.5 证据留存

三轮的 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、`inventory.json` 和
`payload/corpus.json` 均保存在分支的
[`delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260805`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260805)
目录。最终 HAP SHA-256 为
`9dd070743ff1dba597631446e15fb5a5c062a999077bdc02c8c8097dd4aa611f`；三轮均绑定代码提交
`9d276554c686aea31db17354b7f5ece74ea35077`，报告中的 `voiceprintIdCount`、`fedFrames` 和
`lastFinalsBeforeFinish` 已与真实输入及生命周期断言一致。

### 4.6 合入前完整回归

同一 HAP 还完成了 21 个通用真机发布模式，全部 `overall_status=PASS`，包括基础实时/突发识别、
`vadBegin` 真实语音和纯静音、声纹评分与 cold/warm 回退、Speaker VAD、取消、最大时长、数值边界、
`onStart` 同步写入和卸载后冷加载，以及回调内重入和真实用户快速操作序列。完整模式清单与逐轮证据见
[`release-gate/20260805-9d27655`](../../delivery/harmony-dingqiao/evidence/release-gate/20260805-9d27655/README.md)。

## 5. 本轮发现并修复的问题

首次真机启动时，Harmony 原生 N-API 把 512 维 `Float32Array` 的长度报告为 2048 字节；若按标准
Node-API 的“元素数”直接读取，会把声纹误判为 2048 维，并把 32000 个音频采样误判为 128000。
修复后读取 TypedArray 视图自身的 `byteLength` 计算元素数，再用 `byteOffset` 和底层
`ArrayBuffer` 校验边界；因此即使输入是较大 buffer 的 subarray，也不会误把整个 buffer 当成视图。
同一 C1 输入从启动失败变为全链路通过。

实时测试最初也发现 0.5 秒重叠对应的 1.5 秒步长余量不足：25 块中最慢 1.607 秒。工程优化包括
并行计算两路 ERes2Net 分数，并把重叠缩短为 0.25 秒、步长增至 1.75 秒。最终三轮最慢 1.701 秒，
在不改变 2 秒模型输入和公开接口的前提下通过实时门禁。

## 6. 使用建议和妥协

- 该能力适合交警执法中“目标警员与他人同时说话”的重点场景，客户应在预期存在多人同时说话时开启。
- 周围只有目标说话人、环境安静或希望最低延迟时保持关闭；单人场景没有必要承担额外约 2 秒首块等待
  和数百 MiB 峰值内存。
- 目标说话人不在场时，公开模型在扩展负例中曾出现 `8/60` 个错误选中块，因此不能把该能力描述为
  “目标不在时绝对安全”。现有 Speaker VAD 会继续检查增强后的音频并可能拒绝片段，但不能把历史
  负例风险写成零。
- 当前只处理最多两路输出；三人及以上同时说话不在本实现承诺范围内。

## 7. 2026-08-06 正式资产与模型生命周期

Conv-TasNet 已用 Harmony 设备同版本 ONNX Runtime 1.16.3 转换为固定 ARM CPU 图的
`amphion-dingqiao/convtasnet_16k.ort`，并纳入标准 SDK rawfile、自包含 HAR、Demo HAP 和客户包校验。
正式组包不再允许缺少该文件，也不再依赖测试环境变量临时注入。

正式 ORT 为 `20,500,600 bytes`，SHA-256 为
`921dc579ae7fdff42b5b53d6d3408c520121c6292d2c69d5d8dc92908b05ad13`。在同一台 Apple Silicon
开发机、同一 ONNX Runtime 1.16.3 和相同线程/内存选项下，连续 7 次内存字节加载的中位数从 ONNX
的 `53.48 ms` 降为 ORT 的 `6.86 ms`，约 `7.80x`；固定随机输入的输出形状均为
`[1, 2, 32000]`，最大绝对差和平均绝对差均为 `0`。这些数据只证明格式转换和桌面端加载优化，
真机首会话耗时以第 8 节实测为准。

它与 ERes2Net 同属 SDK 的 L2 模型层：

1. 普通 ASR 和未开启增强的 session 不加载 Conv-TasNet。
2. 第一个开启 `enableTargetSpeakerEnhancement` 的 session 按需加载 ORT 模型；ORT 图已离线优化，
   加载时关闭重复图优化，并直接复用包内 FlatBuffer 字节，减少冷加载复制。
3. 后续增强 session 复用同一个 native ORT Session。每个 session 仍单独持有目标声纹、两个候选流的
   评分器、音频队列和回调状态；`finish`、`cancel` 或 engine `shutdown` 只释放这些 session 状态。
4. `SpeechRecognizeSdk.unloadModel()` 清除 ASR、ERes2Net 与 Conv-TasNet 的共享模型；
   `unloadRuntime()` 同样先清除模型。仍在执行的 native 任务通过共享引用安全完成，但调用方契约仍要求
   卸载前结束或取消所有 session 并关闭 engine。
5. 卸载不删除 HAR 内模型，也不删除已注册声纹 embedding；下次启用时重新冷加载，无需重新注册。

| SDK 状态/操作 | Conv-TasNet 共享模型 | 增强 session 状态 |
|---|---|---|
| `init` / `prepareRuntime` | 未加载 | 不存在 |
| 普通 ASR 或增强关闭 | 未加载或保持原状态，不触发加载 | 不创建 |
| 首个增强 session 启动 | 从 HAR 首次加载，进入可复用状态 | 创建目标声纹、评分器和队列 |
| `finish` / `cancel` / engine `shutdown` | 保持加载，供后续 session 复用 | 按各自契约关闭并释放 |
| `unloadModel` | 释放；活动任务仅由内部引用延迟到安全点销毁 | 调用方须先结束或取消 session |
| `unloadRuntime` | 与 ERes2Net 一样随 L2 模型一起释放 | Runtime 回到未初始化态 |
| 卸载后再次启用增强 | 重新从 HAR 冷加载 | 创建全新 session 状态 |

最终交付仍需用固定 ORT 资产执行 C1/C2/C3、目标不在场负例、目标单独说话和默认关闭精度回归。
生命周期的 cancel、onStart 同步写入、卸载后重载和 60 秒以上资源观察已由第 8 节覆盖。
当前设备支持范围仍以真机报告为准。

## 8. 2026-08-06 ORT 真机生命周期验证

正式资产已随 `ZH_EN` HAP 在 Mate 80（`VYG-AL30`，HarmonyOS `6.1.0.135`）完成编译、签名、
安装和包内哈希校验。随后从全新应用进程连续执行 3 个增强 session：

- 首轮首次加载 ORT，在 `onStart` 调用栈内写入 100 帧并继续写入，最终恰好一次 last、一次 complete；
- 第二轮在同一进程复用已加载模型，在 `onStart` 调用栈内立即 `finish`，仍恰好一次 last 后一次
  complete；
- 第三轮在 `onStart` 调用栈内立即 `cancel`，没有 final、complete 或迟到回调。

三轮均无 error、无跨 session 回调、结束后 native stream 数为 0；实际 Conv-TasNet 处理耗时为
`547～1,211 ms/2 秒块`。本轮使用固定声纹生命周期语料，只验证 ORT 可加载、同进程复用和回调契约，
不以空文本判断识别精度；C1/C2/C3 的内容收益仍由第 4 节固定 ONNX 实验支撑，需另用相同客户音频补做
正式 ORT 的输出回归。

证据保存在
[`20260806-ort-lifecycle`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260806-ort-lifecycle)，
包括 `report.json`、逐轮结果、内存采样、完整 hilog、设备包身份和输入映射。该轮总时长不足 15 秒，
因此内存趋势结论为 `INCONCLUSIVE`，不替代既有 122 秒资源观察。

审查补充门禁随后又执行了固定 4 阶段流程，证据见
[`20260806-ort-reload`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260806-ort-reload)：

| 阶段 | `startListening` 到 `onStart` | 生命周期结果 |
|---|---:|---|
| 首次冷加载 | 1028 ms | 一次 last 后一次 complete，0 error |
| 同进程复用 | 617 ms | 一次 last 后一次 complete，0 error |
| `shutdown → unloadModel → createEngine` | 1305 ms | 重新加载成功，一次 last 后一次 complete，0 error |
| `shutdown → unloadRuntime → prepareRuntime → createEngine` | 1305 ms | 重新加载成功，一次 last 后一次 complete，0 error |

四轮都在 `onStart` 调用栈内同步写入 100 帧，显式 `finish` 前 `isLast` 数为 0，结束后 native
stream 为 0，且无跨 session 回调。资源采样持续 `75.882 秒`：峰值 RSS `723.062 MiB`，稳定窗口
头部/尾部为 `492.424/478.600 MiB`，变化 `-13.824 MiB`，线程变化 `-5.5`，内存门禁为 PASS。
该语料只用于生命周期，4 个 terminal final 均为空，不能替代客户 C1/C2/C3 的内容精度回归。
