# 锁屏变慢的根因：系统把应用限制到小核（2026-09-30）

**结论：锁屏后 HarmonyOS 把该应用的 cpuset 从全部 12 核收窄到 `0,1,2,3`（4 个小核）。所有推理阶段
因此均匀变慢约 3.5–4.8 倍。这是内核级的 cgroup cpuset 限制，应用自身无法放宽：`sched_setaffinity`
只能收窄、不能越过 cpuset，所以调用方传的 `cpuIds=[4..11]` 在锁屏下必然失败。**

这条推翻了此前两版阶段性结论（"硬冻结是载体假象"只对了一半：真实采集确实消除了冻结，但**性能限制
是真实存在的**；而"绑核覆盖角色链路即可修复"在锁屏场景下不成立）。

## 证据一：内核报告的允许 CPU 集合

来自设备 `/proc/<pid>/status` 的 `Cpus_allowed_list`（采集器逐 5 秒记录）：

| 臂 | 屏幕状态 | Cpus_allowed_list | 采样数 |
| --- | --- | --- | ---: |
| armAffinityLong（960 s，真实采集，角色开启） | AWAKE | `0,1,2,3,4,5,6,7,8,9,10,11` | 7 |
| 同上 | SLEEP | `0,1,2,3` | **229** |
| armSliceT4（120 s，亮屏） | AWAKE | `0,1,2,3,4,5,6,7,8,9,10,11` | 35 |
| armMicHoldScreenOff（120 s，真实采集） | SLEEP | `0,1,2,3` | 32 |

收窄发生在屏幕离开 AWAKE 时，并且此后 229/230 个采样都保持 `0,1,2,3`。

## 证据二：所有阶段均匀变慢，包括不使用线程池的阶段

同一 10 秒窗、同一模型，亮屏（120 s 切片）与锁屏（960 s 长跑）对比，各取 357 个窗口的时间三段中位：

| 阶段 | 亮屏 | 锁屏 | 倍数 | 是否使用线程池 |
| --- | ---: | ---: | ---: | --- |
| `segmentationMs` | 112–117 | 387–413 | 3.5× | 否（`intra=1`） |
| `featureMs`（fbank） | 22 | 81–83 | 3.7× | **完全没有线程** |
| `embeddingMs`（encoder+pooling） | 408–429 | 1925–2036 | 4.8× | 是 |

`featureMs` 是纯单线程计算，没有任何线程池参与，却同样慢 3.7 倍。**这排除了线程池、绑核、空转、
并发屏障等一切线程层面的解释**，只能是"同样的指令流跑在更慢的核上"。

慢的倍数在整个 977 秒里保持稳定（前段/中段/后段 387/413/406 ms），不是逐渐恶化，符合恒定限流。

## 为什么绑核不可能修好它

- Linux 的 `sched_setaffinity` 与 cgroup `cpuset` 是**取交集**关系：请求的 CPU 必须落在
  `Cpus_allowed_list` 内，否则调用失败（EINVAL）或得到空集。
- 锁屏期间 `Cpus_allowed_list=0,1,2,3`，因此请求 `4..11` 必然失败，线程仍留在小核。
- 本次已实现并注入真机的角色链路调度覆盖（`213bd791` + `b94e53d3`）在锁屏场景下因此**没有效果**；
  它只在亮屏（cpuset 为 0–11）时可能生效。这也解释了为什么加上它以后长跑仍然落后。

## 预算算术：为什么 0.3.13 可以、0.3.19 不行

以亮屏 CPU 口径估算（`ps -o TIME`，见 `DIARIZATION_THREAD_OVERHEAD_20260930.md`）：

| 配置 | 所需 CPU-s/墙钟秒 | ×3.7 后折算到小核 | 4 个小核是否够 |
| --- | ---: | ---: | --- |
| 仅 ASR（0.3.13） | 0.850 | 3.1 | 勉强够，所以"不会延迟很多" |
| ASR + 角色（0.3.19） | 2.641 | 9.8 | **不够**，必然落后 |

这与客户现场描述完全一致：同一段会议、同一套 `affinity cpuIds=[4..11] spinning=false numThreads=4`
参数下，0.3.13 锁屏基本不延迟，0.3.19 开角色后明显变慢。

## 长跑实测后果

960 秒语料、真实麦克风采集、锁屏、角色开启（`armAffinityLong`，完整 journal 解析）：

- 音频写入 960 s（`max audioEndSample=15,360,000`）；
- ASR 只处理到 **523 s**，角色只完成到 **366 s**；
- 角色积压 `audioDelayMs` 最大 **603 s**，`pendingJobs` 最大 1（执行器在丢窗，未反压音频）；
- `finish` 发生在输入 960.003 s 处，30 秒后仍未 drain，被 cancel 收束。

**这组落后数据有效**：`audioDelayMs` 与 `completedThroughSample` 出自喂入期间，与驱动超时无关。
角色落后 603 秒、单窗 2.4–2.5 s 超过 1 s 步长 2.4 倍，都是实测。

### 方法论更正：早先"会话无法收尾"的结论不成立

上述两臂使用了 `--timeout 900`，而语料本身长 960 秒——**驱动在喂完音频之前就已经超时**，所以
"没有 `isLast`、没有 `CALLBACK_COMPLETE`"是**测试配置造成的**，不能归因于 SDK。同理
`armMicHoldLong`（同样 `--timeout 900`）也不能用于收尾结论。

正确做法是超时必须大于"喂入时长 + 排空预算"。已用 `--timeout 1800` 与产品配置（关诊断）重跑，
结论以该臂为准。

## 产品配置实测（关诊断）：角色能跑，但收尾失败

长跑的数字来自**诊断构建**，逐窗写盘与事件记录会放大成本，不能代表客户配置。`DIAGNOSTICS_BUILD`
是编译期常量（`DiagnosticsModule.ets:26` 读 `BuildProfile.ets` 的 `BUILD_MODE_NAME`），运行期无法关闭；
把 HAR 内 `BUILD_MODE_NAME` 由 `diagnostics` 改成 `release` 即可得到**代码完全相同、仅关诊断**的
产品配置（该常量只被诊断模块使用）。用该配置重跑 960 秒、锁屏、真实采集、角色开启：

| 指标 | 诊断构建 | **产品配置** |
| --- | ---: | ---: |
| 角色 RTF（`inferenceMs` / 音频） | > 2.5（落后 603 s） | **0.962**（732,693 ms / 960 s） |
| 角色是否降级 | 最终超时降级 | **未降级（`degraded=0`）** |
| 角色输出 | 无 | **2 位说话人，3 次临时结果** |
| 单窗 native 合计 | 2,441 ms | 未采（诊断关闭后无逐窗事件） |
| 结果 | 无 last/complete | **仍无 last/complete（`liveStreams=1`）** |

**所以"锁屏后角色完全跑不动"是诊断构建的假象；产品配置下角色能跑，只是没有任何余量。**

### 收尾失败的精确机制

- 载体在 `finish` 后给 30 秒（`COMPLETE_TIMEOUT_MS = 30000`）等待 `isLast` + `onComplete`；
- 角色 RTF = 0.962，即**每 10 秒音频落后约 0.4 秒**；960 秒累计落后约 **38 秒**；
- 这 38 秒的残留在 `finish` 之后仍需处理完才能定稿，**超过了 30 秒的收尾窗**，因此没有任何
  `isLast`/`complete`，`fedFrames=48000`（音频确实喂满 960 秒）。

即：**RTF 逼近 1 时余量消失，落后量随会议时长线性累积，最终表现为会话无法收尾**。这也解释了
为什么 120 秒的短臂能通过（累计落后仅约 5 秒），而 16 分钟长会失败。

## 对修复方向的含义（更新）

1. **调度层（QoS/绑核）不能解决锁屏问题**：cpuset 收窄在应用之外，`sched_setaffinity` 无法越过。
   已实现的调度覆盖应保留（亮屏下有效、不影响正确性），但不得再声称它修复锁屏。
2. **把角色 RTF 从 0.96 降到 ≤0.7 才能拿回余量**：在 4 个小核上这需要把角色计算量再降约 30%，
   只有模型层改动（量化/更小 encoder）能到，且必须重走身份精度门禁。
3. **收尾预算需要与会议时长脱钩**：现在定稿成本随音频时长线性增长，长会议必然撞上固定等待窗。
   要么降低定稿的聚类成本，要么让调用方拿到"定稿仍在进行"的明确状态，而不是最终没有任何回调。
4. 1 s 证据密度、身份映射与已提交冻结保持不变，不得用放大 hop 换取性能。

## 复现

```bash
# 960 s 语料 + 真实采集 + 锁屏 + 角色
OFF_AFTER=30 COLLECT_SECONDS=1200 DATA_DIR=corpus-aligned \
  bash .cache/speaker-screen-repro-acf477c2/run_arm.sh armAffinityLong \
  --mode continuous-max-duration --cycles 1 --timeout 900 \
  --enable-diarization --diarization-num-threads 4 \
  --allow-screen-off --hold-mic-capture \
  --asr-cpu-ids 4,5,6,7,8,9,10,11 --asr-disable-spinning --asr-num-threads 4
```

`Cpus_allowed_list` 直接取自 `armAffinityLong/telemetry/telemetry.ndjson` 的 `process.text`；
单窗阶段耗时取自完整 journal `events.full.ndjson`（轮转文件需合并去重，`summary.json` 只是有界尾部）。
原始 PCM 与遥测不进入 Git。
