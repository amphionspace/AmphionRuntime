# 鸿蒙 ASR 分段语音与长语音边界设计

状态：stable-prefix 原生状态机与 Harmony/Android 接线已实现；客户 PCM host A/B 已通过，真机回调验收待完成
基线：`origin/main@48829b8a7c4fe6b095b17816a642dcfa0d2acd7b`
分支：`fix/harmony-meeting-boundary-design`

## 1. 结论

`endpointMaxUtteranceMs` 不应在所有场景中表达同一种行为。

- **分段语音（`recognizerMode=short`）**：时长上限是业务可见的硬切句点。到达上限可以产生一次 public final，随后从新句继续识别。
- **长语音（`recognizerMode=long`）**：不启用周期性 Rule3，不产生固定时长 public final；每 60 秒只在 native 内尝试压缩所有活跃 beam 共同确认的 token/frame 前缀。没有稳定前缀就保持状态并每 1 秒重试，公开分段仍只由自然静音或显式 `finish` 触发。

因此，会议场景不是“不该有时长参数”，而是这个参数不应同时承担“控制内部状态规模”和“强制形成一句 final”两种职责。

所有流式 ASR 都需要管理有限的模型上下文和解码状态，但这不等于必须每 60 秒丢弃上下文或强制切句。限制可以落在 encoder cache、稳定前缀提交、beam 剪枝或 session 时长等不同层次；能否无损跨越边界取决于状态转移设计，不是“流式模型天然只能识别 60 秒”。

## 2. 原问题和当前修复

Harmony 当前固定使用 `modified_beam_search` 和 `maxActivePaths=8`。Rule3 命中后，native `CommitRule3Segment` 会：

1. 取 checkpoint 当下的最优 hypothesis；
2. 丢弃其已经发布的 token，只留下 decoder context；
3. 将 8 条活跃 hypothesis 收缩为 1 条；
4. 清空时间戳、LM/context 进度和 trailing blank 状态，再继续解码。

`0018-fix-asr-preserve-checkpoint-beam-normalization.patch` 保留了这条最优路径的长度归一化历史，但没有保留另外 7 条候选。

这意味着旧 checkpoint 与连续解码不具备一般等价性：如果 A 在 60 秒时暂时领先、B 需要边界后的声学证据才反超，连续解码仍可能选择 B；checkpoint 已删除 B，只能沿 A 继续。表现可以是边界附近或稍后的任意错字/丢字，不要求一定丢首字。

`short` 仍保留上述“冻结当前 best path”的硬切取舍。`long` 新增的 `CommitStablePrefix` 则只移除所有活跃 hypothesis 在 token ID 和 frame timestamp 上都一致的共同前缀，同时保留每条候选的未决尾部、累计分数、长度归一化 offset、LM/context graph 状态和 encoder 状态。已提交前缀移到 stream 的单份 transcript 缓冲，`getResult` 仍返回完整本句，因此不会引入跨 final 字符串拼接、重复 ITN 或时间轴重置。

## 3. 行为边界

### 3.1 要改变的行为

- `recognizerMode=short` 和 `recognizerMode=long` 不再映射到相同实现语义。
- 长语音模式下，20/60 秒 Rule3 不再进入 public final 或 native checkpoint 路径。
- long 模式每 60 秒尝试一次内部 stable-prefix 压缩；无共同 token/frame 前缀时不改状态、不发空结果，并在 1 秒后重试。
- `StartParams.extraParams['recognizerMode']` 可以覆盖 engine 缺省值，使同一调用方按 session 选择场景。
- short/long 或 short 的时长上限发生变化时，recognizer 配置键必须隔离复用。
- 不在 ArkTS/Kotlin 适配层拼字符串或猜测去重。

### 3.2 必须保持不变的行为

- `isFinal=true` 仍表示一个公开 endpoint 的最终结果；`isLast=true` 仍只表示 session 最后一条结果。
- 未调用 `finish(sessionId)`，且未命中显式 `vadBegin` / `maxAudioDuration` 时，不得出现 `isLast=true`。
- 正常结束仍恰好一次 `isLast=true`，随后恰好一次 `onComplete`；`cancel` 不产生 final/complete。
- Rule1/Rule2 的自然静音 endpoint 语义不变。
- 分段语音模式保留当前硬 endpoint 能力，避免 PTT、点击识别等调用方失去有界 final。
- checkpoint 的内部重叠/context token 不进入下一 public utterance 的声纹 PCM、Speaker VAD、`vadBegin` 或 duration 计数。
- Harmony 与 Android 的同名模式和回调语义一致。

### 3.3 明确不在本次设计中处理

- 不通过提高 60 秒阈值来宣称修复。
- 不更换 ASR 模型或用 WER 调参掩盖状态机问题。
- 不在适配层做字符串前后缀去重、补字或跨 final 文本纠错。
- 不把 `maxAudioDuration` 改造成 endpoint；它仍是显式的 session 自动结束条件。
- 不承诺在“恰好第 60.000 秒”既输出不可修订的完整 final、又与无限连续 beam 严格等价；两者在未决假设存在时不可同时保证。

## 4. 两种场景的公开语义

复用已经存在且对外接受的 `CreateEngineParams.extraParams['recognizerMode']`，不再新增第三个相近的场景参数。

| 行为 | `short`：分段语音 | `long`：长语音/会议 |
|---|---|---|
| 典型场景 | PTT、点击识别、短指令 | 会议、访谈、填单、持续转写 |
| Rule1/Rule2 静音 | public final | public final |
| `endpointMaxUtteranceMs` | public hard endpoint 上限 | 不生效 |
| 到达时长但仍在说话 | 冻结当下句并产生 final | 保持原 stream；仅尝试内部 stable-prefix 压缩 |
| 未决尾部 | 可以进入下一句，接受硬切精度取舍 | 留在 native recognizer 中继续竞争 |
| 是否结束 session | 否 | 否 |
| `finish` | 唯一 last + complete | 唯一 last + complete |

未传 `recognizerMode` 时保持旧调用方的 `short` 硬切行为。长转写、填单和会议 profile 必须显式设置 `long`，以落实不做周期性 Rule3 强切的新语义，同时避免旧业务在升级后丢失周期性 final。

参数命名暂时保留以兼容客户集成，但文档按模式解释其含义。后续大版本可以拆成更准确的内部配置：

- `hardEndpointMaxUtteranceMs`：仅 short 使用；
- `checkpointTargetIntervalMs`：仅 long 使用。

不建议现在同时公开这两个新参数，否则会把 native 状态管理细节继续泄漏给调用方。

## 5. stable-prefix native 设计

long 模式通过明确的 `rule3=false` 禁用周期 endpoint；内部压缩由独立计时器触发，不复用 endpoint 状态机。

边界 seam 必须位于 recognizer 内部，因为只有该层同时拥有 beam hypotheses、token/frame timestamp、encoder cache、decoder state、LM/context graph 进度和累计分数。

原生接口是一个不产生公开边界的原子操作：

```text
bool OnlineRecognizer::CommitStablePrefix(stream)
```

该模块内部承担以下完整职责，调用方不检查或修改 hypothesis：

1. 在所有仍存活的 hypothesis 中计算 token ID 与 timestamp 都一致的最长共同前缀。
2. timestamp 不一致时停止提交，避免只因当前文本相同就过早跨越声学边界。
3. 从每条 hypothesis 中移除已提交部分，但保留解码所需的 context tokens；内部 context overlap 带 native frame 边界，永不作为新 public token 返回。
4. 保留每条 hypothesis 的相对/累计分数、长度归一化 offset、LM/context graph 状态和未决 timestamps。
5. 使 cached decoder output 失效，由下一帧按保留 hypothesis 重新计算；不得把 beam 收缩为 1。
6. 不重置 encoder、frame offset 或 endpoint 计时，token timestamp 保持原 utterance 时间轴。
7. 如果稳定前缀为空，不改变 recognizer 状态并返回 `false`；Runtime 1 秒后重试。

Runtime 采用保守语义：stable-prefix 只做内部状态压缩，不形成 public final。已提交 transcript 与当前未决尾部在 native `getResult` 时合并，再统一执行 ITN/标点；Rule1/Rule2 或 `finish` 仍走原有 final 路径。

内存因此分成三类：feature/encoder cache 由流式实现自行淘汰或固定 left context；已经确认的
transcript 按输出 token 数线性增长，但只保存一份；每条活跃 beam 只保留 decoder context 和尚未
达成共识的尾部。正常收敛时，后两者比 8 条完整历史持续增长小得多。这个方案不宣称严格的常量
内存上限：如果所有 beam 长时间没有共同前缀，未决尾部仍会增长且压缩会每秒重试。若产品要求
“无论输入如何都严格封顶”，必须在超限时选择硬 endpoint/丢候选，或新增“稳定段 public final”
并允许调用方消费后释放 transcript；不能一边要求无限连续结果严格等价，一边无条件丢弃未决状态。

## 6. 状态和回调序列

```text
                    Rule1/Rule2 silence
ACTIVE ------------------------------------------------> PUBLIC_FINAL
  |                                                          |
  | short + Rule3 hard limit                                 | keep session
  v                                                          v
PUBLIC_FINAL ----------------------------------------------> ACTIVE

ACTIVE -- finish --> LAST_FINAL --> COMPLETE
ACTIVE -- cancel ----------------> CLOSED
```

long 模式不产生 Rule3 transition；stable-prefix 是 `ACTIVE -> ACTIVE` 的内部压缩，不触发 endpoint/final。short 的 Rule3 public final 也不是 session terminal condition，不能产生 `isLast=true` 或 `onComplete`。

## 7. 测试设计

### 7.1 checkpoint 首个红灯

新增 modified beam native 状态测试：

1. checkpoint 前放入 A、B 两条 hypothesis，A 的归一化分数暂时领先；
2. checkpoint 后喂入同一组未来分数，使 B 在连续路径中反超；
3. 对比 continuous 与 checkpoint 的最终 token；
4. 旧实现因删除 B 稳定红灯；修复后共同前缀被提交，A/B 两条未决路径都保留，B 可以在未来反超。

该红灯已经建立并转绿；另覆盖 timestamp 不一致时延后、无共同 token 时状态完全不变、committed transcript 单份累积和原 Rule3 行为不退化。当前原生定向套件 9/9 PASS。

该测试直接捕获根因，不能用“checkpoint 后还剩一条 hypothesis”作为正确性断言。

### 7.2 固定 PCM 差分

对同一 PCM、同一模型、同一 chunk、同一 warmup 和 `modified_beam_search/maxActivePaths=8` 分叉：

- oracle：命中 Rule3 后保留原 stream 连续解码；
- candidate：分别在 60 秒、120 秒执行真实 native checkpoint。

比较 raw token 和绝对 timestamp，第一个不同 token/frame 即失败；整段字符串相同但 token/timestamp 不同也不算通过。

### 7.3 生命周期相邻门禁

- short：硬 endpoint 后产生非 last final，后续音频属于新公开句；
- long：checkpoint 前后 `stream identity/generation` 符合设计，finish 前 `isLast=0`；
- checkpoint 无稳定前缀时不产生空 final；
- 60 秒和 120 秒连续两个 checkpoint 不重复、不漏 token；
- `finish` 后唯一 last，再唯一 complete；
- `cancel`、callback reentrant、voiceprint、Speaker VAD 与 checkpoint PCM 隔离保持现有契约；
- Harmony 与 Android 使用同一 native 语义和同名配置映射。

## 8. 固定 PCM 复现与 A/B

### 8.1 客户会议录音：稳定复现

从本地保留的客户问题数据中找到一条 213.28 秒、16 kHz、mono、PCM16 会议录音。其 SHA-256
`55007d53bcc9e9aeb67bb76592fdd3c7028c00526498a284d1ab79a5142084c2` 与仓库已有 AGC 证据账本一致；
原始 PCM 不提交仓库。

固定条件：同一 amphion-119 模型、100 ms chunk、800 ms warmup、Rule1/Rule2 设为 100000 秒以
隔离 Rule3、`modified_beam_search/maxActivePaths=8`。先分叉 continuous oracle 与真实 native
checkpoint，再用同一 PCM 运行无 Rule3 对照。

60 秒 Rule3 路径稳定复现了边界问题：

- 真实 checkpoint 在 60.2、120.4、180.5 秒命中三次；
- continuous 最终为 346 raw tokens，checkpoint 为 351 raw tokens；
- 两路在第 212 个 raw token 首次分叉；oracle token 时间为 143.56 秒，checkpoint 对应 token
  时间回落到 118.68 秒；
- 因此错误既不是只发生在第一个边界，也不要求表现为下一段首字丢失。

A/B 结果：

| 路径 | Rule3 行为 | endpoint | raw tokens | 与 continuous oracle |
|---|---|---:|---:|---|
| A：现有 checkpoint 语义 | 60 秒提交当前 best path | 3 | 351 | 第 212 token 起分叉 |
| B：long 语义 | 本段音频内不启用 Rule3 | 0 | 346 | 逐 token 完全一致 |

在实现 `CommitStablePrefix` 后，又用同一客户 PCM 做了第二组直接 A/B：两路共用同一已加载 recognizer，
固定 100 ms chunk、800 ms warmup、`modified_beam_search/maxActivePaths=8`、Rule3=`-1`；A 路完全
连续，B 路分别在 60、120、180 秒调用 stable-prefix。三次提交均成功，提交前后的公开 token/timestamp
均不变；两路最终都是 353 raw tokens，token 与 timestamp 逐项完全一致，全文也一致，全程 endpoint=0。
这组结果的 token 数与前一组 346 不直接横比，因为 host 线程配置不同；A/B 内部的模型、线程、PCM 和
调用时序完全相同，唯一变量是是否执行 stable-prefix。

host 诊断动态库早于禁用补丁，B 路使用 `rule3=100000` 仅表达“这 213.28 秒内不发生 Rule3”；
它不是产品配置，也不能代替禁用值测试。产品实现使用 `rule3=-1`，当前补丁源码重新构建后的
`Endpoint.NegativeMinimumUtteranceDisablesRule` 定向 native 测试为 1/1 PASS。

证据：

- 复现与 oracle JSON：`/private/tmp/amphion-meeting-boundary-design-artifacts/customer-213s-rule3-search.json`，
  SHA-256 `19995e3199ce559ef8b746bd93bbe0e993c5dd72cf7429a5c6a18c8b6f31179f`
- long 对照 JSON：`/private/tmp/amphion-meeting-boundary-design-artifacts/customer-213s-long-no-rule3-proxy.json`，
  SHA-256 `f652beb29ef752302b148b4136d06b903986d71dede6dde456989a378153573f`
- stable-prefix 直接 A/B JSON：
  `/private/tmp/amphion-meeting-boundary-design-artifacts/customer-213s-stable-prefix-ab.json`，
  SHA-256 `315117c6603a7f87737e246e490536c8a42aad5a065636a411d10d237dedf424`

### 8.2 公网连续长语音：21 分钟 A/B

从 LibriVox 官方目录下载 public-domain 录音《Ardath》第一章，原始 MP3 由 Internet Archive
托管。该文件是同一朗读者连续 21:15 的自然长语音，不是短句拼接：

- 目录：`https://librivox.org/ardath-by-marie-corelli/`
- 原始 MP3：`https://archive.org/download/ardath_2003_librivox/ardath_01_corelli_128kb.mp3`
- MP3 SHA-256：`dc68c9b5696f328e028f619a7fec54e5ee0dc0e0986f01ae0db3d78840071016`
- 转码：macOS `afconvert`，16 kHz、mono、PCM16LE；时长 1275.1008125 秒
- WAV SHA-256：`187800cb21fb7779aec93d327431fc0265a3b9acc9ec42a4ec61ddd405ae7e7f`

固定与客户 PCM 相同的模型、100 ms chunk、800 ms warmup、Rule3=`-1`、
`modified_beam_search/maxActivePaths=8`。continuous 与 stable-prefix 最终均为 3974 raw tokens，
token、timestamp 和全文逐项完全一致，两路 endpoint 都是 0。

stable-prefix 成功提交 19 次；另有 98 次因当时不存在可安全提交的共同 token/frame 前缀而返回
false，并按设计每秒重试。所有失败尝试均保持公开 token/timestamp 不变，后续形成共同前缀后继续
提交。这证明 long 路径会保留未决候选，不会为了固定周期强制压缩。

主机 RSS 只作为观察项：continuous 受 allocator/系统回收影响先升后降；stable 从约 506 MiB
增至 636 MiB。两路在同一 Python 进程顺序运行，且完整结果保留在测试报告中，不能据此证明泄漏或
严格有界；内存结论仍需同一最终 HAP 的真机 RSS/线程采样。

证据：`/private/tmp/amphion-meeting-boundary-design-artifacts/internet-long-audio/ardath-1275s-stable-prefix-ab.json`，
SHA-256 `4e195af36842a25f3366c2f8efee9144f8775ce8fb6a954fe9d0e3cb2425ba8c`。

### 8.3 拼接语料：保留为阴性对照

此前从 Aidatatang 确定性拼接的 156.06 秒语料在 60.2、120.4 秒执行 checkpoint 后仍与
continuous 的 641 tokens 完全一致。它没有复现问题，只能作为“并非每条音频都会分叉”的阴性
对照，不能再作为本方案的主要正确性证据。

## 9. 实施顺序

1. 已完成：用 `recognizerMode=short/long` 分流 Rule3 语义并同步 Android；long 显式设置 `rule3=false`，固定时长不再形成 endpoint。
2. 已完成：客户 213.28 秒 PCM 在 60 秒 checkpoint 下稳定复现 raw token 分叉；同输入 long
   对照与 continuous oracle 逐 token 一致。
3. 已完成：当前源码的 Harmony Debug HAP 编译，确认 ArkTS 配置链、HAR 和 native ABI 一致。
4. 已完成：补“候选在边界后反超”的 native 红灯并实现 `CommitStablePrefix`；原生状态机 9/9、C API 构建、Harmony 策略测试和 Android SDK/适配层单测通过。
5. 已完成：用同一客户 PCM 做 host native stable-prefix A/B；60/120/180 秒三次提交后与 continuous
   的 raw token/timestamp 完全相同，且未产生 endpoint。
6. 待完成：真机公共回调验收，确认 short 的硬 final、long 的无周期 final 和 stable-prefix 内部提交日志。
7. 待完成：用同一客户 PCM 做 Harmony 真机公共 API 黑盒 A/B；host native A/B 证明了 Rule3
   状态分叉，但不能替代最终 HAP 的回调与组包验收。

## 10. 不采用的方案

- **仅把 60 秒改大**：只移动风险位置，不改变错误状态转换。
- **fresh stream / soft reset**：会丢 encoder 或 decoder 状态，已有边界空窗风险。
- **边界重放 PCM**：若没有 native token/frame seam，容易把 replay 污染公开文本、声纹和时长计数。
- **字符串去重或补字**：无法区分真实重复、ITN 变化和 replay token，会隐藏根因。
- **把 beam 固定为 1**：可以绕开“丢候选”的表象，但会改变模型解码质量，不是保持连续语义的修复。

## 11. 开源实现参考

- Kaldi `OnlineFasterDecoder` 的 immortal token：从所有活跃 token 回溯共同祖先，只提交未来音频无法改变的路径；这是本方案最接近的状态机参考。https://github.com/kaldi-asr/kaldi/blob/master/src/online/online-faster-decoder.cc
- Whisper Streaming 的 LocalAgreement：连续两次解码结果的最长共同前缀才提交，并只在已确认边界裁剪音频；其思想可参考，但它依赖重复解码，不直接适合本项目 RNNT beam 内部状态。https://github.com/ufal/whisper_streaming/blob/main/whisper_online.py
- sherpa-onnx、Vosk 的常规在线路径都在 endpoint 后 reset/restart，适合自然分句，但不能证明固定时长 mid-speech 硬切无损。https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/csrc/online-recognizer-transducer-impl.h https://github.com/alphacep/vosk-api/blob/master/src/recognizer.cc
- WeNet 可以通过 left chunks 限制 encoder attention cache，但 CTC prefix hypotheses 仍持续到 reset；它说明“encoder cache 有界”不等于“整条解码输出状态有界”。https://github.com/wenet-e2e/wenet/blob/main/docs/runtime.md
