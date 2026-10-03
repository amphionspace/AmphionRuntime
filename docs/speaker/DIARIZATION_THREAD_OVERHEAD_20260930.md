# 角色链路的线程预算：历史 FP32 结果与当前 INT8 执行器（2026-09-30，2026-10-02 更新）

**当前结论：旧 FP32 XNNPACK 4→2 线程的 CPU 收益不能用于解释或选择当前 Harmony INT8 的线程预算。** 2026-10-02 的 round3 前七个 arm（CPU1 基线、CPU2-only、CPU4-only、CPU4-only+ASR cursor、恢复 XNNPACK arena、Runtime ready-gate、ASR stages）全部 FAIL。第八个 ASR4 prepack arm 的短程 overall/application/role lifecycle 为 PASS，但 late-wall 仍高于 1 秒，角色处理滞后仍随音频进度增长，不能外推为长期或热通过；第九个 ASR2 prepack arm 的 overall FAIL 保留 RSS/thread growth advisory，虽然 application 和唯一 last/complete PASS，也不采用 ASR2。第十臂 encoder active-only bounded spin 短程 PASS，但晚段滞后与收尾均比第八臂更慢，不采用；生产保留 encoder `allow_spinning=0`。CPU-only 对照还同时改变了 XNNPACK provider/allocator 注册，不能称为纯 CPU 预算单变量。恢复 XNNPACK 后的 `1078 ms`、ready-gate 的 `1100 ms` 和 ASR stages 的 `1106 ms` median 都不是 1 秒稳态达标证据。

canonical per-channel INT8 的 36 个卷积使用 UINT8 激活与 INT8 权重；XNNPACK 不认领这组 U8S8 per-channel Conv，但 provider 注册仍影响 ORT 的 preferred allocator。兼容性、ASR 争用、收尾与热量必须分别判定，不能以 profile 的 `xnnProvider=0` 把 XNNPACK 注册和 allocator 路径删掉。

下文保留 FP32、per-tensor 和 per-channel 实验作为各自构建/模型下的历史证据。
“软件层已无优化空间”“只能换模型”“所有空转和并发开销已排除”的旧结论撤回。

<a id="2026-10-02-round3cpu-provider-asr-cursor"></a>

## 2026-10-02 round3：CPU 预算、provider 变量与 ASR cursor

十二个 arm 使用同一 canonical per-channel INT8 encoder（SHA-256 `368629e9bad8277b5249b70eec1879bf293e1be614569c3257fdea937211eedd`）、同一 120 秒载体、20 ms 喂入、ASR `cpuIds=[4..11]`、`spinning=false`；冻结 HAP 与逐臂报告见表中链接。除第九臂外均使用 `ASR numThreads=4`。第八臂与第七臂使用同一 HAP，只增加 `--asr-enable-prepack`；第九臂与第八臂使用同一 HAP，只将 `--asr-num-threads 4` 改为 `2`，继续开启 prepack。第十臂以第八臂为基线，仅将 encoder 改为 `allow_spin=1/force_stop=1`。CPU2-only 与 CPU4-only 使用同一 CPU-only HAP；从 XNNPACK arena restore 起的八个 arm 都保留 XNNPACK provider/allocator 注册。

| arm | 冻结身份 | 窗口数 | wall 中位数 | embedding 中位数 | finish / tail 现场 | 结果 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| CPU1 基线（CPU fallback 1，XNNPACK budget 4） | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpuFallback1Screen120/probe-analysis.json) / [identity](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpuFallback1Screen120/build-identity.json) | 70 | 1988.5 ms | 1580.474 ms | role finish lag 55 s；ASR tail +11.694 s，随后 barrier timeout +15.002 s，complete +26.696 s | FAIL；finals 10、completes 1，角色 degraded reason 4 |
| CPU2-only | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpuBudget2Screen120/probe-analysis.json) / [identity](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpuBudget2Screen120/build-identity.json) | 101 | 1377 ms | 965.350 ms | role finish lag 32 s；ASR tail +25.942 s；载体 30 s 内未见 role drain/complete | FAIL；finals 9、completes 0 |
| CPU4-only | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpuBudget4Screen120/probe-analysis.json) / [identity](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpuBudget4Screen120/build-identity.json) | 111 | 1157 ms | 736.716 ms | role finish lag 16 s；local drain +18.618 s；ASR tail 未出现 | FAIL；finals 9、completes 0 |
| CPU4-only + ASR cursor | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrCursorScreen120/probe-analysis.json) / [identity](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrCursorScreen120/build-identity.json) | 111 | 1164 ms | 747.119 ms | role finish lag 17 s；local drain +18.948 s；request finish 时 processed=1427200 | FAIL；finals 9、completes 0 |
| CPU4 + XNNPACK arena restore | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4XnnArenaScreen120/probe-analysis.json) / [HAP f8a56fcd3a2ad08c5bab3b5351d119a1398d113ee8344ce48c1d24b35e8a9470](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4XnnArenaScreen120/build-identity.json) | 111 | 1078 ms | 656.431 ms | role native drain +10.095 s；finish 时仍有 ASR cursor backlog；无 tail、stop enter/exit | FAIL；finals 9、completes 0；report lifecycle `PASS` 但 `completed_sessions=0`，该子项尚未覆盖完成会话；native 排空另由 `local-drained` + 111 窗事件证明，不是公共角色生命周期或身份通过 |
| CPU4 + Runtime ready-gate | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4ReadyGateScreen120/probe-analysis.json) / [HAP dc0dc80a19d5a6a1263b5adb2709233da76f2f2812dc626d9331eefd5aeaf0fc](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4ReadyGateScreen120/build-identity.json) | 111 | 1100 ms（晚 56 窗 1098 ms） | 661.570 ms | role native drain +10.122 s；local-finish +1 ms 收到 ASR request `processed=1457920`；无 tail、stop enter/exit | FAIL；finals 9、completes 0；原始 cursor backlog `(1920000−1457920)/16000=28.880 s`；report lifecycle `PASS` 但 `completed_sessions=0`，该子项尚未覆盖完成会话；native 排空另由 `local-drained` + 111 窗事件证明，不是公共角色生命周期或身份通过 |
| CPU4 + ASR stages | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrStagesScreen120/probe-analysis.json) / [stages](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrStagesScreen120/asr-stages-analysis.json) / [cursor](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrStagesScreen120/asr-cursor-summary.json) / [HAP a075ff37fb05631188374df98c7d1c02b3c99f5e68d4978c97f76ef82f063ea7](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrStagesScreen120/build-identity.json) | 111 | 1106 ms（晚 56 窗 1099.5 ms；输入起点≥60 s 为 1111 ms） | 678.685 ms | segmentation 361.155 ms；role native drain +13.513 s；same-ts ASR request `processed=1457920`；110 s 音频仍无 stop/tail/complete | FAIL；finals 9、completes 0；原始 cursor backlog 28.880 s；report lifecycle `PASS` 但 `completed_sessions=0`，该子项尚未覆盖完成会话；native 排空另由 `local-drained` + 111 窗事件证明 |
| CPU4 + ASR4 prepack | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrPrepackScreen120/probe-analysis.json) / [scalar comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrPrepackScreen120/prepack-vs-baseline-scalar-comparison.json) / [HAP a075ff37fb05631188374df98c7d1c02b3c99f5e68d4978c97f76ef82f063ea7](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrPrepackScreen120/build-identity.json) | 111 | 1062 ms | 613.637 ms | segmentation 359.381 ms；ASR finish backlog 0；genuine tail +1.800 s；role drain +7.590 s；complete +7.877 s | overall/application/role lifecycle PASS（短程）；finals 10、completes 1；role late-wall mean/median 1042.784/1053 ms，lag slope +58.306878 ms/audio-sec；不能外推长期实时或热通过 |
| CPU4 + ASR2 prepack | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4Asr2PrepackScreen120/probe-analysis.json) / [scalar comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4Asr2PrepackScreen120/asr2-vs-asr4-prepack-scalar-comparison.json) / [HAP a075ff37fb05631188374df98c7d1c02b3c99f5e68d4978c97f76ef82f063ea7](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4Asr2PrepackScreen120/build-identity.json) | 111 | 1066 ms | 631.564 ms | segmentation 350.388 ms；ASR finish backlog 0；role drain +10.616 s；complete +10.878 s | overall FAIL（保留原始 RSS/thread growth advisory）；application PASS、唯一 last/complete；role late-wall mean/median 1069/1064 ms，lag slope +72.1819 ms/audio-sec；不采用 ASR2 |
| CPU4 + encoder active-only bounded spin + ASR4 prepack | [analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4ActiveSpinPrepackScreen120/probe-analysis.json) / [HAP 511269d6be4c4275920d52ceb46c7692f25042e9421eaf8e7e4fdb2cd0250435 / comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4ActiveSpinPrepackScreen120/active-spin-vs-baseline-scalar-comparison.json) | 111 | 1089 ms | 641.577 ms | ASR finish backlog 0；真实 tail +1.736 s；role drain +11.925 s；complete +12.195 s | overall/application/role lifecycle PASS（短程）；finals 10、completes 1、completed_sessions=1；late-wall mean/median 1075.569/1072 ms，lag slope +91.41086 ms/audio-sec；不采用，生产保留 encoder allow0 |
| CPU4 + role bridge stages + ASR4 prepack | [stages](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4RoleBridgeStagesScreen120/role-bridge-stages-analysis.json) / [HAP 5947824500ec26ac0bfbad62c8eca8ef44b4c30d4eb52386321a3e1208a45ec5 / comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4RoleBridgeStagesScreen120/role-bridge-vs-baseline-scalar-comparison.json) | 111 | 1072 ms | 626.195 ms | 真实 tail +1.760 s；role drain +9.480 s；complete +9.745 s | overall/application/role lifecycle PASS（短程）；finals 10、completes 1、completed_sessions=1；完整 native pipeline 计时 0 条/INCONCLUSIVE；local-only late wall mean/median 1063.824/1063 ms，lag slope +77.432851 ms/audio-sec；不证明 1 秒 hop 稳态 |
| CPU4 + native PCM16 + ASR4 prepack | [pipeline stages](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PrepackScreen120/role-bridge-stages-analysis.json) / [HAP 2d9b209a1e8e7b3fbec8f428dfa089487542b18f1cd7efd40badec66c8cb1751 / 三方 comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PrepackScreen120/native-pcm16-prepack-vs-bridge-vs-scalar-comparison.json) | 111 | 993 ms | 585.470 ms | finish backlog 0；ASR stop exit +1.761 s；role drain 首次/末次 +2.579/+2.673 s；complete +2.842 s | overall/application/role lifecycle PASS（短程）；finals 10、completes 1、completed_sessions=1；pipeline 111 窗匹配；late wall mean/median 1005.706/1027 ms，lag slope +9.035747 ms/audio-sec，26/51 窗超过 1 秒；不证明长时稳态 |

十二个 first encoder profile 都是 `cpuProvider=58`、`xnnProvider=0`。canonical graph 有 36 个 Conv；profile 的 `qlinearConv=108` 是三类 profile event 的重复计数，不是 108 个图 Conv。round3 的应用内线程快照按有效记录观察到 mask `0..3`；XNNPACK arena arm 的 888 条线程记录中 1 条为 unknown，不计入有效 mask 统计，ready-gate、ASR stages、ASR4 prepack、ASR2 prepack 和 active-only spin arm 的无效/unknown 记录也不计入有效样本。旧 shell 采集器的空数组仍无效。因而 `xnnProvider=0` 只能说明本次 canonical INT8 Run 没有 XNNPACK 算子归属，不能说明 XNNPACK provider/allocator 注册没有作用。

CPU1 基线的源码注册 XNNPACK，CPU2-only 与 CPU4-only 候选把 OHOS CPU fallback 改为 2/4 并关闭 spinning，同时撤掉了 XNNPACK 注册。恢复 XNNPACK arena 的 CPU4 arm、Runtime ready-gate 的 CPU4 arm、ASR stages 的 CPU4 arm 以及同 HAP 的 ASR4/ASR2 prepack arm 则回到两平台注册 provider、保留 OHOS CPU budget + `spin0`；ASR4 只改变 prepack，ASR2 只把 ASR threads 从 4 改为 2。CPU-only 与 CPU1 的比较因此同时改变了 CPU budget 与 provider/allocator；这些 arm 只验证 canonical INT8 CPU execution path，不能据此宣称任意 FP32 buffer 已在设备上验收。prepack 短程 PASS 仍不能替代长期/热验收，ready-gate 与 ASR stages 未消除主要 ASR backlog，ASR2 不采用。

CPU4 cursor arm 在 `ts=1790894861586` 同时记录 role `local-finish`（spoolEndSamples=1920000）和 `asr-request-finish processed=1427200`，差值为 492800 samples，即 30.8 秒真实 ASR backlog；旧 observed-spool 约 30.14 秒只是下界。载体结束前没有 `asr-stop-enter/exit`，所以该现场已定位为 ASR accept/dispatcher backlog 尚未排空，尚未进入 stop，而不是 stop 内部耗时。最后一个进度只到 processed=1760000；这与未出现 stop 边界一致。

XNNPACK arena restore arm 在同样的 finish cursor 上仍是 `processed=1427200` 对 `spoolEndSamples=1920000`，同样没有 tail 或 stop enter/exit；它把 native 111 窗 drain 缩短到 `finish +10.095 s`。报告的 `diarization_lifecycle.status=PASS` 对应 `completed_sessions=0`，该子项尚未覆盖完成会话；native 排空另由 `local-drained` + 111 窗事件证明，不能把该 PASS 当作公共角色生命周期或身份通过，也不能把 1078 ms median 当作 1 秒稳态达标。

Runtime ready-gate arm 在 `local-finish` 后 1 ms 收到 ASR request，原始 `processed=1457920` 对 `spoolEndSamples=1920000`，差值为 462080 samples，即 28.880 秒；不能沿用旧派生数字。它同样没有 tail 或 stop enter/exit，native 111 窗 drain 为 `finish +10.122 s`，说明省去空 decode 任务没有消除主要 backlog。其 lifecycle `PASS` 也只是 `completed_sessions=0` 的空覆盖，native 排空仍由 `local-drained` + 111 窗事件证明。它与 XNNPACK arena arm 的 111 个共同窗口在四字段 hash 全部匹配。

ASR stages arm 的累计音频区间为 110 s：`acceptPcmFloatNowAsyncWallMs=140509 ms`，普通 `drainAsync` 的 `decodeAsyncNativeDurationMs=118032 ms`，约占 accept wall 的 84%；对应 `decodeAsyncAwaitWallMs=118308 ms`，await 与该 worker 内 native wall 的算术残差为 276 ms，`confirmVadEndpointAsyncWallMs=9892 ms`。这里的 native duration 是 worker 内 wall，含抢占，不是 CPU time，也不是全部 ASR native 成本；276 ms 是 await residual，也不等同纯 NAPI queue time。当前测量只支持把这段 measured await/NAPI/回调残差限定为主要 accept wall 来源之外的较小部分，未分解 native 计算、OS 抢占或 ORT 内部等待。该臂的 `loadedAsrThreads=4`、`disablePrepack=true`、`providerDisablePrepacking=true`、`providerSpinningDisabled=true`、`providerCpuIdsPresent=true`，speaker VAD 与 target speaker 均为 false；stage quality 的所有问题数组均为空。110 s 期间仍无 stop、tail 或 complete，整体仍 FAIL。

ASR4 prepack arm 与 ASR stages arm 同 HAP、只增加 `--asr-enable-prepack`；同刻 finish cursor 为 `processed=spoolEndSamples=1920000`，ASR backlog 为 0。真实 ASR tail 为 `+1.800 s`，role drain 为 `+7.590 s`，complete 为 `+7.877 s`；tail/complete 相对 `barrier-begin`，drain 相对同刻的 `local-finish`。短程 overall/application 与 `diarization_lifecycle` 均 PASS，`completed_sessions=1`，唯一 last 后唯一 complete，角色未降级。输入起点≥60 s 的 51 个 late windows 的 wall mean/median 为 `1042.784/1053 ms`；`lateLagSlopeMsPerAudioSec=+58.306878` 表示角色处理滞后随音频进度增长的斜率。35/51 窗 wall 超过 1 秒，因此不能把此次短程 PASS 写成持续 1 秒 hop 实时或长时热通过。

ASR2 prepack arm 只把同一 HAP 的 ASR threads 从 4 改为 2；finish 时同样 `processed=spoolEndSamples=1920000`，application、唯一 last/complete 和 role lifecycle PASS，`completed_sessions=1`。overall FAIL 及其 RSS/thread growth advisory 保留。其 51 个 late windows 的 wall mean/median 为 `1069/1064 ms`，`lateLagSlopeMsPerAudioSec=+72.1819`，38/51 窗 wall 超过 1 秒；真实 tail 为 `+1.846 s`，role drain 为 `+10.616 s`，complete 为 `+10.878 s`，时序起点与第八臂相同。角色晚段处理和收尾均未改善，本轮不采用 ASR2。

同输入阶段对照见第八臂的 [scalar comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrPrepackScreen120/prepack-vs-baseline-scalar-comparison.json)。对齐到基线的 110 s 音频后，ASR stages → ASR4 prepack 的 `acceptPcmFloatNowAsyncWallMs` 为 `140509→98829 ms`，普通 drain 的 `decodeAsyncNativeDurationMs` 为 `118032→78547 ms`，`decodeAsyncAwaitWallMs` 为 `118308→78957 ms`，await residual 为 `276→410 ms`，confirm wall 为 `9892→6951 ms`。不把基线 110 s 累计量与 prepack 完整 120 s 累计量直接作差。第八、九臂的 `disablePrepack=false`、`providerDisablePrepacking=false`、`providerSpinningDisabled=true`、`providerCpuIdsPresent=true`，实际加载 ASR 线程分别为 4/2；speaker VAD 与 target speaker 均为 false，阶段质量摘要未报告问题。上述 native duration 与 residual 沿用 worker wall 和算术残差的语义，不能当作 CPU time 或纯队列时间。

资源数字按第八臂的 [scalar comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrPrepackScreen120/prepack-vs-baseline-scalar-comparison.json) 与第九臂的 [scalar comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4Asr2PrepackScreen120/asr2-vs-asr4-prepack-scalar-comparison.json) 原值列出；RSS/HWM 单位沿用摘要的 kB，CPU 为进程累计 CPU 秒：

| arm | 末次 elapsed（s） | 末次 CPU（s） | max RSS（kB） | max HWM（kB） | 末次 RSS（kB） | max threads |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ASR stages（prepack 关闭） | 160.131 | 421 | 567312 | 577164 | 227484 | 82 |
| ASR4 prepack | 140.117 | 349 | 732872 | 965212 | 237496 | 84 |
| ASR2 prepack | 140.136 | 346 | 772936 | 1003464 | 218560 | 80 |

第九臂摘要另记录接近 120 s 时的 CPU：ASR4 prepack 为 `316 CPU-s / 120.097 s`，ASR2 prepack 为 `307 CPU-s / 120.116 s`。末次累计量包含不同的运行、收尾与采样区间，不能当作相同工作量的节能百分比；采样 max RSS 与进程 HWM 也不是同一指标。ASR2 的累计 CPU 和最大线程数较低，同时 max RSS/HWM 更高、角色滞后和收尾更慢，不能据前两项覆盖原始 overall FAIL，也不能推出泄漏或长时热结论。

70/101/111 个共同窗口的哈希分别在各自对照中全部一致；CPU4 cursor、XNNPACK arena restore、Runtime ready-gate 与 ASR stages 的 111 个共同窗口在 `segmentsHash`、`embeddingsHash`、`runEmbeddingsHash`、`runRangesHash` 四字段均无 mismatch，其中 ASR stages arm 与 ready-gate arm 的对比见 [hash comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrStagesScreen120/asr-stages-baseline-vs-ready-gate-hash-comparison.json)。ASR4 prepack 与 ASR stages 的 111 窗四字段也全部匹配，详见 [prepack comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4AsrPrepackScreen120/prepack-vs-baseline-scalar-comparison.json)；ASR2 prepack 与 ASR4 prepack 的四字段同样全部匹配，详见 [ASR2 comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4Asr2PrepackScreen120/asr2-vs-asr4-prepack-scalar-comparison.json)。它们只能说明对应 arm 的输入/窗口结果保持一致，不能把不同 arm 拼成身份精度真值门禁。前七个 arm FAIL，第八、十、十一、十二臂仅短程 PASS，第九臂 overall FAIL；第十臂不采用，生产保留 encoder allow0。短时 shell 温度不能替代长时热验收。

public ASR text/time 的补充证据见 [text boundary summary](../../.cache/speaker-screen-repro-acf477c2/round3-probe/asr-text-boundary-evidence-summary.json)：baseline 与 ASR4 prepack 各有 1 个 `resultHex`，公开结果文本确已保存；prepack 的 `speakerWindowsHex` 还含公开 `rawText`/`text` 及起止时间，`speakerTurnsHex` 也有起止时间。baseline 为 9 finals、prepack 为 10 finals，覆盖的完成结果不同，不能单凭整体 result hash 不同判为识别或身份精度退化，也不能宣称文本等价。`reportDirectFields` 的 Core `rawText`/`text`/`tokens`/`tokenTimesMs`/`timestamps`/`beginTime`/`endTime` 未直接采集；baseline 的对应 speaker-window 文本与边界缺失，因而没有可比的 Core tokens/时间边界或 speaker-window boundary hash。旧 scalar comparison 的 `asrDigestAvailability=missing` 仅反映标量 probe 的字段范围，不代表所有公开文本都不存在。

ORT 1.16.3 的 XNNPACK preferred allocator 使用默认 `use_arena=true`（见 [xnnpack_execution_provider.cc](../../third_party/.derived/onnxruntime-ohos-1.16.3-46e19ecaf56f/source/onnxruntime/core/providers/xnnpack/xnnpack_execution_provider.cc#L153) 与 [allocator_utils.h](../../third_party/.derived/onnxruntime-ohos-1.16.3-46e19ecaf56f/source/onnxruntime/core/framework/allocator_utils.h#L17)）；`SessionState` 按 `OrtDevice` 保留先注册 EP 的 allocator（见 [session_state.cc](../../third_party/.derived/onnxruntime-ohos-1.16.3-46e19ecaf56f/source/onnxruntime/core/framework/session_state.cc#L95)）。`loadCommunityDiarization` 的 buffer 契约只接收裸 `Uint8Array`，没有 dtype 字段，不能用字节字符串猜模型类型或无条件丢掉 XNNPACK。

另一个独立方向是 [`Runtime.ets` 的 `drainAsync`](../../asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets#L1878) ready 预检：在 `decodeAsync` 前先确认 recognizer ready，同时保留全部 `processDecodedResultAsync` 与 endpoint 路径。Runtime ready-gate arm 已运行但仍 FAIL，未消除主要 ASR backlog；不能把它与 XNNPACK arena arm 的 native drain 结果混为同一通过证据。

[formal regression summary](../../.cache/formal-regression-20261002/formal-regression-summary.json) 为 PASS：clean host regression 共 111 tests，Android native build 为 PASS，适用源码身份以摘要的 `source_identity` 为准。完整 54 探针 cleanup 已归档；冻结 HAP 与对照摘要保留为上述实验构建的证据。该回归摘要记录 `harmony_final_package_built=false`。prepack 默认策略及后续 clean 构建/API23 的限定结果见下文；身份精度与匹配设备长时热验收仍待完成，host/native 回归不能替代这些门禁。

第十臂 encoder active-only bounded spin 已完成，native SHA-256 为 `f91417b203dfa3d61fe2820b72160aa6d4c525e7cd5c0d716c9a2ab63723a537`；它以第八臂 ASR4 prepack 为基线，仅改变 encoder `allow_spin=1/force_stop=1`。短程虽 PASS，但 late-wall mean 从 `1042.784` 增至 `1075.569 ms`，lag slope 从 `+58.306878` 增至 `+91.41086 ms/audio-sec`，complete 从 `+7.877` 延至 `+12.195 s`，因此不采用，生产保留 encoder `allow_spinning=0`。对照的 111 窗四字段 hash 全部一致，`resultHex` 与 `speakerTurnsHex` 相同；`speakerWindowsHex` 整体 hash 不同，不把已比字段的一致性外推为完整精度验收，详见该臂 [comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4ActiveSpinPrepackScreen120/active-spin-vs-baseline-scalar-comparison.json)。

该 comparison 的 terminal CPU 为第十臂 `354 CPU-s / 140.098 s`、第八臂 `349 CPU-s / 140.117 s`，是完整该段的原始累计值，不能证明热稳定。`postNativeCpuSamples.status=INCONCLUSIVE`：初版误把首个有 CPU 值的样本（`elapsedSec=10.004`）作为零点，错移约 10 秒，且 device `Date.now` 与 host telemetry/CPU 时钟没有可靠校准。`initialPostNativeCpuSamplesSuperseded.status=SUPERSEDED` 明确废弃初版推导，仅保留审计；不得据其计算 endpoint 后 CPU 覆盖或增量，也不能扣除 baseline 后把任何区间判为 idle。该更正不否定上述完整区间 terminal 累计值。

第十一臂 role bridge stages 已完成，native SHA-256 为 `a7f427252f9a167b4c7e705656e69bcbb7ce5ee9b421df68cb8fd1a1ad54ffbf`，与第八臂的 111 窗四字段 hash 全部一致。完整 native pipeline 计时为 0 条、合并拆解为 INCONCLUSIVE：两份原始日志各有 `TEMP_PROCESS=111/TEMP_PIPELINE=0`，冻结二进制包含后者字符串；新增日志的 `LOG_INFO/domain=0x6666` 与既有 `LOG_WARN/domain=0` 不同，是可疑原因，尚未完全证实，详见 [bridge comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4RoleBridgeStagesScreen120/role-bridge-vs-baseline-scalar-comparison.json)。

[bridge stages analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4RoleBridgeStagesScreen120/role-bridge-stages-analysis.json) 的 local-only 111 窗、输入起点≥60 s 的 late 51 窗有效。late wall mean/median 为 `1063.824/1063 ms`，read 为 `44/43 ms`；segmentation/feature/embedding mean 分别为 `377.344/12.359/604.517 ms`；`localWall−read−native stages` 未分解 residual mean/median 为 `25.604/2.259 ms`，不能命名为队列、算子或 spinning 耗时。角色 lag slope 为 `+77.432851 ms/audio-sec`，第八臂为 `+58.306878`，不能宣称 1 秒 hop 稳态达标。

该臂 complete 后有 4 次同 PID 的有效 CPU 读取，counter 为 `352→352 CPU-s`，实际采样间隔界限为 `29820..30343 ms`，CPU 计数分辨率为 `1 CPU-s`。只能说约 30 秒未观察到 counter 增加，界限不是精确连续区间；`nativeStaticProven=false`，不证明 native 静止或热验收通过，也不改变第十臂的 INCONCLUSIVE。

生产源码的 prepack 默认策略已实施：`RecognitionConfig` 仅 long 默认 `disablePrepack=false`，short/prepare/Core 仍为 `true`，显式 engine boolean 优先。[production validation](../../.cache/speaker-screen-repro-acf477c2/round3-probe/long-prepack-policy-staging/production-validation.json) 记录 35 项相关 host PASS；[demo/doc closure](../../.cache/speaker-screen-repro-acf477c2/round3-probe/long-prepack-policy-staging/demo-doc-closure/closure-validation.json) 记录 31 项 host 检查及 10 个真实 demo 方法的 host 交叉检查 PASS。既有显式配置设备臂不验证新的省略键默认路径及其初始化成本，当前来源仍非最终验收。

同步 PCM16 helper 已写入四个产品源文件，[host summary](../../.cache/speaker-screen-repro-acf477c2/round3-probe/native-pcm16-helper-host-828/host-summary.json) 记录 63 项 host PASS。初始 Node addon 因 TeamID 不符加载失败单独保留；后续 host 验证使用实际生产 CPP 的 N-API shim 与 helper host。新增 Harmony 真机证据由以下第十二臂提供，不能把较早的 host/formal regression 自动扩展到后续源码或最终验收。

第十二臂为配置正确的 `armProbeCpu4NativePcm16PrepackScreen120`，native SHA-256 为 `9d5194e75fa4d9dfcbac33ad9f342ac00ad6b900ae6269a0435cbc69017e78cb`。显式 `--asr-enable-prepack` 对应 `disablePrepack=false/providerDisablePrepacking=false`，实际 ASR threads 为 4；短程 overall/application/role lifecycle PASS。第十一臂作为 readWindow 直接基线，第八臂作为原 scalar 基线，详见 [PCM16 三方 comparison](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PrepackScreen120/native-pcm16-prepack-vs-bridge-vs-scalar-comparison.json)。输入起点≥60 s 的 51 窗中，相对第十一臂，read mean/median 从 `44/43` 降至 `2.333/2 ms`，wall 从 `1063.824/1063` 降至 `1005.706/1027 ms`，lag slope 从 `+77.432851` 降至 `+9.035747 ms/audio-sec`；第八臂对应 wall 为 `1042.784/1053 ms`、slope 为 `+58.306878`。新臂仍有 26/51 窗 wall 超过 1 秒且 lag slope 为正，整段 wall median `993 ms` 不能证明长时 1 秒 hop 稳态。

[PCM16 bridge analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PrepackScreen120/role-bridge-stages-analysis.json) 从 app-hilog fallback 恢复 111 条 `TEMP_PIPELINE`，parse errors 为 0，与 111 条 local/TEMP_PROCESS 窗口全部匹配；probe-events 中的 pipeline 计数仍为 0。late queue/worker/callback/resultBuild mean 分别为 `0.271/989.790/12.197/0.119 ms`，local/worker residual mean 为 `0.996/11.369 ms`，均保持 wall 与未分解残差的语义。全部窗口中的两条负 local residual 约为 `−0.050/−0.005 ms`，对应起点 samples `880000/1312000`，原值与符号保留、不截断；`Date.now` 毫秒计时与 native 计时精度不同，不能把这些残差改称 spinning 或纯 CPU 成本。第十一臂仍无可比较的完整 pipeline 拆解。

该臂 finish backlog 为 0；相对 local-finish，ASR stop exit 为 `+1.761 s`，首次/末次 role drain 为 `+2.579/+2.673 s`，complete 为 `+2.842 s`。complete 后 4 次同 PID CPU 读取为 `342→342 CPU-s`，device 采样间隔界限为 `29694..30264 ms`、分辨率为 `1 CPU-s`；仅是约 30 秒未观察到 counter 增长，不能证明 native 静止或热验收。

第十二臂对第八、十一臂的 111 窗四个原生 hash 均全部一致；`resultHex`、`speakerTurnsHex`、`speakerDiarizationMessageHex` 也相同。`speakerWindowsHex` 的[脱敏字段对照](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PrepackScreen120/speaker-windows-diff-analysis.json) 确认三臂各有 1 个 session 级 window，唯一差异字段是 `inferenceMs` 与 `rtf`；`speakerIndex`、`secondarySpeakerIndexes`、`confidence`、`overlap`、`speakerInferred`、text span 身份及 text hash 均无差异，本轮输入对应的最终冻结身份保持一致。该一致性不替代带身份真值的精度验收。

Harmony 诊断候选构建 exit 0，八个源码已按当前含 helper 的 clean 快照恢复，见 [clean restoration](../../.cache/speaker-screen-repro-acf477c2/round3-probe/candidate-cpu4-native-pcm16-transaction/clean-restoration.json)；两个 HAR 与同身份 HAP 已[冻结](../../.cache/speaker-screen-repro-acf477c2/round3-probe/candidate-cpu4-native-pcm16-transaction/artifact-freeze.json)。Android `externalNativeBuildRelease` 也为 PASS（exit 0、7.884 s），四源 before/after hash 一致，见 [Android build result](../../.cache/speaker-screen-repro-acf477c2/round3-probe/native-pcm16-helper-host-828/android-native-release-20261002T055049Z/result.json)。后续 clean 构建、限定的 API23 检查及省略键短程观察已完成，见下文；其初始化成本与长时热验收仍未闭环，不能把该显式配置诊断候选写成最终生产验收。

此前 `armProbeCpu4NativePcm16Screen120` 漏传 prepack 开关，实际 `disablePrepack/providerDisablePrepacking=true`，已由独立 [protocol deviation](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16Screen120/protocol-deviation.json) 标记 `ABORTED_SETUP_MISMATCH_ASR_PREPACK`。原 report 的 overall/application FAIL 保留；进程 exit 0 不改变该失败，也不能把该臂计入上述十二臂有效对照。

### 后续 clean 构建与 SDK 默认观察

`clean-acceptance-01-build` 的[构建状态](../../.cache/speaker-screen-repro-acf477c2/round3-probe/clean-acceptance-build-prep/clean-acceptance-01-build/status.json) 为 BUILD_COMPLETE、exit 0；[源码核对](../../.cache/speaker-screen-repro-acf477c2/round3-probe/clean-acceptance-build-prep/clean-acceptance-01-build/clean-restoration.json) 确认八源 before/after 一致、匹配当前 clean，临时 markers 全无，无需恢复操作。[冻结身份](../../.cache/speaker-screen-repro-acf477c2/round3-probe/clean-acceptance-build-prep/clean-acceptance-01-build/build-identity.json) 保留 native/bytecode PCM16 helper，ASR HAR SHA-256 为 `8be587bf52fd37522af7ae1dfb5e28873d0ced2500f54fa7caa5e355446f05ac`，DQ HAR 为 `273287756da6ce72bab7b318a4bfe894338d68df125dd5dfed901703b854450c`，clean HAP 为 `7a9ba768e5fe85f359eb94ac4c82abeb1f8b5e51274b72db961a5e668edbe20e`。

后续 [API23 summary](../../.cache/speaker-screen-repro-acf477c2/round3-probe/clean-acceptance-build-prep/clean-acceptance-01-build/api23-summary.json) 记录两份 HAR 的检查均 PASS、exit 0；[编译器身份](../../.cache/speaker-screen-repro-acf477c2/round3-probe/clean-acceptance-build-prep/clean-acceptance-01-build/api23-compiler-version.json) 确认为真实 API23 SDK `6.1.0.31`、bytecode `13.0.1.0`。通过范围是 ASR 21 个、DQ 27 个非声明 TS 文件，不扩大为 `.ets` 或 Windows 全覆盖，也不将构建/API23 通过当作设备或产品验收。

省略键短程观察另见 [SDK default observation](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16SdkDefaultScreen120/sdk-default-observation.json)：`armProbeCpu4NativePcm16SdkDefaultScreen120` 使用诊断 HAP `0e3d9fb456962b71c24cf4db93c947d1ff2289cb9190ef357879f367fd92a165`，与上述 clean HAP 分别绑定证据。配置来源为 `SDK_MODE_DEFAULT`，runner 记录 `asrDisablePrepack=null`（省略 SDK 配置键）；[实际阶段标志](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16SdkDefaultScreen120/asr-stages-analysis.json) 为 `disablePrepack=false/providerDisablePrepacking=false/loadedAsrThreads=4`。application/lifecycle PASS、completed_sessions=1；与第八、十一、十二臂的 111 窗四个原生 hash 全等，公开 result/turn/message 摘要相同，已脱敏的公开窗口字段差异仅为 `inferenceMs/rtf`、身份字段无差异，不替代身份真值验收。

该省略键臂的 late 51 窗 wall mean/median 为 `1036.157/1032 ms`，lag slope 为 `+43.627602 ms/audio-sec`，31/51 窗超过 1 秒，仍不支持长时 1 秒 hop 稳态。没有独立初始化计时字段；只能直接记录 application `129035 ms`、cycle `127644 ms`、角色推理聚合 `112490.192 ms`，不能用这些时长或排空时长之差冒充 init 成本。按本次 report 口径，peak RSS/HWM 为 `734.508/742.598 MB`，排除 18 个 warmup samples 后 RSS growth 为 `5.293 MB`，仅说明本次资源观测。

该臂 complete 后只有 3 次同 PID 有效 CPU 读取，counter 为 `343→343 CPU-s`，device 采样间隔界限 `19711..20283 ms`、分辨率 `1 CPU-s`；只能说约 20 秒未观察到增长，不能写成 30 秒，也不证明 native 静止或热稳定。后续 600 秒 clean 包运行已完成但 overall/lifecycle FAIL，见下文；发热与息屏变慢仍未取得整体 PASS。

<a id="2026-10-02-clean600-fail"></a>
### clean 包 600 秒验证失败

生产 clean HAP `7a9ba768…` 的实际运行 `armCleanCpu4NativePcm16SdkDefaultScreen600TailManifest`（job933）已完整 collect、exit 0，无 host timeout；[probe analysis](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armCleanCpu4NativePcm16SdkDefaultScreen600TailManifest/probe-analysis.json) 的 root overall 与 role lifecycle 均为 FAIL。application PASS（50 finals、1 complete、0 errors、liveStreams=0），输入为 600 s、fedFrames=30000；角色结果 degraded，`FINISH_TIMEOUT` 的 reason 值为 4，既有 15 s 收尾超时保持不变。`inferenceMs=596205.014`、`RTF=0.993675` 是累计角色计算字段及其比值，不是端到端吞吐或 1 秒 hop 稳态证据。

[五个公开窗口的身份摘要](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armCleanCpu4NativePcm16SdkDefaultScreen600TailManifest/clean600-window-identity-summary.json) 显示：`0–101.3/101.3–221.3/221.3–341.3 s` 三窗均报告 2 个角色；`341.3–461.3 s` 首现 ID 2、报告数增至 3；`461.3–600 s` 最后窗 degraded、speaker turns 为 0、身份标记全为 `-1`。[标注状态](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armCleanCpu4NativePcm16SdkDefaultScreen600TailManifest/clean600-annotation-status.json) 为 NO_EXACT_IDENTITY_ANNOTATION_FOUND：120 s 的两角色输出不是人工真值，没有同一 600 s 输入的身份标注，三角色仅记为输出差异，身份精度未验收。

[温度与频率摘要](../../.cache/speaker-screen-repro-acf477c2/round3-probe/native-pcm16-600-preparation/job933-thermal-frequency/analysis.json) 的 131 个温度点记录 shell_back `33.175–35.728°C`、system_h `33.105–36.388°C`、Battery `32–35°C`。采样原点不是输入原点，最后 60 秒可能包含完成后观察；这些范围及频率回落不能用于宣称热 PASS、热稳态或温度导致降频。

此前 job928 缺少 parser 必需的 tail manifest、实际输入 0 frames，已单独保留为 [SETUP_FAIL_TAIL_MANIFEST_REQUIRED](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armCleanCpu4NativePcm16SdkDefaultScreen600/protocol-deviation.json)，不计作 SDK 失败；933 使用包含新 600 s source hash 映射的 [tail manifest](../../.cache/speaker-screen-repro-acf477c2/round3-probe/native-pcm16-600-preparation/clean-600-tail-manifest.json)，沿用既有尾部断言。后续已有 `0e3d9fb4…` 诊断包的 job960 已完成同一 600 s 输入观察，overall/role 仍 FAIL，详见 [933/960 分阶段对照](../../.cache/speaker-screen-repro-acf477c2/round3-probe/comparison-933-vs-960.json)；此处 960 是 job 编号，不是原始 960 秒输入。两个用户可见问题仍未完成。

<a id="2026-10-02-mutex-split600-pool-affinity"></a>
### 分锁 600 秒仍失败；构造期 affinity 已取得短程观察

分锁 clean HAP `7bf7bb7ad9b6dddec5ef846071f38a96982fead90ee10a9b3f62e1661569f53e` 的 job1008 已完成，[运行摘要](../../.cache/speaker-screen-repro-acf477c2/round3-probe/mutex-split-clean600-summary.json) 保留 overall FAIL、角色 `FINISH_TIMEOUT`（reason=4）。输入 30000 frames，application PASS：50 finals、唯一 last/complete、0 errors、liveStreams=0；公开 last、角色结果、complete 距 finish 分别为 `19263/19264/19265 ms`，不把 ASR 收尾通过改写为角色或整体验收通过，15 秒角色等待规则未放宽。

六个公开窗口中，前四窗与 933 已比身份/结构字段一致（不含文本及 `inferenceMs/rtf`）；window 4（`461300–581300 ms`）首次出现 ID 3、报告角色数为 4；最终 `581300–600000 ms` 窗 degraded、turns=0、身份全为 `-1`。同一输入没有 exact human/MOSS 身份标注，只记录输出差异，不据此判定 identity regression 或身份精度 PASS。

`inferenceMs=646676.502`、`RTF=1.077794` 不代表输入吞吐：[Session 累加三个 native stage](../../asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization/SpeakerDiarizationSession.ets#L261)，再累加[聚类调用外层 elapsed](../../asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization/SpeakerDiarizationSession.ets#L409)。分锁时这些区间可以重叠，累计值不能直接用于吞吐比较或证明 1 秒 hop 稳态。

[1008 温频分析](../../.cache/speaker-screen-repro-acf477c2/round3-probe/mutex-split-clean600-thermal-frequency/job1008/analysis-unanchored.json) 保留独立采样原点：132 个温度点、133 个频率点；shell_back/system_h/Battery 首点为 `32.087/32.3/31°C`，分别比 933 低 `1.191/0.805/1°C`。没有可靠输入/完成锚定，末 60 秒不等于音频末 60 秒，不能据较低温度判定热收益、热 PASS 或降频根因。

[CPU 阶段更正](../../.cache/speaker-screen-repro-acf477c2/round3-probe/post-summary-cpu-observation.json) 将 933、job960、1008 的 post-summary 均保留为 `MISSING_PUBLIC_SUMMARY_LOG_ANCHOR`；文件 mtime 不是公开完成事件的设备时间/PID 锚点。这三个 600 s 运行中只有 job960 有有效 `barrier-complete` 锚定：3 次同 PID 读取，在 `19730..20302 ms` 区间观察到 `0 CPU-s` 增长，分辨率为 `1 CPU-s`；不证明 native 静止。933/1008 也缺少该 barrier 事件，不能补写完成后 CPU PASS。

失败分锁的两处 hunk 已撤销，Process/Cluster 恢复共用 `inference_mutex_`，源码 `86d66399…→2918f57a…`。新 OHOS 构造期 affinity 候选源码为 `315181910cb98eb207eb46e7485d1492fd1524222829b37945fcceb642cbac31`：保留 copied policy 和 RAII scope，只让 OHOS 构造 Session/provider 时保留 CPU IDs，返回或异常后恢复借用 driver；非 OHOS 仍走原清空分支。范围见[候选说明](../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-affinity-candidate/README.md)、[候选差异](../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-affinity-candidate/candidate.patch)与[来源记录](../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-affinity-candidate/clear-origin.md)。真实 constructor + scope 的 host 回归在旧 `2918` 上 5 个显式请求场景失败，新候选 7 场景全过，4 项最小 host 检查 PASS；Android Model 预处理逐字节相同、SHA 为 `f0c5261d858ace48b7ee824d20cafe77cec7a5f7f25caa4b21de9c1b503e6a8a`。这些证据不替代实际 ORT workers、Android 构建或设备验收。

job960 的[线程归属分析](../../.cache/speaker-screen-repro-acf477c2/round3-probe/thread-affinity-analysis-960.json) 仍为 INCONCLUSIVE：全进程快照不能归属为 segmentation/encoder/ASR owned pool；[旧 ProbeProcess 调用点](../../.cache/speaker-screen-repro-acf477c2/round3-probe/candidate-cpu4-native-pcm16-build/probe-sources/community_diarization.cpp#L802) 位于 scheduling scope 仍存活的窗口末端，并非 after-return 恢复采样。源码已证明构造前丢弃显式请求的机制，尚未证明该机制就是设备慢因，也不能把 observed mask 当成系统 cpuset 上限。

job1044 的[构建状态](../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-affinity-diagnostic-build-prep/pool-affinity-diagnostic-01-build/status.json) 为 BUILD_COMPLETE/exit 0，[八源恢复](../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-affinity-diagnostic-build-prep/clean-restoration.json) PASS、恢复到 `3151819…`。[冻结 HAP](../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-affinity-diagnostic-build-prep/pool-affinity-diagnostic-01-build/build-identity.json) 为 `6ecf07c94af5f886b462724fce76e53cd1b27cc5b13825fe9caf05082803a26c`，属于 DIAGNOSTIC；[构建事务](../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-affinity-diagnostic-build-prep/transaction-result.json) 不含设备或 API23 验收。1049/1059 两次 120 s 诊断已 collect；旧 `7bf…` 构建的 [API23 PASS](../../.cache/speaker-screen-repro-acf477c2/round3-probe/mutex-split-clean-acceptance-build-prep/mutex-split-clean-acceptance-01-build/api23-summary.json) 不覆盖 `3151819…` 候选，诊断短程结果也不是新 clean/API23 验收。

[1049 默认 QoS 分析](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PoolAffinitySdkDefaultScreen120/pool-affinity-analysis.json) 为 overall/application/role lifecycle 短程 PASS、cleanup PASS；完整 CPU 请求到达 native，构造期 requested `4..11`、effective `4..7`（adjusted）。随后 Process scope 仍出现 `errno=22/effective=0..3`，一窗同 TID 的 mask 在 scope 内从 `4` 变为 `0..3`。首 encoder profile 确认 3 个 worker 有执行活动、recent core 样本覆盖 `0..4`；它们是执行样本而非完整 affinity mask，profile thread ID 与 proc/TID 的 owned 映射仍 UNKNOWN。111 窗四个原生 hash 与已比旧 PCM16 臂一致，不能由此证明身份真值或 owned pool 已按请求绑定。

[1059 QoS 分析](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PoolAffinityInitiatedScreen120/pool-affinity-qos-analysis.json) 和[运行核对](../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16PoolAffinityInitiatedScreen120/qos-arm-validation.json) 确认：同一冻结 HAP `6ecf07…`、native `4bc43fad…`、同一输入，命令/配置唯一差异为 QoS `default→user-initiated`，overall/application/role lifecycle 短程 PASS、cleanup PASS。native 7/7 次 Get→Set→Get 成功，requested/effective QoS 均为 `3`、status 为 applied；CPU 请求仍是 3 次 adjusted 加 4 次 `EINVAL/0..3`，未消除原 affinity 模式。对 1049 的 111 窗四个原生 hash 全同，公开 result/turns/message 全同，window identity projection 相同；不把整个 `speakerWindowsHex` 当作逐字节相同。

按输入起点 ≥60 s 的后 51 窗口径，1059 的 wall mean 为 `981.902 ms`、native 三阶段均值之和为 `946.064 ms`，lag mean/slope 为 `386.824 ms / +0.042624 ms/audio-sec`，观察 queue=0，公开 finish→complete 为 `2165 ms`；1049 对应 wall mean `1023.275 ms`、lag mean/slope `3411.98 ms / +27.101719 ms/audio-sec`、finish→complete `4987 ms`。这些是短程观察，不能归为 QoS 的唯一因果、1 秒 hop 长稳或热 PASS；本次未长跑，owned-pool 归属与设备慢因仍未解决。

<a id="2026-10-02-ahc-memo-clean7038"></a>
### clean 7038 的 600 秒 FAIL；原 960 秒暂停

前一阶段单次 `Ahc` 的局部 pair-score memo 已实现，header 为 `1c07657d…`，当时 CPP `3151819…` 不变，见[实现与 host 证据](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/ahc-pair-memo-candidate/README.md>)及[结果摘要](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/ahc-pair-memo-candidate/results.json>)。只复用原 distance 对未变化 pair 的重复算术结果，首次计算顺序及树/tie/fit 逻辑保持不变；host 的 merge、centroid、height double bits 与 labels 对旧 Ahc 等价，10 项及最终 3 项检查 PASS，独立复核无 blocker。score 预算为 16 MiB，加 O(N) slot；N2048 真实启用，额外 live payload `25426496 bytes < 32 MiB`，原 host 门槛未放宽。N>2048 回到原路径，AHC 仍可有 O(N³) 标量扫描；计算次数减少不等于设备提速。

1104 / `2ac2…` 新诊断包的[最终分析](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16AhcMemoInitiatedScreen120/ahc-memo-analysis-final.json>)与[运行后核对](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/armProbeCpu4NativePcm16AhcMemoInitiatedScreen120/post-run-validation.json>) 为短 120 s PASS、cleanup PASS，job 已 collect/exit 0。真实 24 次 fit 的 N 为 `2..159`，hit/raw 为 `15090/193252`，AHC 合计 `179.824 ms`；111 窗四 hash 与 1049/1059 全同，公开身份投影相同。后 51 窗 native/wall mean 为 `949.242/977.216 ms`，queue=0、lag slope 为 `+2.380724 ms/audio-sec`，finish→complete 为 `2253 ms`，没有一致的端到端收益。与 1059 运行参数和输入相同，但二进制同时包含 memo、聚合探针与 CF0 载体变化；QoS 6/6 读回 3，affinity 仍有 4 次 errno=22，不据此断言 owned mask。

1125 所用历史 clean 产物为 HAP `7038…`、native `eabc…`；下列构建/API23 证据仅绑定该阶段。[执行摘要](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/ahc-pair-memo-clean-acceptance-build-prep/ahc-pair-memo-clean-acceptance-01-build/execution-summary.json>)记录 1116/1118 均已 collect/exit 0；[完整性核对](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/ahc-pair-memo-clean-acceptance-build-prep/ahc-pair-memo-clean-acceptance-01-build/post-build-integrity.json>)为九源精确 clean、无 probe，两个 HAR 和 HAP 均以 0444 冻结；[新 HAR API23](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/ahc-pair-memo-clean-acceptance-build-prep/ahc-pair-memo-clean-acceptance-01-build/api23-summary.json>)对 21/27 份非声明 TS PASS。Android job1086 已实际 compile/link 并依赖 `1c07657d…` header，PASS；这些属于构建与指定检查证据，尚非产品验收。

1049/1059 的旧诊断 HAP 载体仍绑定 `5feee61f…`；[CF0 的最初静态核对](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/complete-epoch-static-validation.json>)保留当时 PASS_STATIC_ONLY。后续 1104 已真实包含 CF0，设备 result/report 的 `completeAtEpochMs` 一致，减去 `2253 ms` 与设备 barrier-begin 一致，见上述最终分析；它表示 publicComplete，不是 native ack。旧温度/频率没有 device epoch，不能用新字段修复 1008 的 UNANCHORED。新版[device-clock collectors](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/device-clock-collectors/README.md>)的 15 项 fake PASS 是前期准备证据；1125 已实际使用新增时钟完成采集，有效查询及其边界见下。

<a id="clean7038-job1125-600-fail"></a>
1125 的 clean `7038…` / native `eabc…` 600 s 已完成并全部收集，[公开验收摘要](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/armCleanCpu4NativePcm16AhcMemoInitiatedScreen600/public-acceptance-summary.json>)为 overall/role lifecycle FAIL（reason=4）：30000 frames、50 finals、唯一 last/complete、errors=0、liveStreams=0，application/tail PASS；公开 last/role/complete 距 finish 为 `16642/16643/16645 ms`。[身份、收集与 cleanup 核对](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/armCleanCpu4NativePcm16AhcMemoInitiatedScreen600/post-run-validation-final.json>) PASS、owner collect/exit 0，均不覆盖产品 FAIL；1125 运行前后产物与九源未变；后续源码优化见下。

[失败阶段补充](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/armCleanCpu4NativePcm16AhcMemoInitiatedScreen600/role-failure-phase-supplement-final.json>)确认前四个公开窗口非降级，最后 `461.3–600 s` 的 11 条 utterance primary 及 11 个 span 均为 `-1`、secondary 为空、turns=0。591 是期望的 native Process 窗数，实际完成覆盖与 internal ASR tail/drain 时序均 UNKNOWN；不能由 `RTF=0.995441639`、五个公开窗口或 finish→last 反推 native 已完成、已排空或精确 tail 时刻。

[1125 温频/CPU 最终分析](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/job1125-analysis/analysis-final.md>)及[标量摘要](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/job1125-analysis/summary-scalars.json>)记录新版时钟的 thermal 130 / frequency 131 条有效查询。频率含 12 核，查询区间 median 为 `3.067 s`，不是瞬时同步读数。实采首点 shell_back/system_h/Battery 为 `32.160/32.150/30°C`，shell/system 最大值为 `34.639/35.315°C`；finish 前 120 s 的描述性斜率为 `+0.217/+0.151°C/min`，不构成热稳态。旧 1008 初温不匹配、UNANCHORED 保留，不能作热收益因果比较。

post20 同 PID 的整秒 CPU 为 `1759→1759`，两端对应实际 wall 跨度界 `20.394–20.964 s`；首次查询到公开 complete 后 `8.191 s` 才开始，无法覆盖此前空档。1 CPU-s 分辨率的零增量不能证明亚秒 CPU 为零或 native 静止；publicComplete 仍不是 native ack。

1125 的 `continuous=true` 经 [EndpointRulePolicy 默认模式](<../../asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/EndpointRulePolicy.ts#L25>)进入 long，SDK-default 省略 `disablePrepack` 经 [RecognitionConfig](<../../asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RecognitionConfig.ets#L134>)实际为 false；本次失败不能归为 short/prepack 错配。普通 Demo 未启用 continuous 且未显式指定 mode 时仍默认 short，两者不同。

原 960 s 验证仍暂停；总体、热、身份真值、离线与界面覆盖仍未验收，canonical INT8、1 秒 hop 及 ASR 生命周期边界不变。

<a id="accepted-label-reuse-pooling-build"></a>
后续 AHC accepted-label reuse 已实现，header 为 `47f59d9d…`，见[host 阶段说明](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/accepted-training-ahc-reuse-candidate/README.md>)及[结果索引](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/accepted-training-ahc-reuse-candidate/results.json>)。18 项有效 host 检查通过，green-01 的原始整体 FAIL 保留，两个 mutant 均触发预期断言，敏感性验证通过。它增加 O(N) 的已接受 train 完整标签，在可复用时省去最终重复 fit；原 Ahc 函数块不变，不把 isolated AHC 的 32 MiB 门槛扩大为整个 Cluster 的内存承诺。

pooling 合并已实现于 CPP `a145c440…`；[host 检查](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/pooling-pack-candidate/test-run.json>)为 1 个 unittest、6 条成功与 3 条拒绝路径，实际编译执行 production fragment，并对 `run_embeddings/run_rms/run_ranges` 全字段作 memcmp。111 窗 host 绑定对照的 pool 调用数 `230→188` 仅说明调用工作量，不能换算为设备提速。

Android1198 与 Harmony1200 平台 build PASS，均 exit 0，见[Android 结果](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-pack-ahc-reuse-diagnostic-build-prep/android-native-release-01/result.json>)及[最终构建完整性](<../../.cache/speaker-screen-repro-acf477c2/round3-probe/pool-pack-ahc-reuse-diagnostic-build-prep/pool-pack-ahc-reuse-diagnostic-01-build/post-build-integrity.json>)。reader 已 exit 0 并完成归档，当前新诊断 HAP/native 为 `34a4c246…/f7eb3f02…`，最终状态 `PASS_NOT_DEVICE_ACCEPTED`；device/API23/clean release 均为 `NOT_RUN_NOT_AUTHORIZED`，旧 7038 的 API23 PASS 不覆盖此包。两项优化已实现并经 host、平台构建验证，真机收益与产品验收待定，1125 的 `FAIL_FINISH_TIMEOUT4` 仍未解除。

原始[960 秒输入绑定](../../.cache/speaker-screen-repro-acf477c2/input-aligned-identity.json)的 WAV SHA 为 `66133c62a0f6da69d2b98d96a5d193816e73899fa28340313beb146309c9167d`；[600 秒构造清单](../../.cache/speaker-screen-repro-acf477c2/corpus-native-pcm16-600/manifest.json) 则是 SHA `37649ba9…` 的 120 秒切片重复 5 次，目标 SHA 为 `8a646530a502fb81463f0a582cef0b974d296acf63a08dd4ed6a254e4aa03b42`。两者非等价，即使后续 600 秒通过，也仍须按[原验收约定](DIARIZATION_CANCELLATION_20261001.md#L58)验证同一签名产物的原 960 秒息屏输入；历史 960 FAIL 保留。[取消记录第 44 行](DIARIZATION_CANCELLATION_20261001.md#L44) 的 HAR gate 未运行及编译器 skip 是当时状态，历史 skip 不回写为 PASS；上述后续构建证据分别绑定各自产物。身份精度、离线边界、实际 worker 调度、1 秒 hop 与长时热验收仍未完成。

## 当前 INT8：先核对实际执行器，再选择预算

Harmony canonical encoder SHA-256 为 `368629e9bad8277b5249b70eec1879bf293e1be614569c3257fdea937211eedd`，
Android 继续使用 FP32。直接检查 canonical 图得到：

- 原图 36/36 个 Conv 的 activation zero point 为 UINT8、weight zero point 为 INT8、权重 scale 按通道；
  输出量化类型也为 UINT8。第一层 activation zero point 为 140，权重 zero point 均为 0。
- 锁定 ORT 1.16.3 XNNPACK 的
  [Conv 支持检查](../../third_party/.derived/onnxruntime-ohos-1.16.3-46e19ecaf56f/source/onnxruntime/core/providers/xnnpack/nn/conv_base.cc#L218)
  要求 per-channel INT8 权重搭配 INT8 输入/输出，拒绝当前 U8S8 组合。canonical graph 的 36 个 Conv 因而没有 XNNPACK 算子归属；round3 first-run profile 的 `xnnProvider=0` 与此一致。
- CPU fallback 使用 ORT operator thread pool；round3 CPU-only 候选分别把 OHOS encoder budget 设为 2/4 并关闭 spinning，CPU1 基线则保留 CPU fallback 1 与 XNNPACK budget 4。由于候选还改变了 XNNPACK provider/allocator 注册，不能把这组结果解释为纯预算差分。
- 当前正式保留方向是 OHOS `SetIntraOpNumThreads(encoder_threads)` + `session.intra_op.allow_spinning=0`，Android CPU fallback 保持 1，并在 `#endif` 后两平台都注册 XNNPACK budget；这同时保留 FP32 from-buffer 兼容与既有 allocator 路径。XNNPACK arena restore、Runtime ready-gate 和 ASR stages arm 都已运行但仍 FAIL；ASR4 prepack 只有短程 PASS，不能替代长期/热验收；ASR2 不采用。


主机最小试验使用 ORT 1.16.3、ONNX 1.15.0、NumPy 1.26.4、macOS arm64：相同 8 个现有 eval 输入，
CPU EP intra-op 1/4、其它选项一致并关闭 spinning，8 组 `[1,2560,125]` 编码输出全部位级一致，最大绝对误差为 0。
再用单线程 FP32 pooling 和每窗 5 种代表性 mask，40 组 embedding 也全部位级一致、最大绝对误差为 0。
本地[脚本](../../.cache/encoder-cpu-parity-review-20261001/verify.py)和
[报告](../../.cache/encoder-cpu-parity-review-20261001/report.json)记录了输入/模型哈希与逐项比较。

主机 wheel 没有 XNNPACK provider，因此这里的 8+40 项主机等价试验不提供手机 XNNPACK profiling；手机 round3 的 first-run provider profile 见上表及各 arm 报告。合成 mask 的等价也不是身份精度门禁。
主机耗时不用于预测 Harmony wall time 或热量。后续候选应分别验证 Harmony INT8 的 CPU 预算和 Android FP32 的
XNNPACK 路径，不能无条件增加两个计算线程池。CPU 并行可能缩短 encoder wall time，也可能增加与 ASR 的竞争。

另一个限制是观测归属：已复核的 8 个旧 Release 臂所有有 PID 的逐线程样本都是 `threads=[]`，不能据此证明
worker mask 相同、全部绑核或空闲；外部 `/proc/<pid>/status` 只给 leader 当前亲和性，不是所有线程或系统 cpuset 上限。
round3 改用应用内有界只读采样，十二个 arm 的有效线程快照均观察到 `0..3`；XNNPACK arena arm 的 1 条 unknown、ready-gate、ASR stages、ASR4 prepack、ASR2 prepack 和 active-only spin arm 的无效/unknown 记录均不计入有效样本，但这仍不是系统上限证明；
细节见[息屏采样专题](DIARIZATION_SCREEN_OFF_CPUSET_20260930.md)。

## 历史 FP32：早先“可回收 0.73 CPU-s/墙钟秒”的推断作废

早先把 FP32 1 线程臂的 CPU 当作“有用计算的上限”，推算 4 线程有 0.73 CPU-s/墙钟秒的并行开销可回收。
复查发现两个 1 线程臂都发生角色降级，工作量不同，该算式无效：

| 历史 FP32 臂 | overall | diarization_lifecycle | 失败原因 |
| --- | --- | --- | --- |
| XNNPACK 1 线程（旧代码，Diagnostics） | FAIL | FAIL | `cycle 0: degraded speaker result` |
| XNNPACK 1 线程（新代码，Diagnostics） | FAIL | FAIL | `cycle 0: degraded speaker result` |
| XNNPACK 2 线程（Release / Diagnostics，亮屏） | PASS | PASS | — |
| XNNPACK 4 线程（Release / Diagnostics，亮屏） | PASS | PASS | — |

角色降级后停止处理窗口，较低 CPU 不能解释为完成相同工作更省。只看 `sdk=PASS` 而忽略角色判定也是错误的。
旧 1 线程臂还出现 `embeddingMs` 最大 5476 ms、中位 440 ms；这支持当时配置不稳定，不能外推当前 INT8 CPU
单线程或其它设备。现有 INT8 CPU1 与这些 FP32 XNNPACK1 是不同执行路径。

## 历史 FP32 亮屏线程对照

同台 Mate 80（`VYG-AL30` / OpenHarmony-6.1.1.120）、同一 HAP、同一 120 秒派生会议切片，实时 20 ms 喂入。
ASR 为 `cpuIds=[4..11] spinning=false numThreads=4`。CPU 来自 `ps -o TIME -p <pid>` 的进程累计值，1 秒分辨率。

| 历史 FP32 臂 | 判定 | CPU-s/墙钟秒 | 相对角色关闭 | embeddingMs 中位 |
| --- | --- | ---: | ---: | ---: |
| 角色关闭 | PASS | 0.850 | — | — |
| 角色开启，XNNPACK 4 线程 | PASS | 2.641 | +1.791 | 429 |
| 角色开启，XNNPACK 2 线程 | PASS | 2.348 | +1.499 | 408 |
| 角色开启，XNNPACK 1 线程 | FAIL（降级） | 1.908 | 不可比 | 440（max 5476） |

2 线程比 4 线程低约 0.29 CPU-s/墙钟秒，该次单窗耗时没有变差。它说明当时增加 worker 没有带来观测到的速度收益，
但没有内存带宽、调度或同步的直接测量，不能据此断言 encoder 已经内存带宽受限。

## 历史 FP32 idle-spin 补丁：未观察到收益

上游 pthreadpool 在阻塞前有较长的 yield/spin 阶段；仓库原有 worker-spin 补丁只覆盖 ORT 自身线程池。
将 XNNPACK pthreadpool 的 spin 常量约束到 4096 后，旧 FP32 对照结果如下：

| 历史 FP32 臂 | CPU-s/墙钟秒 | embeddingMs 中位 |
| --- | ---: | ---: |
| XNNPACK 4 线程，约束前 | 2.641 | 429 |
| XNNPACK 4 线程，约束后 | 2.675 | 419 |

该轮没有观察到 CPU 下降，不能支持保留补丁；补丁已撤回，恢复的库与修复前逐位一致。
这只否定了该次改法的可测收益，不证明全部 CPU 差异都不是空转，也不排除当前 ORT CPU 线程池的 spinning、同步或争用。

## 历史 FP32 的阶段成本

窗口长度为 10 秒、hop 为 1 秒；以下按单窗统计，并把当时约每 10 窗一次的预览聚类耗时分摊。
不是“每 10 秒才处理一个窗口”。

| 阶段 | 亮屏（120 s 切片，Diagnostics） | 息屏（960 s 长跑，Diagnostics） | 占比（亮屏 / 息屏） |
| --- | ---: | ---: | ---: |
| segmentation | 117 ms | 405 ms | 19% / 15% |
| Fbank | 22 ms | 82 ms | 4% / 3% |
| encoder + pooling | 419 ms | 2000 ms | 70% / 76% |
| 聚类（预览分摊） | 约 44 ms | 约 160 ms | 7% / 6% |
| 合计 | 约 602 ms | 约 2647 ms | 100% |

这些是不同输入时长下的历史阶段 wall time，包含抢占/调度等待，不能视为纯 CPU 算量的精确分解。
它们支持优先检查旧 encoder 成本，不支持“有意义的优化只能换模型”或把该比例套到当前 INT8 Release。
单线程 Fbank 变慢也不能排除来自其它线程的 CPU 争用。

同一旧长跑的预览聚类曾从 438 ms 增到 2338 ms，提示历史长度相关成本；要归因收尾超时，仍须结合实际
队列游标、真实 ASR tail、角色排空与聚类完成时间，不能只看累计 RTF。

## 历史 FP32 Release 对照与参数解析修复

用相同运行代码、关闭 Diagnostics 的构建重测同一 120 秒切片和亮屏条件：

| 历史臂 | CPU-s/墙钟秒 | 相对角色关闭参照的差值 |
| --- | ---: | ---: |
| 角色关闭（Diagnostics 参照） | 0.850 | — |
| Release FP32 XNNPACK t=4 | 2.491 | +1.641 |
| Release FP32 XNNPACK t=2 | 2.149 | +1.300 |

两个 Release 开启臂之间相差 0.342 CPU-s/墙钟秒（约 14%），两臂通过相关生命周期检查。
角色关闭参照来自 Diagnostics，因此表中开/关差值不能单独精确归因于 Release 的角色增量。
这里测的是 CPU 记账，不是直接测得 14% 的功率或长时温度下降。

当时还修复了 `SpeakerDiarizationConfig.numThreads` 参数解析：原生 `Queue()` 仅在参数个数正好 2/6 时读取预算，
但 ArkTS 追加调度串后传入 3/7 个，导致退回默认 4。提交 `b94e53d3` 修复并增加了行为测试。
它证明预算能传到 XNNPACK，不能证明后来切换的 INT8 图也在该执行器上计算。

## 历史 per-tensor INT8：性能收益不抵消身份翻转

主机 ORT 1.16.3 的静态 QDQ per-tensor 试验使用 21 个校准窗和后段互不重叠的 8 个评测窗，
经生产 Fbank、encoder 与全窗 mask 的 FP32 pooling 比较；以下仅是当时的候选记录：

| 指标 | 历史结果 |
| --- | ---: |
| 余弦相似度 | 0.9881–0.9925，中位 0.9911 |
| 相对 L2 偏移 | 12.3%–15.4%，中位 13.4% |
| 模型体积 | 21.3 MB→约 5.4 MB |
| 主机单窗耗时 | 213.5→98.0 ms；不能映射到手机性能 |
| 设备亮屏单窗耗时 | 427→315 ms |
| 设备亮屏整进程 CPU | 2.665→1.474 CPU-s/墙钟秒 |

相对 L2 与余弦是不同量，不能把 `1-cosine` 直接表述为角度百分比。更关键的是后续真实输出差分，
而不是仅靠向量相似度判断是否影响身份。

当时将 INT8 内容临时放入 FP32 文件名的资源位置，使用相同 120 秒切片和 HAP 配置、亮屏、配置 encoderThreads=4。
FP32 和 INT8 的实际执行器不应据这个相同配置值视为相同：

| 模型 | 历史臂 | segmentationMs | featureMs | embeddingMs | CPU-s/墙钟秒 |
| --- | --- | ---: | ---: | ---: | ---: |
| FP32 | `armFp32T4`（23:22:08） | 102 | 25 | 427 | 2.665 |
| per-tensor INT8 | `armInt8T4`（23:17:04） | 101 | 25 | 315 | 1.474 |

对号以设备 run 为准：`run-1790781731584` 是 FP32，`run-1790781427437` 是 INT8。
早先引用另一条 `run-1790778923526` 的 478 ms 作为该 INT8 臂结果，是错误的，已撤回。
这两个亮屏臂不能推出息屏 RTF 0.7，也不能把与角色关闭不同构建的差值称为已可回收的固定 CPU 量。

120 秒差分中，两臂的 111 窗、25 个公开说话人轮、107747 ms 轮总时长、20 个句级标签与每窗人数相同。
这只证明该输入中比较过的字段一致，不能代表全部角色内部状态或精度。

扩大到 360 秒派生切片（历史摘要 SHA-256 前缀 `c0bee0e75f082def…`）后，两臂都有 351 窗、4 个公开结果、
39 个相同的句级标签和 69 个说话人轮，但第 42 轮不同：同一 `213077.84–213482.84 ms` 区间约 405 ms，
FP32 判为说话人 1，per-tensor INT8 判为说话人 0，轮总时长仍为 319557 ms。
因此该 per-tensor 候选不能满足“不改变身份结果”的目标，120 秒一致性没有覆盖这一反例。

## 历史 per-channel INT8：360 秒差分一致，仍保留精度门禁

改为 per-channel 权重、非对称激活后，同样 21/8 窗主机测量中，余弦中位从 0.9911 提高到 0.9980，
相对 L2 中位从 13.4% 降到 6.29%。这仍不是相对 FP32 的数值等价。

| 历史比较 | FP32 | per-tensor INT8 | per-channel INT8 |
| --- | ---: | ---: | ---: |
| 360 秒窗数 / 公开结果 | 351 / 4 | 351 / 4 | 351 / 4 |
| 说话人轮 | 69 | 69，第 42 项翻转 | 69，逐项相同 |
| 句级角色标签 | 39 | 39，相同 | 39，相同 |
| 轮总时长 | 319557 ms | 319557 ms | 319557 ms |
| 已记录亮屏 embeddingMs 中位 | 427 | 315 | 314 |
| 已记录亮屏整进程 CPU | 2.665 | 1.474 | 1.595 |

这支持保留 per-channel 候选，但不证明在所有输入、设备或并发调度下身份等价，也不意味着模型已获发布资格。
Harmony 已接入 canonical INT8 及哈希/复现参数，Android 保持 FP32；正式身份门禁仍要分别比对带身份真值的误认、
同人换号、UNKNOWN 与重叠，并验证同 HAP 的长时息屏性能及生命周期。

## 历史 FP32 息屏反例的适用边界

下表为旧 FP32 XNNPACK 线程预算、960 秒语料、真实麦克风载体的记录，不能当作当前 INT8 CPU 线程选择：

| 历史臂 | XNNPACK 线程 | overall | diarization_lifecycle | 角色状态 |
| --- | ---: | --- | --- | --- |
| `armProductScreenOff` | 4 | FAIL | PASS，`completed_sessions=1` | RTF 0.962，未降级，2 位说话人 |
| `armProdT2ScreenOff` | 2 | FAIL | FAIL | `cycle 0: degraded speaker result` |

4 线程臂整体仍失败，2 线程臂存在角色降级；不能写成二者只有收尾等待不同，也不能笼统声称降级前整场从未输出角色更新。
它们不支持将旧 FP32 默认降为 2，但也不证明 INT8 CPU2 不可用或 CPU4 已有效。
主线程息屏 mask 为 `0..3` 不足以证明所有 worker 都受同样限制，更不能仅凭编号确认 CPU 拓扑。

`Session.inferenceMs` 包含 native 阶段 wall time 与可能带排队/mutex 等待的聚类 elapsed。
`RTF=0.962` 不能推出 38 秒积压；`RTF=1.1038` 也不能替代输入/处理游标和收尾时序。
公开 last 被角色 barrier 暂存，公开 finals 数量不能单独区分 ASR tail 缺失与角色等待。

## 当前失败边界与后续比较

已明确安装的 Release HAP `f0fa26aeb69c3faaf9ee292e5ca1ec96928de2a550640adc0f49ec08f7cbff10` 在受控 120 秒臂中
公共 ASR `finals=10/completes=1`，但角色 `speakerCount=0/degraded=1/reason=4 (FINISH_TIMEOUT)`、RTF 1.1038，整体 FAIL。
同轮 shell-back 约 `30.8→31.8°C` 只是短时轨迹，不能与历史长跑 41.4°C 直接比较或宣称已降温。
该记录不是后续修复的最终 HAP 或验收完成状态，完整边界见[汇总记录](DIARIZATION_ROLE_HEAT_AND_SCREEN_OFF_CONCLUSION_20260930.md)。

下一步应保持 canonical 模型、1 秒 hop、segmentation/pooling、身份冻结、15 秒角色 barrier 与 ASR 契约，
先确认手机实际执行器与处理游标，再单变量修改正确执行器的预算。比较逐窗输出、阶段 wall time、实际线程 CPU 时间、
角色排空和内部 ASR tail；最后分别判定公共生命周期、身份精度与长时热量。不能通过加大 timeout 或删窗转绿，
也不能把旧 FP32 t=2 的约 14% CPU 收益宣传为当前 INT8 的降温方案。

## 历史证据位置

早期 FP32 线程臂保存在 `.cache/speaker-screen-repro-acf477c2/armSlice{RoleOff,T4,T2,T1,T4PoolSpin}/`，
量化派生特征与旧候选保存在 `.cache/speaker-screen-repro-acf477c2/encoder_quant/`。
这些本地目录、原始 PCM 和遥测不进入 Git；历史候选不能覆盖 canonical 模型或冒充当前交付资产。
