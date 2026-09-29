# Harmony ASR 生命周期修复记录（2026-07-16）

本文保留当时的缺陷、修复机制、验证快照与资源观察，不作为当前发布矩阵，也不代表当前 HEAD 已通过验收。
现行规则统一见[公共契约](../../../docs/engineering/ASR_CONTRACTS.md)、[验证矩阵](../../../docs/engineering/ASR_VALIDATION.md)和[交付流程](../../ASR_DELIVERY_WORKFLOW.md)。

当时结论仅适用于记录中的复现条件、提交、设备与产物；不能表述为“覆盖所有边界”。Android 的后续对齐记录见[历史对齐清单](../../../docs/asr/ANDROID_LIFECYCLE_PARITY_TODO.md)。

## 历史问题与防复发机制

| 历史症状 | 根因层 | 修复机制 | 永久门禁 |
| --- | --- | --- | --- |
| 首句无分数并提前 last | 初始静音 deadline 与声纹最短有效语音窗口竞争 | 多信号起音确认；一次有界确认窗；旧活动不能直接解除计时 | `test_harmony_initial_silence_tracker`、`voiceprint-vad-begin`、`voiceprint-vad-begin-idle` |
| 连续识别提前 last / 旧结果污染新 session | 用全局 finish 状态推断较早异步 final；回调未绑定 session generation | 只依据当前结果的 `isLast`；所有回调校验 generation，并在外部监听器返回后复检 | `test_harmony_rejected_final_lifecycle`、`test_harmony_session_callback_generation`、`burst`、`paced`、`user-sequence` |
| 冷加载首次写入失败 | native started 同步回调早于适配层发布 session | started/published 双条件门禁，发布后才发送一次 `onStart` | `test_harmony_session_start_gate`、`start-write`、`start-write-reload` |

## 2026-07-16 验证快照

验证对象为同一 commit、同一中英 `ZH_EN` HAP 和一台 HarmonyOS 6.1 arm64 真机。测试数据为 16 kHz、16-bit、单声道 WAV。生命周期结果不以文本正确率判定 PASS。

| 模式 | cycle |
| --- | ---: |
| `voiceprint-vad-begin` | 4 |
| `speaker-vad-onstart` | 4 |
| `start-write-reload` | 4 |
| `numeric-edge` | 2 |
| `max-duration` | 1 |

汇总结果：

- 15/15 cycle PASS。
- 0 个失败 cycle，0 个意外回调，0 次显式 `finish` 前提前 last。
- 所有正常结束轨迹满足一次 `final-last` 后一次 complete。
- `voiceprint-vad-begin` 的 burst/paced、直接起音/前置静音四种组合各 1 轮；4/4 满足声纹分数契约，4/4 在 `finish` 前 last 数为 0。
- hilog 未命中 `SIGSEGV`、`SIGABRT`、native crash、double free 或 heap corruption 等强崩溃特征。

`0.2.5` 收敛候选构建完成了改动相关的定向复验：声纹首句分数、`vadBegin=1000`、
`onStart` 可用性、冷加载重载、非法/非有限 `maxAudioDuration` 和显式最大时长自动结束均通过。

关键内部 artifact：

| 证明目标 | run ID |
| --- | --- |
| 声纹与 `vadBegin=1000` 四组合 | `20260716-084318-voiceprint-vad-begin-b08b71fa` |
| `onStart` 内启用 Speaker VAD | `20260716-084335-speaker-vad-onstart-879e961d` |
| 冷加载 `onStart` 内同步写入 | `20260716-084357-start-write-reload-85f12115` |
| 非法/非有限数值参数 | `20260716-084405-numeric-edge-42d01c1b` |
| 显式最大时长自动结束 | `20260716-084446-max-duration-b9b853eb` |

每个 run 目录必须保留 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、`inventory.json` 和输入 payload 映射。

## 资源稳定性

| 场景 | 观察时间 | RSS 净变化 | RSS 斜率 | 线程变化 |
| --- | ---: | ---: | ---: | ---: |
| paced | 313.9 秒 | +6.24 MiB | +1.58 MiB/min | 0 |
| cancel-full | 533.0 秒 | +0.52 MiB | +0.39 MiB/min | 0 |
| reconfigure | 541.9 秒 | +1.26 MiB | +0.30 MiB/min | 0 |
| user-sequence 300 | 437.3 秒 | +5.55 MiB | +1.40 MiB/min | 0 |

短场景的瞬时 RSS 变化可能包含模型逐步驻留，不能单独判定泄漏。资源结论以超过 60 秒的观察和 `shutdown -> unloadModel -> createEngine` 后的可回落性为准。


## 当时未覆盖的边界

该历史验证不替代以下独立验证：

- ASR WER/CER 和声纹目标/非目标相似度精度评测。
- 任意回调内立即取消旧 session 并启动新 session 的极限重入路径；该项已记录为后续强化，不作为本次历史 bug 闭环条件。
- 物理断连、系统强杀、麦克风权限动态撤销、音频路由切换和系统级极端内存压力。
- 其他硬件型号、系统补丁版本及宿主调度器差异。

这些边界应作为外部故障与兼容性矩阵单独报告，不能混入生命周期 PASS 结论。
