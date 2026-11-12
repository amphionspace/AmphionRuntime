# EC521S 持续 ASR 发热：定位与后续验证（2026-11-10）

状态：诊断和修复验证进行中，**尚未完成发热验收**。原始问题是无角色分离的记录仪长时间离线 ASR；本轮不修改 Sortformer，也不将 CPU 时间下降视为温升合格。

## 已确认的问题与最小修复

同样 48,000 个静音样本、相同主 APK、门控关闭：调用方每次提交 320 样本时，首个新 stream 起点为 43,520；每次提交 16,000 样本时，起点为 48,000。两组 public 样本数都完整到达 48,000，generation 都为 1，last/stopped 各 1、error 0。结构回归明确失败，不是超时或丢失输入造成的假象。

原因是 ACTIVE 路径把调用方余下的整块 PCM 先交给 native，再排空 ready decoder 并检查端点。端点换流使用此时的 public 样本时钟，因此换流位置受调用方分块影响。此前门控/非门控的文本比较同时受到这个既有问题干扰。

修复在 native 接收前，将 ACTIVE raw/processed 成对切到下一个 10 ms PCM 边界；16000 Hz 下每个完整边界为 160 样本。更短的现有 deadline 和实际尾帧仍直接处理，public 样本只计数一次。IDLE 20 ms 探针、pre-roll replay、warmup、换流策略及回调调度保持原样。

- [修复源文件](</Users/momo/project/AmphionRuntime/asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt#L596>)：修复前 SHA256 `d503073cbc35d92144ecd2defb0b555d4883b29c652f3780a16dbaefc7c249e4`，修复后 `25e64795e3a5fdfdbb93e292a9e57e57dbd843ec6e000e8d071709789d7bb471`。
- [结构及语音分块回归](</Users/momo/project/AmphionRuntime/asr/android/samples/dingqiao-demo/src/androidTest/java/com/amphion/dingqiao/demo/EncoderIngressPartitionInstrumentedTest.kt>)：比较内部流起点、完整输入计数、文本/时间戳及终止回调；不锁死某个期望起点，不输出转写原文。
- [修复前结构证据](</private/tmp/ec521s-partition-red-58v_idvq/encoder_ingress_partition-1794271640559.jsonl>)：8 行，SHA256 `bf753a17b31e22643ef1a5830778014249de8efb81eb4812dc05def26fa27891`。
- [修复前执行身份](</private/tmp/ec521s-partition-red-58v_idvq/result.json>)：1 test / 1 failure，主包未替换，执行前后 SHA256 均为 `201492970fd0a5278be360859171dfb3c56ce67e4d64006eaacde10c87b74ea2`。

修复后 SDK 单元测试 **119/119 PASS，0 failure/error/skip，共 28 suites**，见[本轮摘要](</private/tmp/encoder-clock-unit-build.XQHJch/unit-summary.json>)和[构建日志](</private/tmp/encoder-clock-unit-build.XQHJch/gradle.log>)。

修复后两项真机分块回归 **2/2 PASS**，见[执行与安装身份](</private/tmp/ec521s-fixed-partition-tk9bkpxs/result.json>)。48,000 个零样本在 320/16000 两种分块下均为 generation=1、streamStartSample=43360、publicSamples=48000；[静音报告](</private/tmp/ec521s-fixed-partition-tk9bkpxs/encoder_ingress_partition-1794273711842.jsonl>)保留原始边界。18.24 秒语音夹具两种分块均为 24 字，文本哈希一致、24 个 token 时间戳逐值一致、publicSamples=291840、final/last/stopped/error=2/1/1/0，见[语音报告](</private/tmp/ec521s-fixed-partition-tk9bkpxs/encoder_ingress_partition-1794273695717.jsonl>)。这证明本次分块缺陷的结构与语音回归通过，不代表门控开关识别精度或热验收通过。

## 一线程诊断：确有计算开销下降，输出也发生变化

复用相同冻结主包、同一 EC521S、同一私有 16 kHz 单声道 PCM16：8,145,600 样本，509.10 秒，SHA256 `02f020ed70554a81deea6b37d77509b7e748b6677e29444ebf981d81d2bb64ac`。此次仅将测试配置中的 numThreads 设为 1；与上一轮相同主包的两线程有效结果比较。两次测试 APK 不同；新增内容为诊断参数、记录线程数及独立分块回归。

| 门控 | 线程 | 进程 CPU 时间 | 加速重放 wall 时间 | 输出字符数 | final / last / stopped / error |
| --- | ---: | ---: | ---: | ---: | --- |
| 关 | 2 | 318.163 s | 168.142 s | 1158 | 21 / 1 / 1 / 0 |
| 关 | 1 | 228.204 s | 221.367 s | 1164 | 21 / 1 / 1 / 0 |
| 开 | 2 | 211.213 s | 113.672 s | 1193 | 20 / 1 / 1 / 0 |
| 开 | 1 | 138.367 s | 133.267 s | 1201 | 18 / 1 / 1 / 0 |

门控关/开两组 CPU 时间分别下降 **28.2745% / 34.4894%**；wall 时间分别增加 31.6548% / 17.2382%，仍快于录音时长。全部输入计数完整，但两种线程数的转写哈希不同；不可据字符数增加判定精度变好。没有默认线程数变更，也没有一线程发热合格结论。

一线程本身的 control/gate 严格文本相等断言仍失败：规范化字符数 1164/1201，LCS 1101，未匹配 63/100，最长未匹配连续段 5/9。该值是两份输出的差异，**不是 CER**。control 不是参考真值。gate entries/resumes=20/20，idleSamples=3,677,440 包含回放，不是净节省样本数。

- [本轮一线程执行身份](</private/tmp/ec521s-old-main-one-thread-iu974wyx/result.json>)。
- [一线程脱敏报告](</private/tmp/ec521s-old-main-one-thread-iu974wyx/encoder_idle_regression-1794271933527.jsonl>)：SHA256 `640f337a126b0c9fea68dc7bc41bfd472daec5d4d7a4663749172c37b5eeb91e`。
- [线程对比计算](</private/tmp/ec521s-old-main-one-thread-iu974wyx/thread-comparison.json>)。
- [复用的两线程报告](</private/tmp/ec521s-old-gate-verification-spikmhrq/historical-common-replay/report-1794264838973.jsonl>)。

这些是加速、固定 control→gate 次序的计算诊断，不是平衡次序的实时输入功耗对比。没有本轮温升数据，不能按 CPU 降幅推算温度降幅。

## 实时与测温资格

独立于 Activity/UI 的实时 instrumentation 与设备采样器已完成统一构建，见[短时资格说明](</Users/momo/project/AmphionRuntime/docs/speaker/ASR_EC521S_THERMAL_QUALIFICATION.md>)。它以单调时钟按 1× 输入精确私有 PCM 窗口，前台服务配有超时的部分唤醒锁；记录 submitted、accepted 和 decoder 已处理样本，跟踪进度滞后、末尾回调与资源清理。取消会先关闭 SDK 接收，唤醒可能阻塞的 PCM 提交者。

[冻结构建身份](</private/tmp/encoder-clock-thermal-build.essIax/apk-identities.json>)：主 APK SHA256 `70b2f6e61e36b76a49f5bc4c8e900215db9417ede4124c2cc212fe81bd5287f0`；测试 APK SHA256 `6ba5428f47cd59ca7b1398f2e26f475a0b45968bca1194d6bca8567d7a2ccbe5`。

首轮使用 direct SDK、空热词 greedy、关闭标点/ITN、long/RULE3 关闭；仅作处理与采样资格。[鼎桥真实配置](</Users/momo/project/AmphionRuntime/asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoEngineConfig.kt#L43>)默认有完整预置热词池、beam/maxActivePaths=8、标点及 ITN，ASR 2 线程。最终产品负载比较应复用 SpeechRecognizeSdk 公共入口，并显式固定无角色的 long、VAD 800 ms、会话轮换等参数；不能把旧热测默认 short/20 秒、每 300 秒轮换并补静音的配置当成相同录音场景。旧热测还会落盘 text_head，不直接复用其客户音频报告路径。

已新增 `thermalBackend=dingqiao`，使用公共 create/start/write/finish/cancel/shutdown，保留默认热词/beam/标点/ITN/两线程，单会话、不补静音。finish 前暂停周期探针，公开 complete 后等待 decoder 线程退出再读取最终计数。新增后端的[测试包构建记录](</private/tmp/dq-thermal-backend-build-pke9e1hh/apk-identities.json>)为 Gradle exit 0；测试 APK SHA256 `cb76348eb4d75dbb3cbf84a9f33a448213425ccc1e9b94bb5a5fe642d6b44a26`，构建前后主 APK SHA256 均保持 `70b2f6e61e36b76a49f5bc4c8e900215db9417ede4124c2cc212fe81bd5287f0`。该后端随后以独立 20 秒真机 run 通过处理与采样短时资格，见下文；仍不代表持续温升通过。

设备端采样器需独立保存 USB、真实电池状态、各温度节点、CPU/线程和频率。要求覆盖开始、结束及中间间隔。0、-127000 或缺失的表面温度视为无效，不使用缓存 SKIN 或电池温度代替客户后壳测点。处理资格和传感器资格分别给结果。

首轮 20 秒插 USB、亮屏的资格冒烟，见[运行摘要](</private/tmp/ec521s-thermal-plugged20s-vjpbfn85/result.json>)，应用为 `PASS_PROCESSING_ONLY`：submitted=accepted=processed=320000，输入 SHA256 对齐；last/stopped/error=1/1/0，末尾 drain 964 ms，最大喂入滞后 10 ms，service/唤醒锁均无残留。最终 CPU 累计 26460 ms（20.992 秒处理窗口），不作为长时功率/温升指标。

同轮采样为 **INVALID_SENSOR_COLLECTION**，见[采样状态](</private/tmp/ec521s-thermal-plugged20s-vjpbfn85/sensors/status.tsv>)：最后一批采样在 513938 秒开始，应用在 513939259 ms 正常完成，采样器随后于 513940 秒读取进程时已退出，触发 PID/线程不可用。此轮必需温度节点有效，但不能将旧 FAIL 改为 PASS；采样器须修复完成边界并用新 run 验证。随后门控及鼎桥回归启动器在 APK 身份查询阶段发现 EC521S 不在 ADB 列表，instrumentation 尚未启动，因此这些项目仍待测，不计作测试失败或通过。

新增鼎桥后端的 20 秒亮屏插线验证已通过，见[独立运行摘要](</private/tmp/ec521s-detached-qualification-845ub3f5/collection-3u8qchdh/result.json>)、[实际配置与应用报告](</private/tmp/ec521s-detached-qualification-845ub3f5/collection-3u8qchdh/app/report.jsonl>)和[采样状态](</private/tmp/ec521s-detached-qualification-845ub3f5/collection-3u8qchdh/sensors/status.tsv>)。本轮通过设备驻留驱动执行；完整输入 320000 samples，submitted=accepted=processed，输入窗口 SHA256 与首轮相同。实际配置为 2 线程、370 条默认热词、modified_beam_search/maxActivePaths=8、标点/ITN 开启、VAD 800 ms、RULE3=-1，无 targetSpeaker/diarization。last/complete/error=1/1/0；最大 feed lag 4 ms，最大 barrier delay 798 ms，最终 backlog=0；drain 1447 ms，decoder join 1 ms。服务及唤醒锁无残留，采样器 exit 0/PASS_SENSOR_COLLECTION_ONLY，CPU 三个样本覆盖至完成前 1649 ms。处理窗口 21.467 秒、CPU 29164 ms，仅作为短时资格数据。该结果不改变首轮 INVALID_SENSOR_COLLECTION；实际拔线后的驻留与传感器可用性仍待验证。

已找到与 11.04 秒短夹具完整哈希绑定的 26 字项目参考：[参考脚本](</Users/momo/project/AmphionRuntime/asr/tools/evaluate_automatic_agc_regression.py#L16>)及[既有回归说明](</Users/momo/project/AmphionRuntime/asr/android/reports/automatic-agc-evaluation/README.md#L69>)。其人工标注来源未获证实，不能外推为长录音的人工真值。[本轮哈希闭合分析](</private/tmp/ec521s-frozen-reference-check-vexj8ss7/result.json>)确认旧主包门控 320/16000 的完整输出均等于参考（26 字，CER=0）；旧 320 对照及修复后主包两种分块的 gate-off 输出均恰好缺参考开头 2 字（CER=2/26）。这些结论由完整 UTF-8 SHA256 闭合，不依赖“对照即真值”，未输出原文，也未重放音频。旧严格 gate/control 文本相等 FAIL 仍保留；长录音识别差异仍待独立评估。当前主包的新增独立参考回归与六项相关契约已于本轮真机执行全部通过：见[7/7 结果及 APK 身份](</private/tmp/ec521s-fixed-reference-contracts-u8iv7lkd/result.json>)和[冻结参考脱敏报告](</private/tmp/ec521s-fixed-reference-contracts-u8iv7lkd/encoder_idle_regression-1794278258710.jsonl>)。320/16000 两种分块均输出完整 26 字参考，26 个时间戳及两条 final 的文本边界完全相同，last/stopped/error=1/1/0；其余覆盖 Rule3 checkpoint、IDLE finish、限定热词替换、cancel、finish 幂等及初始静音结束。主 APK 保持 `70b2f6e61e36b76a49f5bc4c8e900215db9417ede4124c2cc212fe81bd5287f0`，只更新测试 APK 为 `5f108963923de1fe4d5b949719998aa09ecf739ad459ad8eacc6bfd1d9fe95eb`，见[构建冻结身份](</private/tmp/ec521s-reference-test-build-ticizz3q/apk-identities.json>)。新增参考检查独立存在，未删除或放宽既有严格 gate/control 断言。最终测试 APK `ddb7614df56f949cece1b996a8c21c618a41e26fdd076ff4d339e9abf0824100` 已复跑同一组七项，结果仍为 7/7 通过，参考行在 320/16000 两种分块下均为 26 字且与参考 SHA256 一致，见[最终契约结果](</private/tmp/ec521s-final-contracts-upuikicx/result.json>)。

两次实际拔线资格均未通过，原因是本机厂商电源策略而非门控代码：

- 熄屏拔线轮：应用在熄屏后约 50 秒被移入厂商冻结组 `freezer:/Group_0377980845`，同轮 `dumpsys power` 中该 PARTIAL_WAKE_LOCK 已消失（`Wake Locks: size=0`、`mWakeLockSummary=0x0`、`mWakefulness=Asleep`），整机随后挂起。报告双时钟给出量化结果：最后一条就绪记录到结束 `elapsedRealtime` 走过 540.689 秒，`uptimeMillis` 只走 140.558 秒，即约 400 秒挂起。见[冻结快照与电源状态](</private/tmp/ec521s-observer-pull-uywm_g_6/obs/power-s3.txt>)和[双时钟应用报告](</private/tmp/ec521s-detached-qualification-50aeyvg3/collection-u7jx9x6y/app/report.jsonl>)。
- 亮屏拔线轮：未发生挂起（两钟同步走完 305 秒），但应用停止推进并在采集超时后被中止，失败原因为 `feed_clock_late`；说明电池供电时即便亮屏也会被限制，而非仅休眠问题。

因此“拔线 + 后台长时间持续处理”在本机不可实现，除非改动设备电池优化/启动管理策略（属设备设置变更，需另行授权）。这一限制不改变门控本身的有效性；客户 61.9 分钟连续使用更可能与插电或前台可见状态对应，需在产品条件中说明。

插电 + 锁屏条件已通过 120 秒资格：[结果](</private/tmp/ec521s-detached-qualification-so4i__7j/collection-y7ydn3a3/result.json>)为 `PASS_SHORT_QUALIFICATION_ONLY`、采样 `PASS_SENSOR_COLLECTION_ONLY`，13 个 CPU 样本覆盖至完成前 387 ms，submitted=accepted=processed=1920000，CPU 108749 ms / 120.910 秒窗口，最大 feed lag 15 ms、最终 backlog 0，last/stopped/error=1/1/0，电池温度 31.9→32.2 °C。该轮仅证明锁屏插电可持续处理与采样，不代表温升验收。

持续对比固定为“插电 + 锁屏 + 同一已核验 509.10 秒窗口（不循环、不拼接）”，已完成门控开/关各一组。两组使用同一主 APK、同一测试 APK、同一 DSP/热词/beam 配置、2 线程，仅门控不同：

| 指标 | 门控开 | 门控关 |
| --- | --- | --- |
| 处理窗口 | 509.927 s | 509.733 s |
| 进程 CPU | 460.768 s（单核 90.36%） | 674.857 s（单核 132.39%） |
| 每秒音频 CPU | 0.904 核·秒 | 1.324 核·秒 |
| submitted/accepted/processed | 8144000 全部 | 8144000 全部 |
| 静音门控进入/恢复 | 19 / 19 | 0 / 0 |
| 最大喂入滞后 | 9 ms | 11 ms |
| 起点 前壳/后壳 | 30.68 / 37.81 °C | 30.80 / 37.76 °C |
| 前壳温升 | **+1.85 °C** | +4.85 °C |
| 后壳温升 | **+0.59 °C** | +1.29 °C |
| 边框温升 | **+3.09 °C** | +6.44 °C |
| CPU 区温升（峰值） | **+5.35 °C（12.93）** | +8.58 °C（19.63） |
| AP 温升 | **+6.0 °C** | +10.0 °C |
| PMIC 温升 | **+6.10 °C** | +9.96 °C |
| 充电区温升 | **+4.0 °C** | +10.0 °C |

两组均为 `PASS_SHORT_QUALIFICATION_ONLY` 且采样 `PASS_SENSOR_COLLECTION_ONLY`：门控开见[结果](</private/tmp/ec521s-detached-qualification-zmr8uqmy/collection-4s1agqs4/result.json>)，门控关见[结果](</private/tmp/ec521s-detached-qualification-ktmjcjpp/collection-i954focf/result.json>)，对比汇总见[对比 JSON](</private/tmp/ec521s-detached-qualification-zmr8uqmy/sustained-comparison.json>)。两组前壳/后壳起点相差不超过 0.12 °C，可直接比较温升。

同条件 CPU 下降 **31.72%**（每秒音频 1.324 → 0.904 核·秒），前壳温升减少 **3.01 °C**、边框减少 **3.35 °C**、AP 减少 **4.0 °C**、PMIC 减少 **3.86 °C**、CPU 区减少 **3.23 °C**。门控开组 19 次进入/恢复静音门控且输出与完整参考一致，说明节流来自静音段跳过而非降低识别质量。

长音频识别差异已量化（不落文本，只记计数）：同一 509.10 秒 PCM、同一主/测试包、SDK 2 线程、control 先跑后跑门控，结果 control 1155 字、门控 1191 字，LCS 匹配 1067 字；control 未匹配 88 字（7.6%，最长连续 6），门控未匹配 124 字（10.4%，最长连续 21）。见[脱敏差异记录](</private/tmp/ec521s-long-audio-gate-vs-control-ks6mscg4/encoder_idle_regression-1794286098681.jsonl>)。该严格相等断言按设计仍为 FAIL，未改写。与历史基线（1158/1193、LCS 1075、83/118）相比差异幅度一致，说明本轮 10 ms 对齐修改未引入额外漂移；同时缺少该 509 秒录音的人工转写，无法判定差异方向，只能确认 11.04 秒参考夹具上门控输出等于完整 26 字参考、对照反而少 2 字。

历史记录：更早一次门控关尝试（`detached-20261110-155059-jw_di8v8`）应用侧跑满但采样器在约 390 秒后由 10 秒退化为 21–23 秒间隔并触发 `sampling_overrun`，被判 `INVALID_SENSOR_COLLECTION`，已保留为失败现场、未改写；其上表数据由重跑的合格组替代。

已有录音不足以覆盖 61.9 分钟；若要做满一小时，必须先明确重复播放或补录策略，不能静默循环。测试工具的 PASS_PROCESSING_ONLY 或 PASS_SENSOR_COLLECTION_ONLY 都不是产品发热验收。

当前判定：相对改善已获同条件真机证据（CPU −31.72%，温升全面更低），识别与公共契约未退化；但“是否达到产品可验收解决状态”仍缺两项外部条件——壳温/温升阈值，以及覆盖 61.9 分钟的音频策略与窗口。

## 客户一小时实测（2026-11-04）与本文数据的对齐

客户报告见[分报告-记录仪离线ASR一小时温升验证-20261104](</Users/momo/project/AmphionRuntime/分报告-记录仪离线ASR一小时温升验证-20261104.md>)。其结论：`com.tdtech.tiassistant 1.1.0.089 zbBwcDebug` 连续 61.9 分钟，背壳 29.97→42.43 °C（**+12.5 °C**）、前壳 +8.5 °C、边框 +7.5 °C、电池 +10.6 °C，Thermal Status 全程 0；进程 CPU 累计 187 分 44 秒 / 61.9 分钟 ≈ **300%**；耗电 265 mAh / 60.4 分钟 ≈ 263 mAh/h、约 1.06 W；全程锁屏，仅每 10 分钟插线约 1 分钟采样。

必须修正上一轮的一个结论：**该平台并非不能在电池供电、锁屏状态下长时间持续处理**——客户应用在同样条件下跑满 61.9 分钟且 CPU 维持 300%。本仓库 Demo 包被厂商冻结组限制是**包级电源管理状态差异**，不能外推为设备客观不可测。

差异已在设备上核实：`com.tdtech.tiassistant`（UID 10055）同时位于 `dumpsys deviceidle whitelist` 的 `system-excidle` 与 `system` 条目，即预置应用的系统级 Doze 白名单；本 Demo `com.amphion.dingqiao.demo`（UID 10069）不在任何白名单条目内。这解释了同一台设备上客户应用可跑满 61.9 分钟、而 Demo 在电池供电后约 50 秒即被冻结并挂起。

若需要在 Demo 上复现客户条件，可用可回退的设备命令把 Demo 加入用户白名单：`adb shell cmd deviceidle whitelist +com.amphion.dingqiao.demo`，测试后以 `-` 前缀移除。该操作修改设备电源策略，必须在获得授权后执行。

两套数据不能直接相减，配置不同：客户为修复前构建，鼎桥 ASR 线程数仍是 4（`DEFAULT_ASR_NUM_THREADS = 4` 属 2026-11-07 提交 `4f6f16a0` 之前的默认值），且整包还包含录音、debug wav 落盘、频繁日志与 FillManager。本文 509 秒组为 2 线程、无录音与 wav 落盘的 SDK 路径，故 90–132% 与 300% 不是同一口径。可比的只有方向与比例。

据此，客户实测的 300% CPU 与 +12.5 °C 背壳温升仍是**修复前基线**；门控与 2 线程修复要落到客户场景，必须用合入后的 SDK 重新构建客户应用并按同一 61.9 分钟协议复测，不能由本文 509 秒数据外推。

另：客户报告 8.1 记录的停止填单 OOM（`AsrPcmWavDebugSession.flushToWav` 一次性 119 MB 拷贝）发生在客户应用自身的 debug wav 逻辑，不在本仓库 SDK 内，未在本文验证。

## 独立参考与产品条件

- [技术指标表](</Users/momo/project/AmphionRuntime/技术指标_场景分级拆分1109.xlsx>)仅只读检索，未发现温度、温升、发热、功耗或 CPU 对应条目；尚未获得明确的产品壳温/温升阈值。
- [既有 MOSS 工作流](</Users/momo/project/AmphionRuntime/delivery/harmony-dingqiao/docs/MOSS_ANNOTATION_WORKFLOW.md>)只给出内部主机名 `amphion-42`。本机 Clash 已确认启用 fake DNS/TUN；此名字当前解析为伪地址。一次无凭证 SSH 探测在服务端版本交换前关闭，尚未进入真实主机认证，不能判为服务端或密钥故障。需要可核实的内部完整地址或既有内网访问路径；没有上传客户音频或修改网络配置。
- 一小时原始客户试验的后壳从 29.97°C 到 42.43°C，约 +12.46°C；前壳共同 T0 下约 +8.50°C。原始表面测点、环境与本次设备内部温度节点不能直接互换。
- 实际拔线、锁屏及固定测温探头需要现场配合。没有物理拔线/有效表面测温数据时，持续温升结论仍不成立。

相关前序证据：[门控已完成检查与限制](</Users/momo/project/AmphionRuntime/docs/speaker/ASR_EC521S_ENCODER_IDLE_GATE_20261110.md>)。
