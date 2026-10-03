# 离线角色分离：发热与息屏变慢的证据边界（2026-09-30，2026-10-02 更新）

本文保留历史 FP32、INT8 实验与已记录的失败现场。两个用户可见问题仍待修复后的匹配设备验收，
不能用构建成功、累计 RTF、短时温度或主机数值等价宣称已经解决。亲和性与采样缺口以
[息屏专题](DIARIZATION_SCREEN_OFF_CPUSET_20260930.md)为准；生命周期边界另见
[取消修复记录](DIARIZATION_CANCELLATION_20261001.md)。

## 已记录的匹配安装 Release 失败现场

设备为 `7GK0226326015655`（Mate 80，OpenHarmony-6.1.1.120）。已明确安装的 Release HAP
`f0fa26aeb69c3faaf9ee292e5ca1ec96928de2a550640adc0f49ec08f7cbff10` 包含 Harmony per-channel INT8 encoder
（SHA-256 `368629e9bad8277b5249b70eec1879bf293e1be614569c3257fdea937211eedd`）。这是一轮既有失败证据，
不是后续修复完成或验收结束的标记。

- 120 秒受控重放得到 `finals=10`、`completes=1`、`errors=0`，公共 ASR 生命周期通过；角色结果为
  `speakerCount=0`、`degraded=1`、`reason=4 (FINISH_TIMEOUT)`，累计 `inferenceMs=132455.2`、`RTF=1.1038`。
  该轮角色与整体判定仍为 FAIL。
- 同轮 shell-back 温度约 `30.8→31.8°C`，观察仅约 158.5 秒，不能与历史 16 分钟的 41.4°C 峰值
  直接比较，也不能替代长时热验收。
- 主线程 `/proc/<pid>/status` 的当前有效亲和性从 AWAKE 的 `0..11` 收窄到 SLEEP 的 `0..3`。
  这不等于测得全部 worker 的掩码或系统 cpuset 上限。
- 其它 barrier、segmentation 或 encoder 预算实验曾出现 `finals=9/completes=0`、无 terminal role result。
  这些 Release 记录缺少内部 `isLast/DIARIZATION_DRAINED` 和逐窗阶段数据；部分实验还改变了 barrier 时长。
  它们不能单独定位 ASR 与角色的最早阻塞，也不能作为线程配置的严格单变量反证。

本地报告为
[该轮 report](../../.cache/speaker-screen-repro-acf477c2/armFinalReleaseSourceBoundScreenToggle120/stress/20261001-151405-continuous-max-duration-3e43309d/report.json)，
屏幕动作与遥测保留在同臂目录。已有 HAP 必须绑定到明确安装记录；`--installed-package` 不会自动安装刚构建的包，
报告中的 bundle/version/签名 fingerprint 也不能代替 HAP 或 native 内容哈希。

## 设备、输入与历史比较范围

设备口径为 Mate 80 `VYG-AL30` / OpenHarmony-6.1.1.120 / `7GK0226326015655`；相关实验的 ASR 配置为
`cpuIds=[4..11] spinning=false numThreads=4`。历史 CPU 统计主要采用 OS `ps -o TIME -p <pid>`，
表示进程累计 CPU 时间，不是各执行器的算子归属。

| 语料 | 用途 | SHA-256 |
| --- | --- | --- |
| [960 秒会议](../../.cache/speaker-screen-repro-acf477c2/corpus-aligned/meeting-960s.wav) | [冻结输入元数据](../../.cache/speaker-screen-repro-acf477c2/input-aligned-identity.json)记录源区间 `513.8–1473.8 s`，配尾清单；历史长臂 | `66133c62a0f6da69d2b98d96a5d193816e73899fa28340313beb146309c9167d` |
| 中段 120 秒派生切片 | 早期 FP32 线程预算短臂，非仓库冻结资产 | `2fc6d548fa3393e19e0e…`（历史摘要中的截断值） |
| [末段 120 秒切片](../../.cache/speaker-screen-repro-acf477c2/corpus-short/meeting-last-120s.wav) | 上述匹配安装 Release 受控失败臂 | `37649ba942eceb58ff655d9efae12590a58bcd24a047ac8f6a90c617ba672eb9` |

不同切片、构建模式、模型和线程执行器的数据不能合并为一组 A/B。历史预算数据详见
[线程专题](DIARIZATION_THREAD_OVERHEAD_20260930.md)。

## 发热：历史 FP32 成本明确，不能排除当前执行器问题

早期 FP32 实验记录了角色关闭时约 30–31°C、角色开启后约 16 分钟达到 shell-back 41.4°C、电池 42°C。
它支持角色链路显著增加持续计算和热负载，不能证明所有发热都来自不可回收的模型算量。

历史同条件亮屏 FP32 线程对照中，encoder XNNPACK 4→2 的进程 CPU 从 2.641 降到 2.348 CPU-s/墙钟秒；
Release 对照从 2.491 降到 2.149，约低 14%，相关生命周期通过。旧 1 线程臂发生降级，工作量不等，
不能把其较低 CPU 当作可回收空间。角色关闭的 0.850 是 Diagnostics 参照；它与 Release 2.491 的差值
1.641 不是严格隔离构建模式后的产品增量。

旧 FP32 阶段数据中 encoder+pooling 占约 70–76%，segmentation 占 15–19%。这些比例是特定历史输入和
配置下的 wall-time 统计，不能直接外推当前 INT8。缩短 XNNPACK idle-spin 的一次实验未观察到 CPU 收益
（2.641→2.675），因此该补丁撤回；这个阴性结果不能排除所有线程同步、争用或 ORT CPU spinning 成本。
“软件层已无空间”“只能换模型”“线程预算是唯一零精度代价的优化”均不是现有证据支持的结论。

## 2026-10-02 round3：性能改善不能解释为纯 CPU 预算收益

round3 十二个 arm 的完整数值主表、冻结 HAP 身份、provider profile、ASR cursor、阶段拆解和 prepack 对照证据集中在[线程专题](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。前七个 arm 全部 FAIL；第八个 ASR4 prepack arm 仅短程 overall/application/role lifecycle PASS，不能外推长期或热通过；第九个 ASR2 prepack arm overall FAIL 且保留 RSS/thread growth advisory，虽然 application 和唯一 last/complete PASS，也不采用。第十臂 encoder active-only bounded spin 短程 PASS，但角色晚段滞后与收尾比第八臂更慢，不采用，生产保留 encoder `allow_spinning=0`。第十一臂 role bridge stages 短程 PASS，111 窗四字段 hash 与第八臂一致；local-only 计时有效，但完整 native pipeline 计时为 0 条/INCONCLUSIVE，不能宣称 1 秒 hop 稳态。第十二臂 native PCM16 + 显式 prepack 短程 PASS，111 窗完整 pipeline 匹配，read 与角色 lag 改善，但晚段仍超过 1 秒且 lag slope 为正。其对第八、十一臂的原生四 hash 和对应冻结身份一致，公开窗口差异仅为 `inferenceMs/rtf`；详情及精度适用范围见同一主表。

对应 arm 的窗口四字段哈希一致，只证明已比较的输出一致，不能拼成身份精度真值门禁。公开结果文本确有 `resultHex`；baseline 与 prepack 的 final 覆盖不同，整体文本 hash 不同不能单独作为精度退化证据。Core tokens/时间边界未直接采集，公开文本与边界的可比范围见[线程专题的文本证据说明](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。

provider profile、canonical graph 计数、wall/embedding 对照、ASR tail 和 role drain 的具体数值统一以线程专题主表为准。CPU1 基线保留 XNNPACK 注册，CPU-only 候选同时改变了 CPU budget 与 provider/allocator，因此性能变化不能写成纯单变量收益。

当前最小正式保留方向是 OHOS `SetIntraOpNumThreads(encoder_threads)` + `session.intra_op.allow_spinning=0`、Android CPU fallback 1，并在 `#endif` 后两平台都注册 XNNPACK budget。ORT 的 preferred allocator 仍须保留，`loadCommunityDiarization` 的 from-buffer 契约没有 dtype 字段，FP32 buffer 兼容不能被 CPU-only 候选意外删掉。XNNPACK arena、Runtime ready-gate 和 ASR stages arm 都已运行但 FAIL；阶段拆解只限制了 measured await residual，未消除主要 backlog。ASR4 prepack 只有短程 PASS，不能替代长期/热验收；ASR2 overall FAIL 且不采用，不能据此宣称发热或息屏问题已解决。

## 量化收益与身份边界

历史模型 A/B 的体积、耗时与输出差分继续保留，但不外推当前锁屏结果：

| 维度 | 历史结果与范围 |
| --- | --- |
| encoder 体积 | 21.3 MB→约 5.4 MB |
| 亮屏设备单窗 encoder | FP32 427 ms，per-channel INT8 314 ms；约 1.36× |
| 亮屏整进程 CPU | FP32 2.665，per-channel INT8 1.595 CPU-s/墙钟秒；约低 40% |
| 整窗 embedding 偏移 | per-channel 相对 L2 中位 6.29%、余弦中位 0.998；并非与 FP32 数值等价 |
| 120 秒 per-tensor 差分 | 该输入上轮次、轮时长、句级标签与每窗人数一致 |
| 360 秒 per-tensor 差分 | 同一 405 ms 区间发生 1 处身份翻转，候选被否决 |
| 360 秒 per-channel 差分 | 该输入的 69 轮、39 标签与轮总时长逐项一致，生命周期通过 |

这些短样本的一致性不保证所有录音的身份结果不变。带身份真值的误认、同人换号、UNKNOWN 和重叠门禁仍需完成；
不能把亮屏 encoder 1.36× 加速换算为锁屏 RTF 0.7，也不能用相对 FP32 的 CPU 下降代替长时温度验收。

## 息屏：当前有效亲和性与逐线程采样缺口

受控动作确认主线程有效掩码变化，并观察到 cgroup 成员路径变化；尚未读取到各目标线程实际的系统有效 CPU 上限。
`sched_getaffinity(0)` 与 `/proc/<pid>/status` 分别描述调用线程与线程组 leader 的当前有效亲和性。
线程可以提交比当前 mask 更宽的请求，再由内核按实际约束接受、裁剪或拒绝。不能将当前 mask 先当成上限，
也不能据它断言“应用无法扩展”“绑核在息屏下必然无效”。CPU 拓扑/capacity 尚未完成核对，本文不把 `0..3`
已经测明为“四个小核”或唯一根因。

已复核的 8 个旧 Release 臂中，逐线程文件所有有 PID 的样本均为 `threads=[]`；其中上述 `f0fa…` 臂共 32 条采样，
31 条有 PID。外部 shell 无权枚举该 Release 应用的 task 目录，旧采集器却把空数组记为 `narrowerCount=0`。
这些旧文件没有有效 worker 亲和性或 CPU-time 证据，不能宣称全部线程已经绑定、全部继承同一 mask，或没有争用。

round3 探针改为应用内有界只读采样；有效线程快照、`0..3` mask 和 unknown/无效记录排除规则统一见[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)，可用于描述实际观察但不能把当前 mask 当成系统 cpuset 上限。

历史 Diagnostics 臂有部分可识别 TID 的有效掩码及请求返回值；它们只证明对应时刻、对应线程，不能替代 round3 Release 探针。
此前“Community 构造时清空 CPU 请求以继承构造线程掩码”是已撤销的 OHOS 选择。构造期 affinity 阶段的 `3151819…` 候选保留 copied policy/RAII scope，在构造 Session/provider 时保留显式 CPU IDs，退出时恢复借用 driver；Process/Cluster 已恢复共用原 `inference_mutex_`，详见[候选与来源记录](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-mutex-split600-pool-affinity)。
之后改变 driver 不会传给已有 worker；QoS 不能笼统当作随 `pthread_create` 一并继承。host 构造边界检查与诊断包构建已通过；1049/1059 的 120 s 观察均短程 PASS，但仍有 adjusted/EINVAL/0..3，owned/proc 映射 UNKNOWN，源码机制和短程指标均不能单独解释设备慢因。
job960（600 s 诊断）的 owned-pool mask 归属仍为 INCONCLUSIVE；旧 `ProbeProcess` 在 scope 仍存活的窗口末端采样，并非 after-return，全进程原始快照不能归属到特定 owned pool，证据见[线程归属分析](../../.cache/speaker-screen-repro-acf477c2/round3-probe/thread-affinity-analysis-960.json)。

旧 FP32 的 segmentation/Fbank/embedding 都曾在息屏后变慢，但 wall time 含抢占与调度等待。
单线程 Fbank 变慢不能排除线程争用；将亮屏 CPU-s/s 乘以 Fbank 变慢倍数，也不能证明息屏必然需要多少核。

## 收尾与累计 RTF 必须分开判定

`Session.inferenceMs` 累加 native 阶段 wall time 和聚类调用外层 elapsed；后者可能含排队、mutex 等待，
并与其它处理区间重叠。RTF 不是处理游标，不能从历史 `RTF=0.962` 算出“960 秒积压 38 秒”，
也不能由 `RTF=1.1038` 单独判断最早阻塞位于哪个阶段。

2026-10-02 的 CPU4 cursor、XNNPACK arena、Runtime ready-gate 和 ASR stages arm 在 role `local-finish` 时均显示 ASR cursor 落后，载体期限内没有
`asr-stop-enter/exit`；ASR4/ASR2 prepack arm 则在 finish 时 ASR backlog 为 0 并进入 tail/complete。具体样本游标、backlog、tail、drain 和阶段时序见[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。CPU1 的 tail 后 barrier timeout、CPU2 的 tail 后未 drain，以及未开启 prepack 的 CPU4 arm 的无 tail 不能用累计 RTF 合并解释。
角色 barrier 只在真实 ASR tail 到达后开始 15 秒等待，公开 last 又会被它暂存；所以 `finals=9/completes=0`
不能单独证明 native ASR 没有生成 tail。应比较输入/ASR/角色的样本游标及真实 tail、DRAINED、聚类和公开完成时间。

早期 `--timeout 900` 小于 960 秒输入的重放不能用于收尾判定；round3 前七个 arm FAIL，第八、十、十一、十二臂仅短程 PASS，第九臂 overall FAIL。不能以延长 timeout、提前 last
或丢弃窗口消除失败表象，短时温度不能替代长时热验收。

## 已否决方案与剩余验证

- 跨窗直接复用已归一化 Fbank/encoder 的历史假设被否决：逐窗去均值与输出网格不对齐破坏等价，见
  [复用专题](DIARIZATION_CROSS_WINDOW_REUSE_FALSIFIED_20260930.md)。这不否定保留逐窗归一化的 raw-Fbank 缓存。
- `numThreads` 参数个数解析缺陷已修复；round3 进一步证明 CPU-only 候选和 CPU1+XNNPACK 基线并非纯预算 A/B，详见[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。当前正式方向保留两平台 XNNPACK 注册、OHOS CPU budget 与 `spin0`，并兼容 FP32 from-buffer；XNNPACK arena、Runtime ready-gate 和 ASR stages arm 均已试验 FAIL，ASR4 prepack 只有短程 PASS，ASR2 overall FAIL 且不采用。
- 前一轮相关主机/native/ArkTS 检查共 146 项：145 项通过、1 项跳过。它们不验证设备吞吐、全部 worker 亲和性或长时热量，也不能自动覆盖后续运行代码改动。
- 本次正式 clean 回归的 host tests 与 Android native build 为 PASS，完整探针 cleanup 已归档；计数、源码身份和摘要链接集中在[线程专题的回归说明](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。第十臂的 `postNativeCpuSamples` 已更正为 `INCONCLUSIVE`，初版零点与跨时钟映射推导已废弃；完整区间 CPU 累计值不能据此解释为 idle 或热稳定，详见同一主表说明。
- 第十一臂完成后约 30 秒未观察到同 PID CPU counter 增加，仍未证明 native 静止或热验收通过；有效 local-only 计时、缺失 pipeline 的可疑原因和采样界限见[线程专题](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。
- 生产源码已实施 `RecognitionConfig` 的 long 默认 `disablePrepack=false`，short/prepare/Core 仍为 `true`，显式 engine boolean 优先；同步 PCM16 helper 四源也已写入。相关 host、demo/文档和真实方法的 host 检查已通过，计数与各自源码身份见线程专题。Harmony 诊断候选构建与第十二臂显式配置的真机短程验证已完成，八源码恢复当前 clean、两个 HAR/HAP 已冻结；Android native build PASS、四源未变。错误 prepack 参数臂另记 SETUP_MISMATCH，原 report FAIL 保留、不作有效对照。后续无 TEMP 的 clean 构建与 API23 检查已通过，API23 范围仅为两份 HAR 中 21/27 个非声明 TS，不扩大为 `.ets` 或 Windows 全覆盖。SDK_MODE_DEFAULT 省略键短程的 application/lifecycle PASS，实际 prepack 开启、ASR4；窗口 hash 与已比身份一致，但仍非 1 秒 hop 稳态。初始化没有隔离计时，资源与完成后仅 3 点、约 20 秒 CPU 观测的数值和边界见线程专题。600 秒 clean 包运行已完成，但 overall/lifecycle FAIL（FINISH_TIMEOUT，reason=4），application PASS；末窗 degraded、turns=0、身份全为 `-1`。三角色只记为未验收的输出差异，现有温频观测不支持热 PASS 或热降频归因。失败证据与首次 0 输入 SETUP_FAIL 的排除见[600 秒失败说明](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-clean600-fail)；身份真值精度与最终产品验收仍待完成。
- 后续分锁 clean `7bf…` / job1008 也为 FAIL：30000 frames、50 finals、唯一 last/complete、0 errors、liveStreams=0，但角色 reason=4；新增 ID 3/报告 4 人及最终 `581300–600000 ms` 全 unknown 仅是输出差异，无 GT，不判 identity regression。累计 `inferenceMs=646676.502/RTF=1.077794` 不代表输入吞吐；起温低于 933、缺少 post-summary CPU 锚点，也不能升级为热或完成后 CPU PASS。分锁两 hunk 已撤销；`3151819…` affinity 候选的 `6ecf07…` HAP 仅为 DIAGNOSTIC，job1044 构建 exit 0、八源恢复 PASS，1049/1059 同冻结 HAP/native 的 120 s 诊断均已 collect、短程 PASS、cleanup PASS；1059 唯一配置差异为 QoS，111 窗四 hash 及公开身份投影相同，短程指标不构成长稳、热或唯一因果结论。旧 `7bf…` API23 成功不覆盖该阶段的新候选；1049/1059 的旧 HAP 载体绑定 `5feee61f…`。证据集中在[历史失败与 affinity 短程观察](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-mutex-split600-pool-affinity)；原 960 秒与 120 秒重复 5 次的 600 秒构造非等价，同一签名产物的原 960 秒息屏验证仍待完成，[取消记录的历史 skip](DIARIZATION_CANCELLATION_20261001.md#L44)保持不变。身份真值精度与最终产品验收仍待完成。
- 前一阶段 AHC memo 已实现（header `1c07657d…`，当时 CPP `3151819…` 不变），host 10 项及最终 3 项 PASS、独立复核无 blocker；N2048 实际启用且保留原 32 MiB 内存门槛，score 预算 16 MiB 加 O(N) slot，N>2048 走原路径，标量扫描仍可 O(N³)。1104 新诊断短 120 s/cleanup PASS，111 窗四 hash 与 1049/1059 全同、公开身份投影同，但没有一致的端到端收益。1125 所用历史 clean HAP 为 `7038…`：九源精确 clean、无 probe、三产物 0444，新 HAR API23 21/27 PASS；Android1086 已实际 compile/link 新 header，PASS。1125 的同一 `7038/eabc` 600 s 已完成并全部收集：30000 frames、50 finals、唯一 complete、errors=0、liveStreams=0，application/tail PASS，但 overall/role lifecycle FAIL（reason=4），公开 last/role/complete 距 finish 为 `16642/16643/16645 ms`。前四窗非降级；最终 `461.3–600 s` 的 11 条 utterance primary/span 全 `-1`、secondary 空、turns=0。期望 591 个 native 窗口的实际完成覆盖及 internal ASR tail/drain 均 UNKNOWN，不能用累计 RTF 推断完成；identity/collection/cleanup PASS 不能覆盖产品 FAIL。新版时钟取得 thermal 130/frequency 131 条有效查询，但末段升温与有起测空档的 post20 零整秒 CPU 不证明热稳态或 native 静止，旧 1008 UNANCHORED 与初温不匹配保留。1125 已确认 continuous→long、省略键实际 `disablePrepack=false`，不是 short/prepack 错配；普通 Demo 无 continuous 时默认 short 仍不同。原 960 s 已暂停，热、身份真值、离线与界面覆盖仍未验收。后续 accepted-label reuse（header `47f59d9d…`）与 pooling 合并（CPP `a145c440…`）均已实现并通过 host、平台 build 验证；18 项 AHC 检查、原 green-01 FAIL、两个 mutant 敏感性，以及 pooling 的 1 unittest/6 成功+3 拒绝与 111 窗 host 调用 `230→188` 的限定口径，见[后续实现与构建](<DIARIZATION_THREAD_OVERHEAD_20260930.md#accepted-label-reuse-pooling-build>)。Android1198/Harmony1200 均 exit 0；新诊断 HAP/native `34a4…/f7eb…` 已归档，状态 `PASS_NOT_DEVICE_ACCEPTED`，device/API23/clean release 均 `NOT_RUN_NOT_AUTHORIZED`。真机收益与产品验收待定，1125 `FAIL_FINISH_TIMEOUT4` 未解除。关键数值与证据见[1125 失败及测量边界](<DIARIZATION_THREAD_OVERHEAD_20260930.md#clean7038-job1125-600-fail>)；此前实现、运行与构建摘要见[AHC memo 与 clean 7038](<DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-ahc-memo-clean7038>)。
- 现有 `f0fa…` 安装失败、round3 前七臂 FAIL、第八、十、十一、十二臂仅短程 PASS、第九臂 overall FAIL，以及身份精度边界继续保留；发热与息屏变慢两个问题尚未取得 PASS。
