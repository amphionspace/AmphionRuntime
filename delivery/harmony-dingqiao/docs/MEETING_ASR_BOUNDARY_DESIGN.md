# 鸿蒙 ASR 分段语音与长语音边界设计

状态：第一阶段正确性修复已实现；stable-prefix checkpoint 留待独立 native 红灯闭环
基线：`origin/main@48829b8a7c4fe6b095b17816a642dcfa0d2acd7b`
分支：`fix/harmony-meeting-boundary-design`

## 1. 结论

`endpointMaxUtteranceMs` 不应在所有场景中表达同一种行为。

- **分段语音（`recognizerMode=short`）**：时长上限是业务可见的硬切句点。到达上限可以产生一次 public final，随后从新句继续识别。
- **长语音（`recognizerMode=long`）**：当前正确性优先实现不启用周期性 Rule3，依靠自然静音或显式 `finish` 分段，从执行路径上移除有缺陷的 60 秒 checkpoint。未来只有在 stable-prefix native 红灯与状态保持得到证明后，才能重新加入内部 checkpoint。

因此，会议场景不是“不该有时长参数”，而是这个参数不应同时承担“控制内部状态规模”和“强制形成一句 final”两种职责。

所有流式 ASR 都需要管理有限的模型上下文和解码状态，但这不等于必须每 60 秒丢弃上下文或强制切句。限制可以落在 encoder cache、稳定前缀提交、beam 剪枝或 session 时长等不同层次；能否无损跨越边界取决于状态转移设计，不是“流式模型天然只能识别 60 秒”。

## 2. 当前实现和风险

Harmony 当前固定使用 `modified_beam_search` 和 `maxActivePaths=8`。Rule3 命中后，native `CommitRule3Segment` 会：

1. 取 checkpoint 当下的最优 hypothesis；
2. 丢弃其已经发布的 token，只留下 decoder context；
3. 将 8 条活跃 hypothesis 收缩为 1 条；
4. 清空时间戳、LM/context 进度和 trailing blank 状态，再继续解码。

`0018-fix-asr-preserve-checkpoint-beam-normalization.patch` 保留了这条最优路径的长度归一化历史，但没有保留另外 7 条候选。

这意味着当前 checkpoint 与连续解码不具备一般等价性：如果 A 在 60 秒时暂时领先、B 需要边界后的声学证据才反超，连续解码仍可能选择 B；checkpoint 已删除 B，只能沿 A 继续。表现可以是边界附近或稍后的任意错字/丢字，不要求一定丢首字。

现有 native 单测反而固定断言 checkpoint 后 `hyps.Size() == 1`；长度归一化测试也只在 checkpoint 前放入一条候选，未覆盖“边界后候选反超”。这是当前测试缺口。

## 3. 行为边界

### 3.1 要改变的行为

- `recognizerMode=short` 和 `recognizerMode=long` 不再映射到相同实现语义。
- 长语音模式下，20/60 秒 Rule3 不再进入 public final 或 native checkpoint 路径。
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
| 到达时长但仍在说话 | 冻结当下句并产生 final | 保持原 stream 连续解码 |
| 未决尾部 | 可以进入下一句，接受硬切精度取舍 | 留在 native recognizer 中继续竞争 |
| 是否结束 session | 否 | 否 |
| `finish` | 唯一 last + complete | 唯一 last + complete |

默认值沿用公开文档中的 `recognizerMode=long`。这是对既有文档语义的真正落地，但会改变此前“参数被接受、实际仍按硬切”的行为，发布说明必须明确记录。确实依赖固定时长 final 的调用方应显式设置 `short`。

参数命名暂时保留以兼容客户集成，但文档按模式解释其含义。后续大版本可以拆成更准确的内部配置：

- `hardEndpointMaxUtteranceMs`：仅 short 使用；
- `checkpointTargetIntervalMs`：仅 long 使用。

不建议现在同时公开这两个新参数，否则会把 native 状态管理细节继续泄漏给调用方。

## 5. 后续 native 深模块设计

本节不是第一阶段交付路径。当前 long 模式通过明确的 `rule3=false` 禁用周期 endpoint；只有以下红灯和状态保持全部成立后，才考虑用 stable-prefix checkpoint 重新引入有界状态压缩。

边界 seam 必须位于 recognizer 内部，因为只有该层同时拥有 beam hypotheses、token/frame timestamp、encoder cache、decoder state、LM/context graph 进度和累计分数。

建议用一个原子操作替代当前“先 `getResult` 再冻结 best path”的浅接口：

```text
CheckpointResult OnlineRecognizer::CommitStablePrefix(stream, target_frame)

CheckpointResult:
  applied                  是否完成了一次内部状态压缩
  committed_tokens         本次可以永久发布的稳定 token
  committed_timestamps     token 在原 session 时间轴上的位置
  retry_after_frame        没有稳定前缀时的下一次检查点
  reason                   stable-prefix / deferred / natural-endpoint
```

该模块内部承担以下完整职责，调用方不检查或修改 hypothesis：

1. 在所有仍有竞争力的 hypothesis 中计算 longest stable common prefix。
2. 使用 token timestamp/frame guard 保留靠近边界的未决尾部，避免只因当前文本相同就过早提交。
3. 从每条 hypothesis 中移除已提交部分，但保留解码所需的 context tokens；内部 context overlap 带 native frame 边界，永不作为新 public token 返回。
4. 保留每条 hypothesis 的相对/累计分数、长度归一化 offset、LM/context graph 状态和未决 timestamps。
5. 重新生成与保留 hypothesis 对应的 decoder output；不得把 beam 收缩为 1 作为 checkpoint 的副作用。
6. 重基准 encoder cache/frame offset，同时保持 token timestamp 的 session 绝对时间轴单调。
7. 如果稳定前缀为空，不改变 recognizer 状态，返回 `deferred`；Runtime 稍后重试。

未来 Runtime 只消费 `CheckpointResult`：

- `committed_tokens` 非空时，按正常 public final 发布该稳定段，session 保持 active，`isLast=false`；
- 为空时不发空 final；
- Rule1/Rule2 或 `finish` 仍走原有 terminal path；
- 不再用 checkpoint 前一次 `getResult` 的完整 best path 作为要发布的 final。

如果业务不要求长语音每隔约 60 秒得到 final，可以进一步采用更保守的策略：checkpoint 只做内部状态压缩，稳定前缀通过 partial 暴露，直到自然静音或 `finish` 才形成 public final。是否采用这一层公开语义，应由客户对“周期性不可修改段落”的需求决定；native seam 不应因此改变。

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

long 模式当前不产生 Rule3 transition；short 的 Rule3 public final 也不是 session terminal condition，不能产生 `isLast=true` 或 `onComplete`。

## 7. 测试设计

### 7.1 后续 checkpoint 工作的首个红灯

新增 modified beam native 状态测试：

1. checkpoint 前放入 A、B 两条 hypothesis，A 的归一化分数暂时领先；
2. checkpoint 后喂入同一组未来分数，使 B 在连续路径中反超；
3. 对比 continuous 与 checkpoint 的最终 token；
4. 当前实现因删除 B 必须稳定红灯；修复后两条路径必须一致。

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

## 8. 本次长音频基线

`/Users/boxp/Downloads/testdata/` 中没有单条超过 60 秒的中文语音，因此从其中 Aidatatang 语料按确定顺序拼接出一条 156.06 秒、16 kHz、mono、PCM16 WAV；未向仓库提交原始或派生 PCM。

- WAV：`/private/tmp/amphion-meeting-boundary-design-artifacts/aidatatang-meeting-boundary-156s.wav`
- SHA-256：`20866a6d33260b54e52d3bd2b33396f5d594182ed9f5d62e3a19490c95286976`
- 60 秒位置：落在一条 5.94 秒真实语音内部约 2.148 秒处，不是静音拼接点；切点前后 1 秒 RMS `0.094434`
- 120 秒位置：落在一条 5.004 秒真实语音内部约 2.820 秒处，不是静音拼接点；切点前后 1 秒 RMS `0.031847`

固定条件：同一模型、100 ms chunk、800 ms warmup、Rule1/Rule2 设为 100000 秒以隔离 Rule3、Rule3=60 秒、`modified_beam_search/maxActivePaths=8`。

结果：

- continuous 在 60.2 秒观察到 Rule3，但不执行状态转换；最终 641 tokens；
- checkpoint 在 60.2 秒、120.4 秒完成 2 次真实 native checkpoint；最终 641 tokens；
- 两者 raw tokens 逐项完全一致，首个差异位置为空；该样本 **PASS，未复现边界错字/丢字**。

证据：

- continuous JSON：`/private/tmp/amphion-meeting-boundary-design-artifacts/continuous-mbs8.json`，SHA-256 `6154a214bbff6310a5f439569fc9a414594e3407db62aa3432a89285f21fbe7a`
- checkpoint JSON：`/private/tmp/amphion-meeting-boundary-design-artifacts/checkpoint-mbs8.json`，SHA-256 `281009ea2e27bbc47ac6f4cdc36bcf2d4be6840f1d4f838553abfbff953307b7`

这个 PASS 只说明该固定样本没有触发候选反超，不能证伪“checkpoint 丢弃其余 beam 候选会造成非等价”的结构性风险。重新实现 stable-prefix checkpoint 前应先用 7.1 的白盒用例建立稳定红灯，再决定是否需要扩大真实语料搜索。

第一阶段探索时先将 Rule3 设为 86400 秒做同音频差分；该次运行全程没有 60/120 秒 endpoint，结束时唯一 final，最终仍为 641 tokens，与 continuous oracle 逐项一致。提交实现随后改为显式 `rule3=false`，不再把 86400 秒 guard 作为产品语义：

- JSON：`/private/tmp/amphion-meeting-boundary-design-artifacts/long-mode-no-rule3-mbs8.json`
- SHA-256：`e54458c924d82bba943442664ef2dedb669ad72aa586b49288dde6509bfa5d41`

## 9. 实施顺序

1. 已完成：用 `recognizerMode=short/long` 分流 Rule3 语义并同步 Android；long 显式设置 `rule3=false`，底层以负最短句长表达禁用，不存在延后的周期边界。
2. 已完成：同一条 156 秒 PCM 验证 long 无 60/120 秒 endpoint，token 与 continuous oracle 一致。
3. 已完成：当前源码的 Harmony Debug HAP 编译，确认 ArkTS 配置链、HAR 和 native ABI 一致。
4. 待完成：真机公共回调验收，确认 short 的硬 final 与 long 的无周期 final 契约。
5. 后续独立工作：补“候选在边界后反超”的 native 红灯，再评估 `CommitStablePrefix`；该优化不得阻塞本次正确性修复。
6. 最后用客户原始长会议 PCM 做黑盒验收；没有原始 PCM 时，不把派生语料 PASS 当作客户问题已关闭。

## 10. 不采用的方案

- **仅把 60 秒改大**：只移动风险位置，不改变错误状态转换。
- **fresh stream / soft reset**：会丢 encoder 或 decoder 状态，已有边界空窗风险。
- **边界重放 PCM**：若没有 native token/frame seam，容易把 replay 污染公开文本、声纹和时长计数。
- **字符串去重或补字**：无法区分真实重复、ITN 变化和 replay token，会隐藏根因。
- **把 beam 固定为 1**：可以绕开“丢候选”的表象，但会改变模型解码质量，不是保持连续语义的修复。
