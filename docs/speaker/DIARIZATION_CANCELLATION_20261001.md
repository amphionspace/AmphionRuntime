# Harmony 角色推理取消与息屏后续修复（2026-10-01）

## 目标与保留项

本轮直接修改 `fix/diarization-role-thread-budget`。保留用户的 per-channel INT8 encoder、默认 `encoderThreads=4` 配置预算、10 秒输入与 1 秒 hop；不改变身份投票、已提交窗口及正常推理数值。INT8 的 CPU 收益值得保留，但它尚未通过身份精度门禁，不能凭亮屏 PASS 宣称息屏性能或发热问题已经解决。

本轮针对超时后 native 仍计算、取消期间加载完成后重新启动工作、清理通知及取消后的 finish timer。原始 960 秒息屏失败继续保留为 FAIL。后续匹配设备 Release 受控 120 秒验收仍为 FAIL；该失败现场继续保留。尾部与取消正确性依赖专门回归和内部状态证据，不能由该 FAIL 证明没有伪造 ASR 尾部或掩盖 role queue。

## 原始证据与因果边界

报告的逐轮数据位于顶层 `cycles[0]`，不是 `application.cycles`。

- 960 秒亮屏：51 条 final，其中 50 条非空；10 个角色结果快照；唯一 complete；`liveStreams=0`。
- 960 秒息屏：19 条非空 final；4 个角色结果快照；角色 `INFERENCE_TIMEOUT`；无 `final-last` / terminal role result / complete；捕获时 `liveStreams=1`。
- `liveStreams` 是 ASR online stream 数量，不是角色 native worker 数量。
- `SpeakerDiarizationFinishBarrier` 必须先得到真实 ASR 尾部才能开启角色收尾超时。证据能确认角色超时与 ASR 尾部未到达同时发生，不能证明前者单独导致后者。
- 进程 leader 的 `Cpus_allowed_list` 收窄与息屏变慢相关，但它只描述 leader 当前 mask；worker 的亲和性和系统有效上限未独立测量，不能从当前 `0,1,2,3` 断言系统无法扩展。
- 首个结果快照 RTF 分别为 `0.418110`（亮屏）和 `0.923631`（息屏），均可从 `cycles[0].speakerWindowsHex` 按 UTF-16BE 解码。息屏四个快照全部 `degraded=true`，累计推理耗时固定为 `385597.338926 ms`，后续 RTF 下降来自音频分母增加，不能当成速度恢复。
- RTF 是累计推理耗时除以当时已写入的音频时长；不能据此计算尾部积压，也不能将不同窗口/构建/统计时段的 RTF 当作匹配 A/B。

原始报告：

- [亮屏 960 秒](../../.cache/speaker-screen-repro-acf477c2/armCurrentInt8Awake960AfterReboot/stress/20261001-025055-continuous-max-duration-b7351d9f/report.json)
- [息屏 960 秒](../../.cache/speaker-screen-repro-acf477c2/armCurrentInt8ScreenOff960Retry2/stress/20261001-031313-continuous-max-duration-e738d906/report.json)

## 修复约束

1. 超时/失败/取消向 native 请求停止；不只结束 ArkTS 的 `Promise.race`。
2. 模型加载迟到时，不再启动已经超时或取消的 process/cluster。
3. 取消只发出停止请求，不能将工作误标为已经退出。等待 process、cluster 和加载都实际结束后，再关闭模型、移除 spool、释放 Runtime lease。
4. 取消后的迟到结果不得发布，旧 finish timer 不得唤起 terminal callback。
5. 不延长超时，不构造假的 ASR `isLast/complete`，不因角色超时丢弃 ASR 已接受的 PCM。
6. ORT/XNNPACK 取消是协作式停止：在算子之间和 CPU 循环检查点观察取消。不能抢占正在执行的单个算子，也不能保证系统冻结或底层算子死锁时的固定退出时延。

## 验证记录

执行器六项新增回归在旧实现全部失败，见本地 `.cache/diarization-cancel-red.log`：超时未停止 native、取消/超时后的迟到加载仍发起推理、并发 process/cluster 取消未接线、降级后仍启动聚类、已关闭时后续清理通知丢失。修复后通过，并保留正常 1 秒 hop/分帧等价、迟到结果抑制、实际退出前禁止释放的相邻检查。

上述回归、构建和失败现场属于 2026-10-01 取消阶段的历史证据，不自动覆盖后续 CPU budget 或 Runtime 异步调度修改；后续进展见[线程开销记录](DIARIZATION_THREAD_OVERHEAD_20260930.md)与[发热/息屏主结论](DIARIZATION_ROLE_HEAT_AND_SCREEN_OFF_CONCLUSION_20260930.md)。

已完成：

- 执行器取消、Runtime 释放、ASR finish/dispatcher 和 INT8 资产相关检查：44 项通过（`.cache/diarization-cancel-adjacent.log`）。
- Session、finish barrier、Community 正常提交与安静 PCM 检查：69 项中 68 项通过、1 项因当时未配置目标 API 23 编译器而跳过（`.cache/diarization-cancel-session-green.log`）。该历史 skip 不改写为 PASS；当前 API23 编译器已准备，但正式最终 HAR gate 尚未运行。
- `amphion_asr` 与 `amphion_dingqiao` release HAR 编译通过；Android arm64 `amphion_diarization_jni` 实际重新编译并链接通过，确认共享 C++ 接口兼容。
- 核验 HAR 内 ArkTS 与 arm64 native 均包含新取消入口，构建模式为 release。包内 INT8 encoder SHA-256 仍为 `368629e9bad8277b5249b70eec1879bf293e1be614569c3257fdea937211eedd`，无 FP32 encoder。产物身份见 `.cache/diarization-cancel-har-identity.json`。

- Native 取消竞态及 wrapper 回归：27 项全通过（旧 Community native 22/22，加新增取消测试 5/5；`.cache/diarization-cancel-native-final.log`）。
- Public Community session contract：16 项全部通过（`.cache/diarization-cancel-public-contract-final.log`），包括中间 boundary 已取走后聚类被取消、真实 ASR 尾部迟到时两句文字仍完整提交，且不会提前发布 terminal result 或释放 lease。

主机检查与构建不替代真机门禁。受控 120 秒息屏验收：真实屏幕状态由 AWAKE 转为 SLEEP，进程有效掩码收窄到 `0,1,2,3`；最终 HAP
`f0fa26aeb69c3faaf9ee292e5ca1ec96928de2a550640adc0f49ec08f7cbff10` 的结果为 `finals=10`、`completes=1`，公共 ASR 生命周期通过，但 role `degraded=1`、`reason=4 (FINISH_TIMEOUT)`、`RTF=1.1038`，整体验收 FAIL。另一次 Release 现场为 `finals=9`、`completes=0`，载体没有 Diagnostics 结构化事件，不能从 public final 数量单独归因 ASR 或 role queue。

结构化 Diagnostics 对照显示：一类现场在真实 `isLast=true` 后仍有 `pendingJobs=1`、`audioDelay=24000`，约 15 秒后 barrier 降级；另一类现场在结束前没有观察到 `isLast`。后续性能修复必须同时保留 `CALLBACK_RESULT.isLast`、末 `DIARIZATION_ASR_PROCESSED`、`DIARIZATION_QUEUE`、`DRAINED`、`COMMUNITY_COMMIT` 和 `PUBLIC_RESULT`，不能以 carrier 的 FAIL 形态推断唯一根因。

## 后续真机验收

先用最短可复现输入确认推理超时/取消后 native 退出、ASR 真实尾部和资源释放，再对同一签名产物验证 960 秒息屏。性能门禁仍要求保留真实换人、短回答、重叠和 1 秒证据密度；需要测实际 worker affinity、ASR 排队/stop 进度和 native 各阶段耗时，才能继续定位 ASR 尾部未完成的位置。

本轮生命周期修复不等同于息屏 RTF 达到 ≤0.7，也不等同于可以发布。
