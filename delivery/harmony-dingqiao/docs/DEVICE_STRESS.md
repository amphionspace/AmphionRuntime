# Harmony ASR 真机压力测试

`delivery/run_device_stress.py` 将 PCM WAV 转为 16 kHz/mono/s16，推送到已连接的 Harmony
设备，并通过无 UI 的 HAP 载体直接调用鼎桥 SDK 公共 API。验收对象是 SDK，不是 demo 页面。
每次运行会采集载体进程的 RSS、VmData、VmSwap、线程数、SDK 回调契约和 native
online-stream 存活数。

当前 USB 问题验证统一使用配置为 `zh-CN`（core 枚举 `ZH_EN`）的单个测试 HAP。除非缺陷明确
涉及其他语种，不为压力测试额外构建或安装其他语种 HAP；这只限制测试载体，不改变 SDK/HAR
声明的语种能力。

## 选择验证范围

问题复现与发布回归是两个阶段：

- 问题复现只运行能证明症状、根因和修复的最小模式，再补与改动直接相邻的状态；达到停止条件后结束。
- 完整模式矩阵只在 PR 合入或正式交付前，对同一 commit、HAP 和设备执行一次。
- 对应当前 commit、HAP 哈希、设备和参数的有效 artifact 可以复用；不要重复构建、安装或运行。
- 用 SDK 可控状态转换代替业务等待。例如验证空闲卸载后的首次使用时，直接运行
  `start-write-reload`，不需要等待业务设置的五分钟定时器。

开始超过一分钟的构建或测试前，应先记录要排除的风险、预计耗时和停止条件。单个问题不能用
无关模式的更多轮数换取“覆盖所有边界”的表述。

0.3.0 异步 FIFO 曾在宿主 finish 兼容性上产生回归，原因和长期门禁见
[`FINISH_COMPATIBILITY_POSTMORTEM.md`](./FINISH_COMPATIBILITY_POSTMORTEM.md)。单独运行统一入口时，
它只构建一次并将两个客户时序的证据绑定到同一 commit、设备和 HAP/HAR：

```bash
python3 delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py \
  --data-dir "$HOME/Downloads/testdata"
```

汇总结果保存在 `build/release-gates/finish-compat/<gate-id>/report.json`，子目录保留两个模式的完整
`run_device_stress.py` artifact。任一模式失败或构建身份不一致时，整体门禁失败。

完整自动 AGC 发布入口会先验证客户 ZIP、外部 HAR、HAP 与 build identity 的一致性，再向该入口传入
`--reuse-verified-build`：已有 HAP 仍会安装并执行 UI smoke，只省略重复编译；两个真机模式仍复用同一次安装。

## 运行

从仓库根目录执行：

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir ~/Downloads/testdata \
  --mode burst \
  --cycles 200 \
  --files 48
```

默认会先构建、签名、安装并执行 UI smoke。确认设备已安装当前 HAP 时可加
`--skip-build-install`。结果写入
`delivery/harmony-dingqiao/build/device-stress/<run-id>/`：

如果目标是测量设备上已经存在、但本地没有对应 build identity 的 HAP，使用
`--installed-package`。该模式不会构建或安装，会把设备 `bm dump` 中的版本、签名指纹和完整
bundle 信息写入 artifact；它不能证明已安装 HAP 与当前源码一致，因此不能替代发布门禁的
构建身份校验。

- `report.json`：总体结论、回调计数、空结果率、native 流和内存判定。
- `memory.csv`：按时间采集的 `/proc/<pid>/status`，并保留进程/整机 CPU tick 与逻辑 CPU 数。
- `result.txt`：设备端逐轮契约结果。
- `hilog.txt`：本轮系统和应用日志。
- `payload/corpus.json`：源 WAV 到设备 PCM 的映射。

`report.json.cpu` 同时给出单核等效 CPU 百分比和整机容量百分比。前者 100% 表示占满一个
逻辑核，可以超过 100%；后者以全部逻辑核为 100%。CPU 统计只覆盖应用写出结果前的工作窗口，
不把结束后的空闲观察计入均值。

设备写出结果后会删除本轮 PCM、manifest 和 corpus 映射，避免重复压测持续占用应用存储；
主机侧 artifact 保留完整输入映射用于复核。

## 模式

| 模式 | 覆盖边界 |
| --- | --- |
| `burst` | 快于实时喂入、尾部 flush、长音频、连续会话 |
| `paced` | 20 ms 实时喂入，对照 burst 是否丢 backlog |
| `vad-begin` | 真实语音启用 10 秒 `vadBegin`，验证即使辅助 VAD 漏检，显式 finish 前也不会提前 `isLast` |
| `vad-begin-silence` | 纯静音命中 500 ms `vadBegin`，验证恰好一次 last/complete 且没有起音事件 |
| `voiceprint` | 轮换验证 500 ms 短句、1.5 秒门槛、3 秒长句、前置静音、低音量、多句连续输入和非注册语料源；只检查分数可选性与生命周期，不判定相似度精度 |
| `voiceprint-fallback` | 固定使用 `000_enroll.wav` 注册、`001_recognize.wav` 识别，覆盖严格窗口不足但 ASR 有非空 text/token 且整句 PCM 达标时的真实 PCM 回退；要求 cold/warm 第一条非空 endpoint final 均带分数 |
| `voiceprint-vad-begin` | 选择自身前 200 ms 已起音的真实语料，声纹开启且传入 1000 ms `vadBegin`，交替实时/突发喂入和直接起音/800 ms 前置静音；验证显式 finish 前无 `isLast`，足够长语音出现带分数 final |
| `voiceprint-vad-begin-idle` | 声纹开启且传入 1000 ms `vadBegin`，交替写入纯静音和稳态高能非语音；鼎桥固定 `minSegSec=0`，验证二者都没有额外确认窗并约在 1000 ms 有界结束 |
| `cancel` | 500 ms 后取消，验证无 final/complete 和短会话泄漏 |
| `cancel-full` | 完整音频解码后取消，隔离正常 finish 路径 |
| `max-duration` | 显式配置 8 秒，交替 burst/paced 并精确在 400 个 20 ms 帧后自动结束；验证 80 个迟到帧、单次 complete 和下一轮重启 |
| `continuous-long-session` | 同时配置 8 秒上限和 continuous，要求单个 model session 实时写入超过 60 秒，显式 finish 前无 last、最终唯一 last/complete，并通过 SHA-256 绑定的尾字断言；两轮运行用于区分首次驻留与持续内存增长 |
| `continuous-voiceprint-speaker-vad` | continuous 同时启用声纹校验和 Speaker VAD；语料尾部必须属于已注册的同一目标说话人，要求完整写入长语音、每个非空 final 都带真实 `speakerSimilarity`、显式 finish 前无 last、最终唯一 last/complete，并通过尾字断言 |
| `reconfigure` | 轮换 VAD 参数，覆盖引擎替换和旧引擎释放 |
| `recreate` | 每轮创建引擎并连续 shutdown 两次 |
| `edge` | 空闲调用、非法 session/帧、串 session、busy、重复 finish |
| `reentrant` | `onComplete` 回调内立即再次 `startListening`，验证完成态可重入 |
| `start-cancel` | `onStart` 回调内立即 `cancel`，验证取消后不再透出 start 后续事件 |
| `start-write` | `onStart` 调用栈内交替同步写入 32/88 个真实 PCM 缓存帧，并交替继续识别或立即 `finish`；验证成功回调前 session 已可用，且不返回 `NOT_LISTENING` / `FINISH_FAILED` |
| `start-write-reload` | 每轮执行 `shutdown -> unloadModel -> createEngine` 后复用 `start-write` 四种组合，等价覆盖业务空闲定时卸载后的再次冷加载 |
| `speaker-vad-onstart` | `StartParams` 只预置 `voiceprintIds`，两个声纹开关保持关闭；在 `onStart` 调用栈内同步启用 Speaker VAD，覆盖 burst/paced 与直接起音/800 ms 前置静音四种组合；足够长的同源有效语音必须至少产生一个带 `speakerSimilarity` 的非空 final，并在正常结束后立即启动恢复 session |
| `target-speaker-enhancement` | 使用第一个 WAV 注册声纹，其余 WAV 按 20 ms 节奏逐轮进行目标说话人增强；完整写入后要求逐条文本含“上海”且不含“你好”，每个 session 恰好一次 last/complete，所有 final 均带增强标记，并检查块耗时和最大排队数 |
| `target-speaker-enhancement-onstart` | 增强开启时在 `onStart` 调用栈内同步写入 100 个真实 PCM 帧，分别继续识别、立即 finish、立即 cancel，验证 session 在回调前已经可用 |
| `target-speaker-enhancement-cancel` | 写入 2 秒并启动后台增强后立即 cancel，随后零等待启动同配置恢复 session；验证取消会话无 final/complete、迟到任务不串入新 session，恢复会话正常结束 |
| `callback-api-reentrant` | 分别在同一 session 的 `SPEECH_BEGIN`、`SPEECH_END`、非 last `onResult` 回调内同步结束；其中 `SPEECH_END` 精确模拟客户只调用 `finish()` 的场景，其余入口执行 `writeAudio -> finish`，验证非空 terminal final、complete 不重复且 sessionId 归属不丢失 |
| `endpoint-reentrant` | 交替在旧 session 的 `SPEECH_END` 与 last `onResult` 回调内同步执行 `cancel(old) -> startListening(new)`；按 sessionId 对 start/partial/event/final/complete/error 的完整有序轨迹做切换前后快照，验证旧回调不污染新 session，且新 session 首帧前只有 start |
| `finish-shutdown` | 模拟旧 PTT 宿主在 `finish()` 返回且 `isBusy()==true` 时立即 `shutdown()`；逐轮重建 engine，要求已接受的 PCM 仍排空，并按 sessionId 恰好产生一次 last、随后一次 complete，不得被资源释放抢断 |
| `finish-shutdown-relicense` | 在 `finish -> shutdown` 后立即重新设置有效授权并重建 Runtime，覆盖 native async decode 尚未排空时的进程级释放竞态；要求旧 session 保留唯一 last/complete，释放后下一轮 Runtime 可恢复 |
| `user-sequence` | cancel 后零等待复用、finish 后立即重启、旧 session 迟到 write/finish/cancel 干扰当前 session；按 sessionId 校验回调归属和顺序 |
| `numeric-edge` | 交替省略 `maxAudioDuration` 和传入 `NaN`，写入超过 20 秒后仍保持活动，随后显式 finish 并验证一次 last/complete |

默认门槛为 RSS 增长不超过 64 MiB、线程增长不超过 2、正常结束模式空 final
不超过 5%。少于 15 秒的采样只报告 `INCONCLUSIVE`，避免把模型冷启动误判为泄漏。
`rss_slope_mb_per_minute` 和三段 RSS 中位数用于识别缓慢线性增长；斜率至少需要 60 秒观测，
且当前不单独作为硬门槛。

`speaker-vad-onstart` 的四个 cycle 恰好对应四种时序组合，每种只跑一轮；Speaker VAD 必须使用
注册时的同一语料源，因此这四轮不机械更换说话人。`callback-api-reentrant` 的三个 cycle 分别对应
三个回调入口，并通过 `--files 3` 映射到 30/60/120 秒分层语料。定向验收命令：

```bash
DATA="$HOME/Downloads/testdata/aishell4/prepared/test-d30x60x120-n4/cases"
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$DATA" --mode speaker-vad-onstart --cycles 4 --files 0 --skip-build-install
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$DATA" --mode callback-api-reentrant --cycles 3 --files 3 --skip-build-install
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$DATA" --mode finish-shutdown --cycles 10 --files 3 --skip-build-install
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$DATA" --mode finish-shutdown-relicense --cycles 2 --files 1 --skip-build-install
```

## 2026-07-10 基线

语料盘点：1894 条有效 WAV，约 3.09 小时；其中 1394 条 24 kHz、500 条 44.1 kHz，
时长约 1.10 到 48.88 秒。SDK 输入是 PCM，因此 MP3 不直接进入本工具。

| 用例 | 结果 | RSS 变化 | 线程变化 |
| --- | --- | ---: | ---: |
| 200 轮、48 条分位语料 burst | 200/200 PASS，空 final 2%，流存活 0 | +11.09 MiB | 0 |
| 100 轮、500 ms cancel | 100/100 PASS，流存活 0 | -0.90 MiB | -1.5 |
| 10 轮、完整 20 秒后 cancel | 10/10 PASS，流存活 0 | +8.41 MiB | -2 |
| 15 轮 VAD reconfigure | 15/15 PASS，流存活 0 | +8.02 MiB | -2 |
| 10 轮 engine recreate + 双 shutdown | 10/10 PASS，流存活 0 | +4.42 MiB | -2 |
| 3 轮 max-duration + 迟到帧 | 3/3 PASS，流存活 0 | +4.32 MiB | 0 |
| 扩展 edge 契约 | 8 个预期错误精确匹配，重复 finish 无额外错误 | 采样不足 | 采样不足 |
| 解码中强制停止进程后冷启动 | 中断被检测并保留日志；重启 edge PASS | 不适用 | 不适用 |

主稳压 artifact：
`delivery/harmony-dingqiao/build/device-stress/20260710-231528-burst-18e50bec`。
该轮 RSS 三段中位数为 694.57/682.59/694.20 MiB，未呈线性增长。

## 2026-07-11 adversarial 发现

新增三条红灯契约，用于固定当前 Harmony SDK 的高风险边界：

| 用例 | 结果 | 主要症状 | Artifact |
| --- | --- | --- | --- |
| `reentrant` 3 轮 | 3/3 FAIL | `onComplete` 回调内 `isBusy()==true`，立即 `startListening` 触发 `ENGINE_BUSY` | `20260711-112219-reentrant-4ff47443` |
| `numeric-edge` 3 轮 | 3/3 FAIL | `maxAudioDuration=Number.NaN` 后喂入 1168 帧仍无 `onComplete`，会话上限被绕过 | `20260711-112231-numeric-edge-f5bf6f84` |
| `start-cancel` 3 轮 | 3/3 FAIL | `onStart` 内立即 `cancel` 后，每轮仍有 1 个 native stream 存活 | `20260711-112628-start-cancel-dfa83bdb` |

其中 `numeric-edge` 是按当时“非法值回退到默认上限”的旧契约判定的历史红灯。0.2.5 已明确改为
“缺省或非法值不启用自动上限”，当前同名门禁因此要求写入超过 20 秒后仍保持活动，并由调用方显式
`finish`；这条历史记录不代表 0.2.5 的现存失败。

对照结果：单独重跑 `edge` 通过（`20260711-112205-edge-71f55e92`），标准
`max-duration` 通过（`20260711-111857-max-duration-457e0da3`）。因此新增失败集中在
回调重入、取消时序和非有限数参数处理，不是旧 edge/max-duration 路径回归。`start-cancel` 的根因指向
`startListening` 中 `this.session = this.asrEngine.newSession(callback)` 的赋值时序：如果
`newSession` 同步触发 `onSessionStarted`，客户在 `onStart` 中取消时 `tearDownSession()` 还看不到
新 session，无法关闭刚创建的 native stream。

## 2026-07-12 模型加载回归

加载优化后的 `zhen` 配置使用 4 个 ORT worker，不执行 eager silence warmup。独立进程
`createEngineAsync` 10 次结果为 p50 774.5 ms、p95 810.25 ms，pool hit 为 0–1 ms。

同一台设备随后使用 500 条 44.1 kHz 语料中的 24 条分位样本执行 48 轮 burst：

| 结果 | 首轮 | 总耗时 | 空 final | 峰值 RSS |
| --- | ---: | ---: | ---: | ---: |
| 48/48 PASS | 120 ms | 21858 ms | 4.1667% | 571.863 MiB |

artifact：`delivery/harmony-dingqiao/build/device-stress/20260712-101550-burst-edaea120`。
该结果用于防止去掉 eager warmup 后把全部成本转移到第一条真实音频；完整加载身份、历史对照
和复现命令见 [`MODEL_LOAD_PERFORMANCE.md`](./MODEL_LOAD_PERFORMANCE.md)。

## 已修复问题

1. online stream 原先只依赖 N-API finalizer，ArkTS 引用释放后 native 对象要等 GC，短会话呈现
   每轮约 4.6 MiB 的线性增长。现在 stream 具有显式幂等 `close()`，会话、硬重启、预热和
   speaker 临时流均在确定的所有权边界释放；finalizer 仅作兜底。
2. 长 WAV 快灌会连续占用 UIAbility event runner，触发 Harmony 6 秒前台阻塞 watchdog。
   burst 每 50 帧让出 1 ms，仍远快于实时但不再饿死事件循环。
3. Harmony 的 `stop()` 可同步回调，导致连续两次 `finish()` 的第二次被误报
   `FINISH_FAILED`。适配层保留最近正常结束的 session，直到下一次成功 start，使其与 Android
   的异步完成窗口一致。
4. 达到 max duration 后，同 session 的迟到采集帧会被安静丢弃；任意真正的空闲写入仍返回
   `NOT_LISTENING`。

## 2026-07-15 `isLast` / 声纹回归基线

设备为 MIA-AL00（OpenHarmony 6.1.0.115）。使用 `$HOME/Downloads/testdata` 中的
AISHELL-4 语料，以及从其中高能量语音段派生的 0.5–10 秒、前后静音和 -30 dB 边界片段，
在修复版 signed HAP 上共执行 15 组、855 个 session，全部通过。

| 覆盖 | 轮数 | 结果 | Artifact |
| --- | ---: | --- | --- |
| burst 短语音连续会话 | 100 | PASS，空 final 0，RSS +0.109 MiB | `20260715-002327-burst-72dbe5cf` |
| `vadBegin` 短句/1.49–1.51 秒/-30 dB | 200 | PASS，显式 finish 前无 `isLast` | `20260715-002458-vad-begin-c985a7ef` |
| paced 实时喂入 | 12 | PASS，空 final 0 | `20260715-002616-paced-8b9ab6eb` |
| 声纹 500 ms/3 秒交替 | 30 | PASS，短段无分数、长段有分数 | `20260715-002748-voiceprint-e36bc36b` |
| 纯静音 500 ms `vadBegin` | 200 | PASS，每轮恰好一次 last/complete | `20260715-002811-vad-begin-silence-8d9189d6` |
| cancel / cancel-full | 100 / 20 | PASS，无泄漏和多余回调 | `20260715-002854-cancel-3f858c03` / `20260715-002917-cancel-full-4bd69561` |
| max-duration / NaN 参数 | 10 / 10 | PASS，自动结束与默认兜底正确 | `20260715-002938-max-duration-592344c4` / `20260715-003012-numeric-edge-9da906f6` |
| edge / complete 重入 / start-cancel | 20 / 20 / 100 | PASS | `20260715-003045-edge-26eeaa69` / `20260715-003057-reentrant-9f058485` / `20260715-003118-start-cancel-29508762` |
| 重配 / 重建引擎 | 20 / 10 | PASS | `20260715-003138-reconfigure-3fcf8a0f` / `20260715-003201-recreate-55900a32` |
| 原始 30/60/120 秒长音频 | 3 | PASS，空 final 0 | `20260715-003215-burst-acb94700` |

本轮额外确认了两个测试方法问题：一是不能用“最终出现过 `isLast`”证明生命周期正确，必须在
调用 `finish` 前快照 last 数量并断言为 0；二是 `vadBegin` 回归不能把 `SPEECH_BEGIN` 当作
通过前提，因为要保护的正是辅助 VAD 漏检、但 ASR 已经识别的场景。纯静音自动结束必须由独立
模式验证。短句和低音量集允许空文本，但仍严格检查 last/complete 次数；普通语音集继续保留
空 final 门槛，避免用放宽识别质量指标掩盖问题。

## 2026-07-15 SDK 真实调用序列补充

在同一台 MIA-AL00（OpenHarmony 6.1.0.115）上补充调用方行为压力。`user-sequence` 每轮包含
3 次 start、1 次 cancel、2 次正常结束，并在新 session 活跃期间故意发送 3 个旧 session
调用。该模式不以识别文本或相似度精度作为 PASS 条件。

| 覆盖 | 轮数 | SDK 操作/回调 | 结果 | Artifact |
| --- | ---: | --- | --- | --- |
| `user-sequence` | 300 | 900 start、300 cancel、600 last/complete、900 旧 session 干扰调用 | 300/300 PASS；串 session 0；native stream 存活 0；RSS -23.324 MiB | `20260715-010331-user-sequence-a4bb07eb` |
| `edge` | 100 | 100 正常 session、800 个预期非法调用 | 100/100 PASS；native stream 存活 0 | `20260715-010911-edge-3c6a09c0` |
| `reentrant` | 300 | `onComplete` 内立即启动，共 600 session | 300/300 PASS；RSS -23.004 MiB；此前 100 轮上升在长跑中确认平台化并回收 | `20260715-011137-reentrant-2aadbdfc` |
| `paced` | 3 x 60 秒 | 20 ms 实时喂入，共 24 个句级 final | 3/3 PASS；调用 finish 前 `isLast` 为 0，结束后每轮恰好一次 last/complete | `20260715-011553-paced-147a7137` |

合入 review 后又用当前 PR HEAD 的 signed HAP 复核了可审计门禁。逐轮结果新增按 sessionId
记录的有序 callback trace 和意外 session 回调计数；`user-sequence` 只允许立即重启的单次
`ENGINE_BUSY` 及故意发送的旧 session 调用对应错误，其他错误直接失败。

| 覆盖 | 轮数 | 结果 | Artifact |
| --- | ---: | --- | --- |
| 声纹 7 类接口边界 | 7 | 7/7 PASS；短句省略分数，其余场景有分数；多句产生 3 个 final；串 session 0 | `20260715-065436-voiceprint-44a5556f` |
| `user-sequence` | 30 | 30/30 PASS；错误集合精确受限；native stream 存活 0；RSS +15.160 MiB | `20260715-065505-user-sequence-4bcd4a2b` |
| `max-duration` 迟到帧 | 2 | 2/2 PASS；80 个迟到帧后 final/last/complete/error 计数不变 | `20260715-065600-max-duration-7e369a38` |

声纹和 `max-duration` 复核轮次短，资源判定为 `INCONCLUSIVE`；它们只作为 callback 契约证据，
资源结论仍以长稳压结果为准。“非注册语料源”只证明未使用注册样本也不会丢失 final，不代表带身份
标注的非目标说话人精度结论。

## 2026-07-15 声纹与 `vadBegin=1000` 竞态复现

针对“首句已有识别文本，但 `speakerSimilarity=undefined` 且提前 `isLast=true`”建立了独立
`voiceprint-vad-begin` 门禁。该门禁只选择自身前 200 ms 已起音的真实语料，交替突发/实时喂入、
直接起音/800 ms 前置静音，并在调用 `finish` 前快照 `isLast` 数量。这个筛选很重要：如果载体注入
800 ms 后源文件自身还静音超过 200 ms，讲话实际晚于 1000 ms，自动结束本来就是正确行为。

| 阶段 | 轮数 | 结果 | Artifact |
| --- | ---: | --- | --- |
| 仅把有效等待钳制为 1500 ms | 20 | 20/20 提前结束，集中在约 1520 ms PCM | `20260715-153610-voiceprint-vad-begin-8a3ebbdc` |
| 改为 1000+1500 ms 静态证据窗口 | 40 | 8/40 提前结束；其中 4 轮 final 已有文本“提。” | `20260715-154224-voiceprint-vad-begin-24feed45` |
| “高能即永久起音”候选方案 | 40 | 40/40 PASS，但 review 发现稳态噪声会永久关闭超时，方案淘汰 | `20260715-154905-voiceprint-vad-begin-2d562386` |
| 纯静音/稳态高能非语音有界对照 | 100 | 100/100 PASS；恰好一次 last/complete；RSS +24.727 MiB | `20260715-171246-voiceprint-vad-begin-idle-ca698bb3` |
| 有界确认 + 语音型声学证据，短句多源 | 40 | 40/40 PASS；提前 last 0，空 final 0；RSS +31.434 MiB | `20260715-164326-voiceprint-vad-begin-bc146fc6` |
| `$HOME/Downloads/testdata` 长稳压 | 100 | 100/100 PASS；提前 last 0；RSS -4.305 MiB，斜率 -2.462 MiB/min | `20260715-170619-voiceprint-vad-begin-46ef77ac` |
| 最终分帧无关版本，短句多源组合回归 | 40 | 40/40 PASS；首个非空 final 带分数；提前 last 0 | `20260715-182307-voiceprint-vad-begin-27989eec` |
| 最终分帧无关版本，纯静音/稳态高能非语音 | 40 | 40/40 PASS；无 phantom final/SPEECH_BEGIN；均有界结束 | `20260715-182522-voiceprint-vad-begin-idle-c251101f` |

前两阶段证明只延长定时器不能消除竞态。第三阶段又证明只按音量永久解除计时会把提前结束换成
噪声环境无法结束。最终状态机保留 `vadBegin` 的纯静音语义：初始窗内有连续未决活动时只增加一次有界
确认；确认窗末仍有近期语音型能量变化和合格过零率时才解除计时，否则强制刷新 ASR，有 text/token 才
继续 session，仍为空就结束。零散或已经过去的脉冲不能直接解除计时，声学证据也不产生伪造的
`SPEECH_BEGIN`。100 轮长稳压约 4 分钟，
SDK 契约和资源门禁均通过；该生命周期模式的空文本率不作为 PASS 条件，避免混入精度评测。
完整根因、被淘汰方案和防复发清单见
[`VAD_BEGIN_VOICEPRINT_POSTMORTEM.md`](./VAD_BEGIN_VOICEPRINT_POSTMORTEM.md)。

## 2026-07-15 `onStart` 同步写入竞态

客户首轮冷加载期间会先缓存麦克风 PCM，收到 `onStart` 后在同一调用栈内冲刷 32 或 88 帧。
旧实现的 core session 构造函数同步触发 `onSessionStarted`，但鼎桥适配层要等 `newSession()` 返回后
才把返回值保存到 `this.session`。因此调用方已经收到成功回调，`writeAudio()` 却仍观察到
`session === undefined`，返回 `1002200010 NOT_LISTENING`。冷加载只会增加缓存帧数和首轮命中率，
不是模型加载失败；普通 burst 在回调返回后写入一直正常。

此前已有的 `start-cancel` 没有暴露这个缺陷，因为 `cancel()` 专门兼容了
`startingSession && session === undefined` 的半初始化状态；`writeAudio()` 和 `finish()` 没有这条补偿路径。
普通 burst 又是在 `onStart` 返回后才喂入，两个门禁都绕过了真正的失败窗口。Android 适配层则先发布
session、active sessionId 和 listening 状态，再通过 executor 异步发送 `onStart`，不存在同一时序缺口。
因此防复发重点是按每一种公共 API 分别验证回调内重入，而不是用一条 `start-cancel` 代表整个
`onStart` 可用性契约。

| 阶段 | 轮数 | 结果 | Artifact |
| --- | ---: | --- | --- |
| 修复前，`onStart` 内立即写第一帧 | 5 | 5/5 FAIL；每轮轨迹均为 `start > error-1002200010 > final-last > complete` | `20260715-232223-start-write-22c8cbfa` |
| 回调返回后普通 burst 对照 | 5 | 5/5 PASS；证明模型 ready 和 sessionId 正常 | `20260715-232519-burst-5138af17` |
| 修复后，交替同步冲刷 32/88 帧 | 100 | 100/100 PASS；错误 0，native stream 存活 0，RSS +35.547 MiB | `20260715-233830-start-write-d96f87fd` |
| 0.2.4 修复分支隔离构建、签名并安装后，以真实 PCM 冲刷复验 | 100 | 100/100 PASS；32/88 帧 x 继续/回调内 finish 各 25 轮；首轮冷加载 `engineReadyMs=804`，错误 0，native stream 存活 0，RSS +32.074 MiB | `20260716-002108-start-write-b00040e2` |
| 每轮 `shutdown -> unloadModel -> createEngine` 后重新冲刷 | 20 | 20/20 PASS；四种组合各 5 轮，20 次均为真实冷加载，`engineReadyMs=681..828`，错误 0，native stream 存活 0 | `20260716-011122-start-write-reload-8782a5ee` |
| 修复后 `start-cancel` / `reentrant` / `edge` | 100 / 100 / 100 | 全部 PASS，确认既有回调重入语义未回归 | `20260715-233159-start-cancel-da161eca` / `20260715-233237-reentrant-d886eba9` / `20260715-234107-edge-3e1fc223` |
| 0.2.4 修复分支相邻生命周期复验 | 50 / 50 / 50 / 30 | `start-cancel` / `reentrant` / `edge` / `user-sequence` 全部 PASS | `20260716-000224-start-cancel-2aae8fbe` / `20260716-000258-reentrant-2bb53260` / `20260716-000358-edge-cb8b2452` / `20260716-000439-user-sequence-12218b68` |

修复策略不是吞掉 `NOT_LISTENING` 或在调用方加延时，而是在同步底层回调期间暂存 started 信号；
待 session 已发布且会话级目标说话人配置完成后，再对外发送一次 `onStart`。因此 `onStart` 恢复为
“所有 session API 已可调用”的公共契约。

最终复验前有一轮 HDC 短暂掉线，artifact `20260716-002011-start-write-cadce3cf` 只有
`Device not found or connected`，未生成 SDK summary，记为外部环境 `INCONCLUSIVE`，不计作通过也不计作
SDK 失败；设备恢复后用相同 HAP、参数和语料完整重跑得到上表 100/100 PASS。

完整的五问分析、测试漏检原因和永久回调门禁见
[`ONSTART_SESSION_PUBLICATION_POSTMORTEM.md`](./ONSTART_SESSION_PUBLICATION_POSTMORTEM.md)。

这组结果提高了对高频调用时序的置信度，但不等于“所有边界已穷尽”。物理断连、系统杀进程、
低内存回收、多个进程同时持有 SDK，以及客户线程真正并行调用同一 engine，仍需要独立故障注入
或多线程载体验证。

## 剩余边界

- 主稳压采用按采样率和时长分位抽取的 48 条 WAV，不等同于 1894 条逐文件准确率评测。
- 本工具覆盖 ASR 会话和引擎生命周期，不覆盖声纹注册/删除压力；声纹需单独准备 3-8 秒样本
  和预期身份关系。
- 物理 USB 断连、系统主动低内存回收和设备重启需要人工控制，不能由本脚本安全自动触发。
- 当前 ArkTS 压测在单个 event runner 上交错 API 与回调，尚未覆盖多个客户线程真正同时调用同一 engine。
- 当前载体是单进程，尚未覆盖两个进程同时初始化 SDK、争用 workPath 或模型资源。
