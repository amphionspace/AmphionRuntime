# 声纹与最大音频时长回归证据

日期：2026-07-17

## 构建身份

| 项目 | 值 |
| --- | --- |
| Source commit | `5c6a3ae` |
| Branch | `fix/voiceprint-score-max-duration` |
| Device | `MIA-AL00` |
| OpenHarmony | `6.1.0.115` |
| Software | `MIA-AL00 6.1.0.117(SP8C00E115R8P4)` |
| Signed HAP SHA-256 | `a11e53508ed87014b4289fb5e914c83ef73a113222be9112d0a1aa26865d63ed` |
| Self-contained HAR SHA-256 | `2b0cf3b465ec6ec1ff8acfbb05a3c240556f4e19e40ad01d6e55f91158c6f742` |
| Enrollment WAV SHA-256 | `3cfffa6e0453bfc4b57fe659d3e872db99ce3be4c1f2169da35427b82fef637e` |
| Fallback recognition WAV SHA-256 | `90c9e25d26c99136dd60349e87d2bea87e0a61fa1fb4d41a97ed70dfdc3ba85e` |

HAP 经签名、模型 manifest、native 库、license 和 UI smoke 校验后安装。自包含 HAR 的内嵌
ASR/声纹模型、警务资源和 native 库与仓库源一致，并在只声明一个
`amphion_dingqiao.har` 的 clean customer host 中完成依赖安装和 HAP 编译。

HAP 字节码确认包含 `SpeakerScoreFallback`、`voiceprint-fallback` 和
`MAX_DURATION_TEST_MS`，不包含 `MIN_MAX_AUDIO_DURATION_MS`。

## 修复前红灯

旧 0.2.6 HAR 使用同一注册/识别输入执行三轮，三轮都产生 18 字非空 endpoint final，但
`speakerScores=0`、`firstNonEmptyFinalHasScore=0`，失败原因为
`endpoint-final-missing-speaker-score`。

Artifact：`20260717-155922-voiceprint-cold-e04fd4a8`。

## 主机和跨端门禁

| 门禁 | 结果 |
| --- | --- |
| `asr/tools/tests` 全量 Python 单测 | 83/83 PASS |
| Harmony 交付脚本全量 Python 单测 | 56/56 PASS |
| 定向门禁最终复核 | 15/15 PASS |
| Android `sdk` / `sdk-dingqiao` debug 单测 | BUILD SUCCESSFUL |
| Android `sdk` / `sdk-dingqiao` release 单测，rerun | BUILD SUCCESSFUL |
| 自包含 HAR clean-host 编译 | PASS |
| 签名 HAP build/install smoke | PASS |

## 问题定向真机结果

### 声纹回退

`voiceprint-fallback` 12/12 PASS：

- 第 0 轮 cold 和后续 11 轮 warm 全部 `firstNonEmptyFinalHasScore=1`；
- 每轮 `speakerScores=1`；
- 显式 `finish` 前 `lastFinalsBeforeFinish=0`；
- 每轮 native stream 为 0，无串 session 回调；
- 170.6 秒按现有硬阈值 PASS，RSS +37.074 MiB、VmData +42.719 MiB、线程变化 0；但 RSS
  斜率为 20.729 MiB/min，三段中位数仍为 718.055/738.898/749.086 MiB，因此趋势判断为
  `INCONCLUSIVE`。

Artifact：`20260717-173106-voiceprint-fallback-17027908`。

另用规范文件名 `000_enroll.wav` / `001_recognize.wav` 做最终 smoke，1/1 PASS：
`20260717-174536-voiceprint-fallback-326854b8`。

先执行的 6 轮短压中，SDK 契约 6/6 PASS，但 RSS +66.086 MiB 超出 64 MiB 门槛，整体记为 FAIL，
artifact `20260717-172911-voiceprint-fallback-615aaa49`。没有放宽阈值或覆盖该 artifact；
随后同 HAP、同输入扩展到 12 轮和 170.6 秒，增长降到 +37.074 MiB、线程稳定并按原硬门槛 PASS。
这足以说明该次 6 轮超阈值不能直接判为生命周期失败，但不足以证明增长已经平台化，也不能仅据此归因
为模型页驻留。当前把生命周期结论记为 PASS，持续内存泄漏风险记为 `INCONCLUSIVE`。

### `maxAudioDuration=8000`

burst 和 paced 各一轮，均在 `fedFrames=400` 时结束：

| 写入方式 | PCM 时长 | 墙钟耗时 | final/complete/error |
| --- | ---: | ---: | --- |
| burst | 8000 ms | 1417 ms | 1 / 1 / 0 |
| paced | 8000 ms | 11966 ms | 1 / 1 / 0 |

两轮 requested/effective 值均为 8000 ms，80 个迟到帧未增加回调，native stream 为 0。

Artifact：`20260717-173427-max-duration-e6fbe381`。

### 声纹相邻场景

客户注册 WAV 组合的 `voiceprint` 七类场景 7/7 PASS。短句按契约省略分数，门槛、长句、
前置静音、低音量、多句和 alternate-source 均满足分数可选性与生命周期要求。

Artifact：`20260717-173513-voiceprint-31688e04`。

## 完整 USB 回归矩阵

以下模式均使用同一 HAP，运行中未重新构建或安装：

| 模式 | 轮数 | SDK | 资源 | Artifact |
| --- | ---: | --- | --- | --- |
| `burst` | 20 | PASS | PASS | `20260717-173606-burst-b8118085` |
| `paced` | 2 | PASS | PASS | `20260717-173647-paced-cb2706da` |
| `vad-begin` | 8 | PASS | PASS | `20260717-173715-vad-begin-06029e63` |
| `vad-begin-silence` | 10 | PASS | INCONCLUSIVE | `20260717-173742-vad-begin-silence-2743ad2f` |
| `voiceprint` | 7 | PASS | INCONCLUSIVE | `20260717-173513-voiceprint-31688e04` |
| `voiceprint-fallback` | 12 | PASS | INCONCLUSIVE | `20260717-173106-voiceprint-fallback-17027908` |
| `voiceprint-vad-begin` | 8 | PASS | PASS | `20260717-173850-voiceprint-vad-begin-bf700644` |
| `voiceprint-vad-begin-idle` | 4 | PASS | INCONCLUSIVE | `20260717-173924-voiceprint-vad-begin-idle-07a9bbe1` |
| `speaker-vad-onstart` | 4 | PASS | PASS | `20260717-173937-speaker-vad-onstart-acb80140` |
| `cancel` | 10 | PASS | INCONCLUSIVE | `20260717-173754-cancel-05907052` |
| `cancel-full` | 4 | PASS | INCONCLUSIVE | `20260717-173805-cancel-full-b7729961` |
| `max-duration` | 2 | PASS | PASS | `20260717-173427-max-duration-e6fbe381` |
| `numeric-edge` | 2 | PASS | PASS | `20260717-174004-numeric-edge-59b5fb93` |
| `edge` | 4 | PASS | INCONCLUSIVE | `20260717-174024-edge-a36f8c0b` |
| `reentrant` | 5 | PASS | INCONCLUSIVE | `20260717-174035-reentrant-e76ce6f0` |
| `start-cancel` | 8 | PASS | INCONCLUSIVE | `20260717-174112-start-cancel-4cbafd88` |
| `start-write` | 4 | PASS | INCONCLUSIVE | `20260717-174125-start-write-28ac18f0` |
| `start-write-reload` | 4 | PASS | INCONCLUSIVE | `20260717-174137-start-write-reload-62af4775` |
| `user-sequence` | 10 | PASS | PASS | `20260717-174152-user-sequence-1f581bba` |
| `reconfigure` | 4 | PASS | INCONCLUSIVE | `20260717-174216-reconfigure-22c2211e` |
| `recreate` | 3 | PASS | INCONCLUSIVE | `20260717-174229-recreate-48f89373` |
| `callback-api-reentrant` | 3 | PASS | INCONCLUSIVE | `20260717-174256-callback-api-reentrant-2d7143cd` |
| `endpoint-reentrant` | 4 | PASS | INCONCLUSIVE | `20260717-174307-endpoint-reentrant-3248b8de` |

`INCONCLUSIVE` 表示资源证据不足，不表示 SDK 契约失败。170.6 秒 `voiceprint-fallback` 已超过最低
观察时间，但斜率和分段中位数仍上升，因此仍需更长轮次或与旧实现同输入对照；20 轮 burst 及其他
模式只能证明各自负载下未越过硬阈值，不能替代该对照。

## 结论与边界

当前证据证明：

- 原始 `speakerSimilarity=undefined` 状态在同输入下由 3/3 FAIL 变为 12/12 PASS；
- strict 主路径、短句可选值和真实 PCM 门槛保持不变；
- `maxAudioDuration=8000` 在 burst/paced 都按 8000 ms PCM 生效；
- final/last/complete、cancel、回调重入、冷加载、跨 session、迟到帧和 native stream 所有权未发现
  回退。

未覆盖物理 USB 断连、系统杀进程、多进程争用和声纹目标/非目标精度。持续内存趋势仍为
`INCONCLUSIVE`。客户识别阶段原始 PCM 未提供，因此本报告不声称覆盖客户现场全部声学前处理特征，
也不声称声纹精度已完成评测。
