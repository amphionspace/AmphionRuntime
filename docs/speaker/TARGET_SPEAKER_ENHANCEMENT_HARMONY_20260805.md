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

技术实现和真机验证已完成，但当前 Conv-TasNet 权重没有进入源码或正式 HAR。公开模型页面同时出现
CC BY-SA 4.0 与基于 LibriSpeech 的 CC BY-SA 3.0 两种描述，商用权利范围不够明确。因此，本实现目前
是“代码可交付、模型待商用授权”的状态，不能把临时测试包作为正式客户包发布。

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

最终结果摘要如下。早期现场包含设备序列号和未脱敏识别文本，已从当前工作树移除；后续发布验收使用统一的脱敏、不可覆盖证据格式。

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

对应的后续脱敏验收见
[`start-write/report.json`](../../delivery/harmony-dingqiao/evidence/release-gate/20260824-97434d1-0.3.9/modes/start-write/report.json)。

增强开启时分别在 `onStart` 调用栈内同步写入 100 个真实 20 ms PCM 帧，然后继续识别、立即
`finish`、立即 `cancel`。三种路径全部通过：继续和结束路径各恰好一次 last/complete；取消路径没有
final/complete；均没有 `NOT_LISTENING` 或其他错误。

### 4.4 取消和立即恢复

对应的后续脱敏验收见
[`cancel-full/report.json`](../../delivery/harmony-dingqiao/evidence/release-gate/20260824-97434d1-0.3.9/modes/cancel-full/report.json)。

第一 session 写满 2 秒并启动原生任务后立即 `cancel`；取消返回时没有 final/complete。随后立即启动同配置
的第二 session 并识别完整 C1：旧 session 没有迟到回调，第二 session 正常一次 last 后一次 complete，
业务文本门通过。

### 4.5 证据留存

早期原始现场不再保存在当前 Git 工作树；本节保留结论和构建身份，后续验收统一使用
`archive_release_gate_evidence.py` 生成的脱敏证据。最终 HAP SHA-256 为
`9dd070743ff1dba597631446e15fb5a5c062a999077bdc02c8c8097dd4aa611f`；三轮均绑定代码提交
`9d276554c686aea31db17354b7f5ece74ea35077`，报告中的 `voiceprintIdCount`、`fedFrames` 和
`lastFinalsBeforeFinish` 已与真实输入及生命周期断言一致。

### 4.6 合入前完整回归

同一 HAP 还完成了 21 个通用真机发布模式，全部 `overall_status=PASS`，包括基础实时/突发识别、
`vadBegin` 真实语音和纯静音、声纹评分与 cold/warm 回退、Speaker VAD、取消、最大时长、数值边界、
`onStart` 同步写入和卸载后冷加载，以及回调内重入和真实用户快速操作序列。完整模式清单与逐轮证据见
[`release-gate/20260824-97434d1-0.3.9`](../../delivery/harmony-dingqiao/evidence/release-gate/20260824-97434d1-0.3.9/report.json)。

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

## 7. 正式商用发布门禁

当前代码故意不提交或默认打包 Conv-TasNet 权重。正式客户包发布前必须全部完成：

1. 对目标 ONNX 获得权利方书面商用授权，或替换为许可清晰且允许闭源分发的自有/第三方模型。
2. 固定最终模型文件、来源、版本、SHA-256、训练数据权利说明和随包声明。
3. 将最终模型放入 `amphion-dingqiao/convtasnet_16k.onnx`，并让交付脚本验证文件哈希；没有模型时
   启用接口必须明确返回 `START_LISTENING_FAILED`，不能静默退回原方案。
4. 用最终模型重跑 C1/C2/C3、目标不在场负例、目标单独说话、cancel、onStart 同步写入、
   60 秒以上资源观察和默认关闭回归。
5. 只在通过上述门禁的设备档位开放接口；当前支持证据仅覆盖本报告的 12 GB Mate 80。

授权核查来源：

- 模型页：<https://huggingface.co/JorisCos/ConvTasNet_Libri2Mix_sepclean_16k>
- CC BY-SA 4.0 条款：<https://creativecommons.org/licenses/by-sa/4.0/legalcode.en>

模型页顶部标为 CC BY-SA 4.0，而说明末尾又称衍生自 LibriSpeech 并按 CC BY-SA 3.0 授权；在权利方
或法务书面确认前，不把该权重放入正式商用包。

正式组包脚本已增加双重保护：默认从自包含 HAR 删除任何测试遗留的 Conv-TasNet；只有显式传入并
匹配已批准 SHA-256 才允许保留。无模型的自包含商用 HAR 已在干净客户工程完成安装和编译验证；
本轮产物大小为 `263,772,830 bytes`，SHA-256 为
`cd1b3ebee3da8c87834ce40b50d964e4e73db39c7b4e472b88eebbc44565d310`，归档内确认不存在
`convtasnet_16k.onnx`。
