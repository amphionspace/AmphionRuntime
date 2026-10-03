# 息屏性能：有效亲和性、采样缺口与收尾证据

更新于 2026-10-02。设备为 `7GK0226326015655`（Mate 80 / OpenHarmony-6.1.1.120）。
本页修正此前将线程当前亲和性误当系统 cpuset 上限、用累计 RTF 推导尾积压的结论。
两个用户可见问题仍待通过修复后的匹配设备验收。

## 当前能够确认的事实

匹配安装的 Release HAP `f0fa26aeb69c3faaf9ee292e5ca1ec96928de2a550640adc0f49ec08f7cbff10`
在 120 秒受控重放中得到 `finals=10`、`completes=1`，但角色结果为
`degraded=1`、`reason=4 (FINISH_TIMEOUT)`、`speakerCount=0`，整体验收 FAIL。
公共 ASR 生命周期通过不代表角色收尾通过。

同轮主线程 `/proc/<pid>/status` 的 `Cpus_allowed_list` 从 AWAKE 时的 `0..11`
变为 SLEEP 时的 `0..3`；主线程 cgroup 成员记录也从 `top-app` 经 `key-background`
变为 `background`。这些是相关联的观测，尚未读取到各目标线程所在组的实际有效 CPU 上限。
短时 shell-back 温度约 `30.8→31.8°C`，不能替代长时热验收。

## 2026-10-02 round3：应用内快照有效，前七个对照 FAIL，prepack 结果需分开解释

round3 十二个 arm 的完整 wall/embedding、冻结 HAP、provider profile、ASR cursor、阶段拆解和 prepack 对照数据集中在[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。前七个 arm 全部 FAIL；ASR4 prepack arm 仅短程 overall/application/role lifecycle PASS，finish backlog 为 0，但 late-wall 仍高于 1 秒且角色处理滞后仍增长，不能外推长期/热通过；ASR2 prepack arm overall FAIL，保留 RSS/thread growth advisory，虽然 application 和唯一 last/complete PASS，也不采用。第十臂 encoder active-only bounded spin 短程 PASS，但角色晚段滞后与收尾更慢，不采用；生产保留 encoder `allow_spinning=0`。第十一臂 role bridge stages 短程 PASS，111 窗四字段 hash 与第八臂一致；local-only 计时有效，完整 native pipeline 计时为 0 条/INCONCLUSIVE，仍不能宣称 1 秒 hop 稳态。第十二臂 native PCM16 + 显式 prepack 短程 PASS，已取得 111 窗匹配的完整 pipeline 计时，read 和 lag 改善，但晚段仍超过 1 秒且 lag slope 为正。对第八、十一臂的原生四 hash 和对应冻结身份一致，公开窗口仅 `inferenceMs/rtf` 不同；数值、字段分类和精度适用范围见同一主表。

对应窗口四字段哈希一致不能替代身份真值门禁。公开结果存在 `resultHex`；baseline 与 prepack 的 final 覆盖不同，整体文本 hash 不同不能单独判为精度退化。Core tokens/时间边界未直接采集，文本与边界可比范围、资源原始数值统一见[线程专题说明](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。

round3 各 arm 的应用内线程快照、旧 shell 空数组的 INVALID 边界和有效 mask 统一见线程专题主表，不能从当前 mask 推导系统 cpuset 上限。provider profile、canonical graph 计数、qlinear event 语义和 unknown 排除规则也不在本页重复。

CPU1 基线与 CPU-only 候选改变了不同的 provider/allocator 与 CPU budget，不能作为纯 CPU budget 单变量；XNNPACK arena、Runtime ready-gate 和 ASR stages arm 都已运行但 FAIL，ready-gate 与阶段拆解都未消除主要 ASR backlog。ASR4 prepack 只改变 prepack，短程能排空但不能替代长期/热验收；ASR2 只把 ASR threads 从 4 改为 2，overall FAIL 且不采用。详见[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。

CPU4 cursor、XNNPACK arena、Runtime ready-gate 和 ASR stages arm 的 role/ASR cursor 在收尾时仍有明确落后，且载体期限内没有 `asr-stop-enter/exit`；ASR4/ASR2 prepack arm 在 finish 时 backlog 为 0 并进入 tail/complete。具体 backlog、处理游标、阶段拆解和时间关系统一见线程专题主表。旧 observed-spool 只能作为下界。

证据保存在本地、不进入 Git：

- `.cache/speaker-screen-repro-acf477c2/armFinalReleaseSourceBoundScreenToggle120/stress/20261001-151405-continuous-max-duration-3e43309d/report.json`
- 同臂 `manual-screen-action.txt`、`telemetry/telemetry.ndjson`、`thread-affinity.ndjson`。

## 亲和性字段不能证明什么

`/proc/<pid>/status` 对应线程组 leader；`sched_getaffinity(0)` 对应调用它的线程。
它们返回当前有效亲和性，不是独立测量的 cgroup 上限，也不代表全部工作线程。
一个线程可以用 `sched_setaffinity` 请求比当前亲和性更宽的集合；内核再根据实际系统约束
决定接受、裁剪或拒绝。因此不能先与当前 mask 求交后宣称“内核不允许扩展”。

历史 Diagnostics 臂 `armFinalWorkerInheritScreenOff120` 有有效逐线程样本：
部分已由调度日志识别的 ASR worker 后来确实读到 `0..3`；特定 ASR/Community driver
请求 `4..11` 后曾被裁剪，或收到 `EINVAL`。这些记录证明对应时刻、对应 TID 的请求结果，
不能单凭它们确定约束来自 cgroup、QoS 还是其它系统策略，也不能移用作新 Release 的线程证据。

旧频率样本显示 `0..3` 的最高频率低于其它核，但未完成 CPU 拓扑或 capacity 核对；本文仅按
CPU 编号报告，不以“小核”作为已经测明的唯一根因。

## 旧 Release 逐线程采样无效，round3 应用内采样有效

复核发现，上述旧 Release 臂共 32 条外部采样，31 条有 PID，但 `threads` 全为空数组。
随后直接检查设备确认：shell 无权枚举该 Release 应用的 `/proc/<pid>/task` 目录。
旧采样器忽略了枚举错误，将空数组计算成 `narrowerCount=0`，这不能证明 worker 掩码相同。
另外，遥测中的 `/proc/<pid>/task/*/stat` 通配符未展开，错误文字写在 stdout，
即使 HDC 返回码为 0，也没有取得有效的工作线程 CPU 时间。

round3 改用应用内部有界只读采样；各 arm 的线程枚举错误、有效线程 mask、CPU tick 与 cgroup 标识见线程专题主表；unknown/无效记录不计入有效样本。这些快照可用于描述 round3 的实际线程现场，但不代表系统 cpuset 上限。
任何旧样本中 PID 存在而线程数据为空的情况仍必须标为 INVALID。详细性能和失败结果见[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。

## 调度实现与执行器预算是两个问题

当前分支将完整 `cpuIds` 请求交给 driver 的 `sched_setaffinity`，不先用当前 mask 截断。
此前 Community 构造池时清空 `cpu_ids` 的 OHOS 选择已撤销；构造期 affinity 阶段的 `3151819…` 候选保留 copied policy/RAII scope，在 Session/provider 构造边界保留 CPU IDs，退出时恢复借用 driver，非 OHOS 仍走原清空分支。失败分锁已撤回，Process/Cluster 恢复同一 `inference_mutex_`。
之后改变 driver 不会传播到已有 worker，QoS 也不能笼统视为继承。真实 constructor + scope 的 host 回归旧 `2918` 红 5 个显式请求场景、新候选绿 7 场景，4 项最小 host 检查 PASS；Android Model 预处理一致，但尚非实际 owned-worker affinity 或设备吞吐验收，详见[候选证据](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-mutex-split600-pool-affinity)。
job960（600 s 诊断）的[owned-pool 归属](../../.cache/speaker-screen-repro-acf477c2/round3-probe/thread-affinity-analysis-960.json)仍为 INCONCLUSIVE：旧 `ProbeProcess` 是 scheduling scope 仍存活的窗末采样，不是 after-return；全进程 raw 快照和 observed mask 不能确定 owned pool、其请求 mask 或系统 cpuset 上限。源码构造机制不能单独定为设备慢因。

另已确认执行器预算需要与 provider 注册一起解释：canonical per-channel INT8 graph 有 36 个 Conv，均采用
UINT8 激活与 INT8 逐通道权重；所用 ORT 1.16.3 XNNPACK 不支持这个组合。round3 first encoder profile
均为 `cpuProvider=58/xnnProvider=0`，其中 `qlinearConv=108` 是三类 profile event 的重复计数，不是 108 个 Conv。
CPU1 基线（CPU fallback 1 + XNNPACK budget 4）与 CPU2/CPU4-only（撤掉 XNNPACK、CPU budget 2/4 + `spin0`）
还改变了 provider/allocator，不能作为纯 CPU budget 单变量；完整对照见[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。
主机 CPU EP 1/4 线程试验已在 8 个输入及 40 组池化掩码上得到逐位相同输出；这不替代手机实际算子分配、吞吐、ASR 争用和热量验收。

## 历史阶段耗时的适用范围

旧 FP32 Diagnostics 数据曾记录息屏后的 segmentation、Fbank、embedding 均显著变慢。
这些 wall time 包含操作系统抢占与调度等待。Fbank 是单线程，仍可能与其它线程竞争 CPU；
它变慢不能排除线程池争用、频率、亲和性或同步开销。跨时长、跨构建的数据也不是严格单变量 A/B。

不能把亮屏 CPU-s/s 乘以 Fbank 的 wall-time 倍数，作为整条流水线在息屏下必然需要多少核的证明。
旧 FP32 的阶段比例也不能直接外推到当前 INT8 Release。

## 收尾失败不能由累计 RTF 反推

`Session.inferenceMs` 累加 native 窗口阶段 wall time，以及聚类调用外层 elapsed；后者可能
包含排队和 mutex 等待，并与其它处理区间重叠。因此 RTF 不是处理游标，不能从 `RTF=0.962`
推出“960 秒积压 38 秒”；即便是真正纯计算 RTF，小于 1 也不是逐秒积压的算式。

必须同时记录输入末端、角色完成样本位置、ASR 已处理位置、真实 ASR tail、角色排空和聚类结束。
角色 finish barrier 仅在真实 ASR tail 到达后开始 15 秒等待；公开 `isLast` 又会被 barrier 暂存。
所以 `finals=9/completes=0` 不能单独证明 native ASR 没有生成 tail。

已有结构化日志区分出两种现场：真实 ASR tail 后仍有约 24 秒角色音频未完成并触发降级；
以及直到载体取消前最后观察到的 ASR 结果仍是非 tail。两者不得混为同一个超时原因。
`pendingJobs` 是有界已物化描述符数量，不能据它小于等于 1 判断没有积压或执行器丢窗。

round3 CPU4 cursor arm 的同刻 role/ASR cursor 差值直接证明 ASR backlog；载体 30 秒期限前没有 stop enter/exit，
所以该现场尚未进入 stop，而在 accept/dispatcher 排空。详细游标、tail、drain 和完成时间统一见[线程专题主表](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。

早期 `--timeout 900` 小于 960 秒输入的重放不能用于会话收尾判定；其喂入期间已经记录的
样本位置落后仍是有效历史观测。不能放宽 timeout、删窗或提前发布 last 以消除失败表象。

## 下一步验收

当前保留方向是 OHOS CPU budget + `spin0`、Android CPU fallback 1、两平台 XNNPACK 注册、canonical INT8、1 秒 hop、segmentation/池化模型和 FP32 from-buffer 兼容。ASR4 prepack 只有短程 PASS，ASR2 overall FAIL 且不采用。本次正式 clean host regression 与 Android native build 为 PASS，完整探针 cleanup 已归档；源码身份及证据链接见[线程专题的回归说明](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。

第十臂的 `postNativeCpuSamples` 已更正为 `INCONCLUSIVE`：初版 CPU 零点错移且 device/host 时钟未可靠校准，初版推导已废弃；不能从完整区间 CPU 累计值推断 idle 或热稳定，证据见[线程专题](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。第十一臂 complete 后约 30 秒未观察到同 PID CPU counter 增加，仅是有采样界限和计数分辨率限制的观测；native 静止及热验收均未证明。完整 pipeline 日志缺失的可疑原因与有效 local-only 数值见同一主表。

生产源码已实施 `RecognitionConfig` 的 long 默认 `disablePrepack=false`，short/prepare/Core 保持 `true`，显式 engine boolean 优先；同步 PCM16 helper 四源已写入。相关 host、demo/文档及真实方法的 host 检查已通过，证据集中在[线程专题](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-round3cpu-provider-asr-cursor)。Harmony 诊断候选构建与第十二臂显式配置的真机短程验证已完成，八源码恢复当前 clean、两个 HAR/HAP 已冻结；Android native build PASS、四源未变。错误 prepack 参数臂另记 SETUP_MISMATCH，原 report FAIL 保留、不作有效对照。后续无 TEMP 的 clean 构建与 API23 检查已通过，API23 范围仅为两份 HAR 中 21/27 个非声明 TS，不扩大为 `.ets` 或 Windows 全覆盖。SDK_MODE_DEFAULT 省略键短程的 application/lifecycle PASS，实际 prepack 开启、ASR4；窗口 hash 与已比身份一致，但仍非 1 秒 hop 稳态。初始化没有隔离计时，资源与完成后仅 3 点、约 20 秒 CPU 观测的数值和边界见线程专题。600 秒 clean 包运行已完成，但 overall/lifecycle FAIL（FINISH_TIMEOUT，reason=4），application PASS；末窗 degraded、turns=0、身份全为 `-1`。三角色只记为未验收的输出差异，现有温频观测不支持热 PASS 或热降频归因。失败证据与首次 0 输入 SETUP_FAIL 的排除见[600 秒失败说明](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-clean600-fail)。

后续分锁 clean `7bf…` / job1008 仍 FAIL（role reason=4）：30000 frames、50 finals、唯一 last/complete、0 errors、liveStreams=0；公开 last/角色结果/complete 距 finish 为 `19263/19264/19265 ms`。六窗中的新 ID 3/计数 4 及最终 `581300–600000 ms` 全 unknown 没有 GT 可作精度判定；累计 `inferenceMs=646676.502/RTF=1.077794` 可能含重叠区间，不是输入吞吐。1008 起温低于 933，温频未对齐输入/完成锚点；933/job960/1008 的 post-summary CPU 均 MISSING，仅 job960 有 barrier 锚定的 `0 CPU-s` 增长（1 CPU-s 分辨率，19.730–20.302 s），不证明 native 静止。详见[最新失败与候选说明](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-mutex-split600-pool-affinity)。

`3151819…` 候选的 `6ecf07…` HAP 为 DIAGNOSTIC：job1044 构建 exit 0、八源恢复 PASS；1049 默认 QoS 与 1059 user-initiated 的 120 s 诊断均已 collect、短程 PASS、cleanup PASS，冻结 HAP/native 相同；1059 仅改 QoS，native 7/7 次 Get→Set→Get requested/effective=3、applied，但仍为 3 次 adjusted 加 4 次 EINVAL/effective `0..3`。111 窗四 hash、公开 result/turns/message 与 window identity projection 相同，owned/proc 映射仍 UNKNOWN；后 51 窗及收尾指标只作短程观察，未长跑，不能升级为唯一因果、长稳或热 PASS，数值与证据见[短程观察](DIARIZATION_THREAD_OVERHEAD_20260930.md#2026-10-02-mutex-split600-pool-affinity)。旧 `7bf…` API23 成功不覆盖该候选，也不是新 clean/API23 验收。1049/1059 的旧 HAP 载体绑定 `5feee61f…`。

前一阶段 AHC memo 已实现（header `1c07657d…`，当时 CPP `3151819…` 不变），host 10 项及最终 3 项 PASS、独立复核无 blocker；16 MiB score 加 O(N) slot，N2048 真实启用且额外 payload 小于原 32 MiB 门槛。原 distance 首次算术与树/tie/fit 逻辑不变，host 数值/labels bits 等价；N>2048 走原路径，仍可有 O(N³) 标量扫描。1104 新诊断短 120 s/cleanup PASS，111 窗四 hash 与 1049/1059 全同、公开身份投影同，没有一致的端到端收益；QoS 6/6 读回 3，affinity 仍有 4 次 errno=22，owned mask 仍 UNKNOWN。

1125 所用历史 clean HAP 为 `7038…`，九源精确 clean、无 probe、三产物 0444，新 HAR API23 21/27 PASS；Android1086 实际 compile/link 新 header PASS。1125 的同一 `7038/eabc` 600 s 已完成并全部收集，overall/role lifecycle FAIL（reason=4）；30000 frames、50 finals、唯一 complete、errors=0、liveStreams=0，application/tail PASS，公开 last/role/complete 距 finish 为 `16642/16643/16645 ms`。前四个公开窗非降级，末窗 `461.3–600 s` 的 11 条 utterance primary/span 全 `-1`、secondary 空、turns=0；期望 591 个 native 窗口的实际完成覆盖和 internal ASR tail/drain 均 UNKNOWN，RTF 不证明完成。identity/collection/cleanup PASS 只说明证据收尾，不覆盖产品 FAIL。

新版采集器已得到 thermal 130/frequency 131 条有效时钟记录；12 核频率查询区间 median 为 3.067 s，非瞬时同步。finish 前 120 s 的 shell/system 温度斜率 `+0.217/+0.151°C/min` 不构成热稳态。post20 CPU `1759→1759` 的实际跨度为 `20.394–20.964 s`，首次查询在 complete 后 `8.191 s`，不能证明此前无工作、零亚秒 CPU 或 native 静止。CF0 仍只是 publicComplete；旧 1008 UNANCHORED 与初温不匹配保留。1125 的 continuous 默认 long、省略键实际 `disablePrepack=false`，不能归因于 short/prepack 错配；普通 Demo 未启用 continuous 时仍默认 short。后续 accepted-label reuse（header `47f59d9d…`）与 pooling 合并（CPP `a145c440…`）均已实现并通过 host、平台 build 验证；18 项 AHC 检查、原 green-01 FAIL、两个 mutant 敏感性，以及 pooling 的 1 unittest/6 成功+3 拒绝与 111 窗 host 调用 `230→188` 的限定口径，见[后续实现与构建](<DIARIZATION_THREAD_OVERHEAD_20260930.md#accepted-label-reuse-pooling-build>)。Android1198/Harmony1200 均 exit 0；新诊断 HAP/native `34a4…/f7eb…` 已归档，状态 `PASS_NOT_DEVICE_ACCEPTED`，device/API23/clean release 均 `NOT_RUN_NOT_AUTHORIZED`。真机收益与产品验收待定，1125 `FAIL_FINISH_TIMEOUT4` 未解除。1125 的证据与关键数值见[1125 失败及测量边界](<DIARIZATION_THREAD_OVERHEAD_20260930.md#clean7038-job1125-600-fail>)。

原 960 秒 SHA `66133c62…` 与重复 120 秒五次的 600 秒 SHA `8a646530…` 非等价，同一签名产物的原 960 秒息屏验证已暂停、尚未验收；[取消记录的历史 skip](DIARIZATION_CANCELLATION_20261001.md#L44)保持不变。原 960 秒、长时热、离线与界面覆盖仍未验收，身份精度与最终产品验收仍未完成。后续验收应保持 provider/allocator、canonical INT8、1 秒 hop、离线及 ASR 生命周期边界，分别核对逐窗输出、角色排空、唯一 last/complete 和长时热轨迹；本轮仅更新文档，不扩展测评。
