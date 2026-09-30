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
- `finish` 之后 30 秒仍未 drain，**没有 `isLast`、没有 `CALLBACK_COMPLETE`**，测试以 cancel 收束。

即：不是"角色降级"，而是**整场会话无法收尾**。

## 对修复方向的含义

1. **调度层（QoS/绑核）不能解决锁屏问题**：cpuset 收窄在应用之外，`sched_setaffinity` 无法越过。
   已实现的调度覆盖应保留（亮屏下有效、且不影响正确性），但不得再声称它修复锁屏。
2. **只能降低角色链路的 CPU 需求**：当前锁屏下单窗约 2.4–2.5 s，而步长是 1 s，超预算 2.4 倍。
   要落进小核预算需要约 2.7 倍降幅，只有模型层改动（量化/更小 encoder）能到，且必须重走身份精度门禁。
3. **必须防止角色链路拖垮 ASR/us 会话**：现在角色跟不上会持续占用 CPU，导致 ASR 也落后、会话无法
   last/complete。需要有界退让（跟不及时明确降级并让出 CPU），把"整场不可用"变成"角色不可用、
   识别可用"。
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
