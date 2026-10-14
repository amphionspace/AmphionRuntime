# 锁屏变慢与吐字慢：归因、改动与待客户验证项

日期：2026-10-12 · 版本：0.3.22 · 设备：Kirin 9020（客户与我方同型）

针对 0.3.22 现场反馈的两个问题给出根因、已完成的改动、以及需要客户配合完成的验证。
两个问题的根因都在 SDK 内部，不是集成方式或设备差异。

数据来源：客户提供的 60 分钟会议录音（`0937.wav`）与对应 hilog（5 个文件 26 MB）、
20:34 锁屏复现录音（`2034.wav`）与 hilog（3 个文件 14 MB），以及我方在同型设备上的对照实测。

---

## 一、根因

### 问题一：锁屏后识别变慢约 3 倍

> **本节已于 2026-10-14 更正。** 下面先给被否掉的归因，再给成立的那个。客户按原归因
> 做了配置、症状未变，这个过程本身就是证据，所以两版都保留。

#### 被否掉的归因（本文 10-12 初版）

初版认为根因是 SDK 自己申请了 `QOS_BACKGROUND`：

```ts
// AsrSchedulingConfig.ts
return diarizationHopMs >= 2000 ? 'background' : 'inherit';
```

`diarizationQos` 默认 `auto`、`diarizationHopMs` 默认 `2000`，解析成 `background`；客户日志里的
`role-qos requested=0 result=0 effective=0` 正是它（`QOS_BACKGROUND = 0`）。据此交付了
`displayMayTurnOff` 开关，声明可能熄屏时保持 `inherit` 不降档。

**该归因不成立，而且其因果前提本身是错的。**

先看现场：客户用 0.3.22-1013 开启该开关后复测（10-14 两场），全量 hilog 中 `role-qos`
**一条都没有**（开关生效、SDK 不再申请降档），而熄屏实时率仍为 **0.80×**，滞后随锁屏时长线性
累积，峰值 67.6 s。

再看机制。该归因依赖一句我方写进源码注释和交付文档的论断：「background QoS 隐含 background
cpuset，所以应用侧的绑核拼不过它」。**我方已实测否证该论断**（Kirin 9020，熄屏，`--asr-qos
user-interactive`）：

| 线程 | QoS 实测 | `Cpus_allowed_list` |
| --- | --- | --- |
| 识别线程 | `qos-effective result=5` = `QOS_USER_INTERACTIVE`（**最高档**） | `0,1,2,3` |
| 角色线程 | `role-qos effective=0` = `QOS_BACKGROUND`（**最低档**） | `0,1,2,3` |
| 进程全部 54 个线程 | — | **全部 `0,1,2,3`** |

**最高档和最低档的可用核完全相同。** QoS 决定的是在**既定核集合内**的调度权重；核集合本身由
系统按进程前后台状态指派为 cpuset，`sched_setaffinity` 与 QoS **都无法扩大它，root 亦然**。

所以 `displayMayTurnOff` 不是实现有缺陷，而是整条因果链从一开始就错了。该开关的实际作用只是
「不让角色线程在已被限制的那几个核里再被降权」，现场复测未测出可辨识收益。

#### 成立的归因：进程级 cpuset，与我们是否申请无关

熄屏时系统把**整个进程**挪进 `key-background`，该组只有 4 个小核。三条独立证据：

| 来源 | 证据 |
| --- | --- |
| 客户现场巡检 | `/proc/<pid>/cpuset` 由 `top-app` 变 `key-background`；79~83/83 线程掩码全为 0-3 |
| **客户日志里我方 SDK 自己打的** | 熄屏后 `affinity-exact result=0` → `affinity-set result=22`（`EINVAL`） |
| 我方设备直接读取 | 熄屏时 `/proc/<pid>/cpuset = /cpuset/key-background`；后台态 `Cpus_allowed_list: 0,1,2,3` |

`EINVAL` 的含义是确定的：请求掩码 `{4..11}` 与进程允许集的交集为空。`sched_setaffinity` 的掩码
会与所属 cpuset 的 `cpus` 求交，**空集即 `EINVAL`，root 也不例外**。我方绑核只用
`sched_setaffinity`（全仓历史中 `cpuset` 仅出现在注释里，从未有过操作），所以绑核在进程被降级后
必然失败，这与 SDK 申请什么 QoS 无关。

#### 成本在哪：segmentation 占 73%，而我们优化的 encoder 只占 5%

我方设备在**相同的 4 小核**约束下（同为 `kirin9020_v2_0`）实测 24 分钟、716 个窗口：

| 阶段 | 中位 | 占比 |
| --- | --- | --- |
| **segmentation** | **446.1 ms** | **73%** |
| fbank | 89.7 ms | 15% |
| pooling | 44.2 ms | 7% |
| encoder（NPU） | 32.3 ms | 5% |
| 单窗合计 | 612 ms | |

0.3.21/0.3.22 把 encoder 搬上 NPU，动的是这 5%。客户报告把 0.54×→0.80× 归因于它，**该归因缺少
依据**。

#### SDK 侧补不上这个缺口

从 0.80× 到 1.0× 需腾出 0.20×。而角色分离链**全部**开销只有 0.180×（258.7 s 墙钟 / 1440 s 音频）：

| 杠杆 | 可腾出 | 状态 |
| --- | --- | --- |
| 放宽 hop（2000→4000） | ~0.090× | 被 `CommunityHopSamples` 取最小间距的推导挡住（见第五节） |
| 分割换 MS Lite CPU 运行时 | ~0.083× | 未在小核验证；MindIR 已转换且逐位一致 |
| 分割加线程 | **0.018×（实测）** | 已实施，见下 |
| 角色分离整个删掉（上限） | 0.180× | **仍 < 0.20×** |

**连把角色分离整个删掉都补不上**，所以这不是一个能由 SDK 单独关闭的问题。

另一个必须排除的变量：客户测的 0.3.22-1013 包，其**正式 SDK 误用 diagnostics 模式构建**（我方打包
缺陷，已在 `dca08e69` 修正），诊断模块每个回调落盘写事件。0.80× 中有多少来自这笔开销目前未知，
需用修正包复测才能得到干净基线。

客户实测数字我方已独立复算一致：

| 状态 | partial 间隔中位 | p90 | 最大 |
| --- | --- | --- | --- |
| 锁屏前 | 0.45 s | 0.95 s | 2.80 s |
| 锁屏中 | 1.36 s | 1.56 s | 14.22 s |
| 亮屏后 | 0.45 s | 0.59 s | 36.89 s |

### 问题二：开说话人分离后吐字慢

这是三个独立原因叠加，不是单一缺陷。

| 成分 | 根因 | 性质 |
| --- | --- | --- |
| 长段朗读等 30 秒以上才出 final | `enableContinuousRecognition=true` 使 `recognizerMode='long'`，进而把 `rule3` 设为 `-1` 即禁用，长录音失去句长兜底 | 真缺陷 |
| 稀疏说话时长时间无输出 | `rule1` 在没有任何语音内容时也切句，每约 2.4 秒把原生流推倒重建，短语音片段累积不起来 | 真缺陷 |
| 特定区间完全无输出 | 该段音频本身没有可转写的语音 | **非缺陷** |

`rule3` 被禁用的链路：

```ts
// EndpointRulePolicy.ts
const defaultMode = sessionExtraParams['enableContinuousRecognition'] === true ? 'long' : 'short';
minUtteranceSec: mode === 'short' ? endpointMaxUtteranceSec(sessionExtraParams) : -1
```

sherpa 侧 `RuleActivated` 对负值直接返回 false，所以 `long` 模式下 rule3 完全不参与。
结果是长录音场景里唯一的切句者只有 rule2（2.0 秒静音且要求有内容），朗读中途没有 2 秒停顿
就会一直不提交 final——客户日志里那条 33.6 秒的长句即此。

---

## 二、需要纯正的两点

### partial 没有被压住

客户分析中的「部分句子的中间结果（partial）被压住不吐」不成立。实测 partial 全程正常流出：
那 34 秒区间内每 0.5–0.7 秒一条，文字从 3 字连续增长到 146 字；全场 999 个 partial、
中位间隔 0.66 秒。实际缺失的是 **final 的提交**。

```
09:55:11.974 partial len=3     09:55:22.302 partial len=45    09:55:42.669 partial len=134
09:55:13.080 partial len=7     09:55:30.198 partial len=78    09:55:45.597 FINAL   len=146
```

### RESULT_SUPPRESSED 是干扰项

222 次压制全部是 `textChars=0 tokens=0 hasEvidence=false` 的空结果，压掉是正确行为，
与本问题无关。

### 另外两点与客户分析不同

- **锁屏瞬间那 14.22 秒不是卡顿。** 日志显示 20:34:41 会话正常结束
  （`onComplete` → `stopCapture reason:complete` → `MS_LITE destruct` → `finalizeArchiveSession id=15`），
  20:34:51 才开新会话。所以「亮屏 0.45 s vs 锁屏 1.36 s」是跨会话对比；放慢 3 倍属实，
  但不是同一会话内的劣化。
- **编码器没有回落到 CPU。** 日志为 `backend=npu device=NPU_ohos.boot.hardware.kirin9020_v2_0`，
  NPU 正常工作。此前「编码器回落导致慢 10 倍」的假设在该设备上被推翻。

---

## 三、已完成的改动

| 文件 | 改动 | 对应问题 |
| --- | --- | --- |
| `AsrSchedulingConfig.ts` | 新增 `displayMayTurnOff: boolean = false`；`resolveDiarizationQos` 增加第三参数，声明可能熄屏时保持 `inherit` 不降档 | 问题一 |
| `SpeechRecognizeSdk.ets` | 调用点传入 `displayMayTurnOff` | 问题一 |
| `Types.ets` | `EndpointRules.rule1` 默认 `true → false` | 问题二（稀疏） |
| `Runtime.ets` | 新增 25 秒句长上限，超出且已有文字时主动切句，日志 `source=utterance-length` | 问题二（长句） |
| `Runtime.ets` | 新增 `kind=SESSION_CONFIG` 每会话回显端点规则与 VAD 配置 | 可观测性 |
| `SpeechRecognizeSdk.ets` | `CALLBACK_RESULT` 补记 `speakerIndex`/`utteranceId`/`speakerConfidence`；新增 `CALLBACK_DIARIZATION_UPDATE` | 可观测性 |
| `DingqiaoModels.ets`、`SpeakerDiarizationSession.ets` | `SpeakerDiarizationResult` 暴露 `encoderBackend`；`FINISH_TIMEOUT` 的 `degradedMessage` 带上实际后端 | 诊断 |
| `run_device_stress.py`、`EntryAbility.ets`、`DeviceStressTest.ets` | 压测链路支持 `--diarization-display-may-turn-off` | 验证用 |

### 10-14 追加的改动

| 文件 | 改动 | 对应问题 |
| --- | --- | --- |
| `community_diarization.cpp` | 先建 encoder，再按"是否有 encoder 落在 CPU"决定分割线程数（全部上加速器时取 2 线程），并加 `force_spinning_stop` 只在 `Run` 活跃期自旋 | 问题一（余量） |
| `SpeakerDiarizationFinishBarrier.ts` | 收尾截止由"ASR 尾部起算"改为"停录起算"，打捞预留从截止内部切出而非叠加；ASR 尾部未到时延迟打捞 | 问题三 |
| `SpeechRecognizeSdk.ets` | 截止 14000 / 预留 3000；新增 `kind=DIARIZATION_FINISH` 逐会话上报收尾时间分解（release 可见） | 问题三 |
| `Types.ets`、`Runtime.ets`、`EndpointRulePolicy.ts`、`RecognitionConfig.ets` | 长录音句长上限改为采纳 `endpointMaxUtteranceMs`，夹在 `[5s, 25s]`，有效值回显 | 问题二（感知延迟） |

### 验证状态

**问题一：原归因已被客户复测否掉，`displayMayTurnOff` 无效。**

10-12 时在亮屏 A/B 中确认过"开启后 SDK 不再申请降档"（默认臂 3 条 `role-qos`，开启臂 0 条），
但那只证明了开关生效，没证明症状消失。10-14 客户带着该开关复测两场，`role-qos` 全程为 0、
熄屏实时率仍 0.80×。**该修正对本症状无效**，根因是进程级 cpuset（见第一节）。

分割线程那条已实测：segmentation 中位 446.1 → 394.1 ms（−11.7%），角色分离链 0.180× → 0.162×，
**只腾出 0.018×**，对 0.20× 的缺口是余量而非解法。保留的理由是它免费、且原先单线程的约束
（与 XNNPACK encoder 争 worker）在 encoder 上加速器后已不存在。

**问题三：已在设备上三臂验证。**

| 臂 | 结果 |
| --- | --- |
| 健康基线（24 分钟，亮屏） | 停录→角色结果 **2.785 s**，零欠账，`timedOut=false` |
| 强制积压（hop 250 + CPU encoder） | **14001 ms**（旧锚点等价 18646 ms），`customer_stop_latency` PASS `max_ms=14104` |
| 慢 ASR 尾部 | `stopToSalvageMs = stopToAsrTailMs = 15120`，延迟打捞成立，推理保住多出的 4.1 s |

截止设 15000 时实测客户可见值为 15099 ms、仍越界（回调链本身约 99 ms），故内部截止取 14000。

**问题二：两处缺陷的修复已实测，但主要症状仍在。**

| 语料 | 指标 | 修前 | 修后 |
| --- | --- | --- | --- |
| 客户稀疏语音 120 s | 最大无输出空档 | 105.1 s | 72.5 s |
| 客户稀疏语音 120 s | final 数 | 3 | 5 |
| 去静音连续语音 301 s | 最大 final 间隔 | 77.8 s | 66.7 s |
| 去静音连续语音 301 s | final 数 | 22 | 24 |
| 去静音连续语音 301 s | final 间隔 p90 | 24.8 s | 24.7 s |

25 秒句长上限实测触发（`source=utterance-length`），p90 24.7 s 与该上限吻合。
但最大空档仍有 66–72 秒，详见第五节。

---

## 四、需要客户做的事

### 1. 问题一：三件事，按性价比排序

> 本小节已于 10-14 整体重写。`displayMayTurnOff` 那条已验证无效（见第一节），不再是待办。

**(a) 用修正包复测一轮，拿干净基线。** 成本最低、可能直接改变结论。

你们测的 0.3.22-1013 包，其正式 SDK 被我方误用 diagnostics 模式构建，诊断模块每个回调
都往磁盘写事件。在 1.6 GHz 小核上这笔开销不可忽略，而 0.80× 里有多少来自它目前未知。
修正包的正式 SDK 为 `debug` 模式，可在包内 `docs/build-identity.json` 自行核对
`build_mode`。

**(b) 把进程或其工作线程移出受限 cpuset —— 这是唯一能独立解决问题一的办法。**

你们亮屏稳态 lag ≈ 0.5 s，证明大核下本来就 ≥1×。但两条常见入口都已被实测排除：

| 入口 | 结果 |
| --- | --- |
| `cpuIds`（`sched_setaffinity`） | 熄屏后 `EINVAL`。只能在 cpuset 内收窄，无法扩大，root 亦然 |
| `scheduling.qos` 调到最高档 | **无效**。`QOS_USER_INTERACTIVE` 与 `QOS_BACKGROUND` 的可用核相同，均为 0-3 |

需要的是改 cpuset 归属本身：

```sh
echo <pid> > /dev/cpuset/<宽松组>/tasks     # 或给 key-background/cpus 加核
```

两点提醒：

- **系统在每次屏幕状态切换时都会把进程挪回去**，所以要在熄屏事件里重新下发，不能只做一次。
- **我方无需任何代码改动。** 绑核作用域构造在每次解码调用里（`SherpaOnnxDecodeOnlineStream`），
  一秒重试多次；日志里只看到 2 条 `result=22` 是因为上报按位去重，不是只试了 2 次。
  你们一旦挪完，下一次解码就会把 `cpuIds=[4..11]` 绑上。

**(c) 改渲染策略 —— 不需要改 SDK，可能解掉大半用户感知。**

你们锁屏期**文字是跟得上的**，这是从你们自己的日志统计出来的：

| 阶段 | 首个 partial | 句末→final | 扣掉句长后的真实滞后 |
| --- | --- | --- | --- |
| 锁屏期（29 句） | **803 ms** | **405 ms** | **1.65 s** |
| 亮屏排空期（20 句） | 500 ms | 51 ms | — |

落后的只有角色标签：锁屏期 **26/29 个 final 的 `speakerIndex = -1`**。而句长中位 12.4 s、
最长正好 25.0 s（SDK 的句长上限在起作用）。

所以"说完等 30~40 秒才上屏"更可能是两件事叠加：界面只渲染 final（要等整句说完），
以及等角色标签齐了才上文字（标签落后 13~67 s）。**先渲染 partial、角色标签等
`onSpeakerDiarizationUpdate` 再回填**，用户就不必等。该接口本就带修订语义。

另外，想让句子更短可以调小 `endpointMaxUtteranceMs`（本版起长录音模式真正采纳该值，
夹在 `[5s, 25s]`，有效值回显在 `kind=SESSION_CONFIG`）。此前该值在长录音模式下被静默忽略。

### 2. 问题二：确认那约 70 秒的实际情况

`0937.wav` 中 09:59:56–10:01:02 一带（音频偏移约 1374–1440 s）在我方三种独立干预下
都提取不出任何文字：

| 干预 | 最大空档 |
| --- | --- |
| 基线 | 105.1 s |
| 仅放大 4 倍 | 73.2 s |
| 仅关闭 rule1 | 72.5 s |
| 两者组合 | 73.1 s |

三臂停在同一地板（72.5–73.2 s），据此判断该段没有可转写的语音。该段音频有声占比 8–47%
（正常区间 49–73%），RMS 125–520（可转写段落 561–2180）。

**请确认：那几十秒内是否有人在正常说话？距麦克风多远？**
日志显示测试者当时在口述「载度属于没有锁屏幕」，疑似在操作手机。
如果当时确实在正常说话，则上述归因有误，该部分需继续排查。

### 3. 可选：确认会话参数

新版 SDK 每次会话开始会打印一行，便于后续定位：

```
kind=SESSION_CONFIG sessionId=1 language=ZH_EN vad=true vadActiveEndpointSilenceMs=800
  endpoint=true rule1=false rule1SilenceSec=2.4 rule2=true rule2SilenceSec=2 rule3UtteranceSec=-1
```

`rule3UtteranceSec=-1` 表示长录音模式下句长兜底被禁用（见第一节），现由 25 秒上限接替。

---

## 五、残留问题与未验证项

不把未证实的当成已解决。以下为明确的边界：

| 项 | 状态 | 说明 |
| --- | --- | --- |
| **问题一** | **未解决** | 根因是进程级 cpuset，SDK 侧无独立解法：缺口 0.20×，而角色分离链全部开销仅 0.180× |
| 问题一的原修正 `displayMayTurnOff` | **已证无效** | 客户 10-14 复测两场，开关生效（`role-qos` 全程 0）但实时率仍 0.80× |
| 问题一的干净基线 | **待复测** | 客户测的 1013 包正式 SDK 误用 diagnostics 模式（我方缺陷），0.80× 中该开销占比未知 |
| 问题一的 cpuset 迁移可行性 | **待客户确认** | 需系统权限写 `/dev/cpuset/*/tasks`，且每次屏幕状态切换后重新下发 |
| 问题二的主要症状 | **仍在** | 最大空档从 105 s 降到 72.5 s，用户仍会看到长时间无输出 |
| 问题二残余的归因 | **待客户确认** | 「该段无可转写语音」证据较强（三臂同一地板）但未经客户确认 |
| 问题二 25 秒上限的覆盖 | **有限** | 上限要求当前已有文字；解码器无文字时上限不生效，这正是残余空档的成因 |
| 问题三 | **已改未交付** | 三臂真机验证通过，但尚未打包给客户 |
| 分割换 MS Lite CPU 运行时 | **未验证** | 10-08 探针显示 35.2 vs 97 ms/窗，但非受控对比，且未在小核域验证 |
| 放宽 hop 以降成本 | **被挡住** | `CommunityHopSamples` 取相邻窗口起点的**最小**间距，中途改 hop 会使 Fb 按密集证据缩放而后半段实际稀疏，正是 #260 要修的失败模式 |
| 熄屏场景的生命周期门禁 | **测不了** | 熄屏下 ArkTS UI 线程冻结，demo 的压测状态上报走 UI 层，`completes=0`。这是 demo/harness 限制，不是 SDK 问题 |

另需说明：`maxSpeakers` 取值范围为 1–4（`SpeakerDiarizationConfigPolicy.ts`，超出直接抛错）。
若实际会议超过 4 人，多出的人会被并入已有标签，角色结果本身就会不准。这是既有产品限制，
不是缺陷，但若客户按更多人数在用，值得单独确认。

---

## 六、复现与验证方法

### hilog 必须在运行期间流式抓取

`run_device_stress.py` 的 `capture_hilog` 只在运行结束后执行一次 `hilog -x`，而设备 hilog 是
跨天的滚动缓冲（实测抓到的文件跨 5 天、8059 行，但本轮 `AmphionMetrics` 仅 13 条）。
结果是**所有会话启动期的日志都抓不到**：`role-qos`、`kind=LOAD`、`kind=SESSION_CONFIG`。
`hilog -r` 在该环境下清不掉缓冲。

此缺陷在本次排查中三次导致误判（一次作废了 rule3 判别结论，两次误判日志「未打印」）。
正确做法：

```bash
hdc shell hilog > live.txt &          # 运行前启动
SPID=$!
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py ... # 跑测
kill $SPID                            # 运行后停止
grep -c 'role-qos' live.txt           # 同一配置下得到 91031 行完整日志、3 行 role-qos
```

建议将流式抓取固化进 `run_device_stress.py`，否则任何人分析会话启动期行为都会被同样误导。

### 问题一的 A/B 命令

```bash
for arm in off on; do
  FLAG=""; [ "$arm" = "on" ] && FLAG="--diarization-display-may-turn-off"
  hdc shell hilog > live-$arm.txt & SPID=$!
  python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
    --mode diarization-windows --skip-build-install \
    --data-dir <语料目录> --files 0 --cycles 1 \
    --diarization-encoder auto --diarization-hop-ms 2000 --diarization-qos auto $FLAG \
    --output-root runs-$arm
  kill $SPID
  grep -c 'role-qos' live-$arm.txt
done
```

判据：`off` 臂 3 行且内容为 `requested=0 result=0 effective=0`；`on` 臂 0 行。

### 问题二的语料构造

- **稀疏语音臂**：从 `0937.wav` 切出 09:59:30–10:01:30（音频偏移 1348–1468 s），对应客户报告的空档区间
- **连续语音臂**：取真实会议录音并把所有停顿压到 ≤200 ms，使 rule1/rule2 都不触发，从而暴露句长无上限的问题

判据：最大 final 间隔、`source=utterance-length` 是否触发、`kind=SESSION_CONFIG` 中
`rule3UtteranceSec` 的实际取值。

---

## 七、问题仍在时，需要客户提供什么

本节是「装上修订包以后问题还在」时的材料清单。按问题分列，但**第 0 项对三个问题都必需**。

### 0. 最优选项：用 Diagnostics SDK 跑一次复现

包内 `diagnostics-sdk/` 是专门为此准备的。它能产出一样东西是任何其他途径都给不了的：
**每个 session 的 `sdk-input.wav`，即 SDK 实际收到的音频**。有了它，问题二可以一次定性——
到底是麦克风没收到声音，还是 SDK 收到了却没识别出来。目前我方三种干预都停在同一地板，
最可能的解释是前者，但没有这份音频就只能是推断。

做法：把应用依赖临时换成 `diagnostics-sdk/sdk/` 里的 HAR（接口与正式 SDK 完全相同，无需改代码），
复现一次，然后：

```bash
python3 tools/collect_asr_diagnostics.py --device auto --last 1 \
  --bundle <你们的 bundle name> --note "熄屏后仍变慢" --include-all-sessions
```

`--bundle` 必须传你们自己的包名（工具默认读随包 Demo）。多 HAP 应用再加 `--module`。
工具会自己校验、脱敏 hilog、打 ZIP 并给出 SHA-256，直接把那个 ZIP 发回即可。

如果不方便换依赖，也可以只用正式 SDK，按下面第 1 项准备材料——但问题二大概率仍定不了性。

### 0b. hilog 必须在复现期间流式抓取

这一条请务必照做，否则材料会白费。设备 hilog 是按域滚动的缓冲，**事后导出抓不到会话启动期**：
我方实测导出的文件跨了 5 天 8059 行，而当轮的 `AmphionMetrics` 只剩 13 条，
`role-qos`、`kind=LOAD`、`kind=SESSION_CONFIG` 全部丢失。`hilog -r` 在该环境清不掉缓冲。
同一配置下改用流式抓取，得到 91031 行完整日志和 3 行 `role-qos`。

```bash
hdc shell hilog > live.txt &          # 点"开始录音"之前就启动
# 在手机上正常操作：进入会议纪要 → 开始录音 → 复现问题 → 停止
kill %1                              # 停止录音之后再关
```

### 1. 问题一仍在（熄屏后仍然变慢）

| 材料 | 说明 |
| --- | --- |
| 两次对照会话的流式 hilog | 同一台机器、同一段话、相近时长，一次亮屏一次熄屏 |
| 两次会话的原始音频 | 未转码、未重采样、未裁剪 |
| 应用的线程相关调用 | 有没有自己绑核、设置线程 QoS、申请长时任务（continuous task）？有的话给出具体调用和参数 |
| 熄屏期间的 CPU 状态采样（可选但很有用） | 每秒一次：`cat /sys/devices/system/cpu/cpu*/online` 和 `.../cpufreq/scaling_cur_freq` |

partial 间隔不需要你们统计，我方会从 `CALLBACK_RESULT` 自己算。

**先看一眼就能分流：**

| hilog 中的现象 | 含义 |
| --- | --- |
| `role-qos requested=0 result=0 effective=0` 仍有 3 行 | 配置没生效。检查是否传给了 `createEngine`（引擎级，`createEngine` 之后再改无效） |
| 这三行已消失，但仍然慢 | 我方归因不完整。需要上表的 CPU 状态采样继续查 |

另外请一并回传 `kind=SESSION_CONFIG` 那一行，用于确认会话参数与预期一致。

### 2. 问题二仍在（吐字慢）

| 材料 | 说明 |
| --- | --- |
| 流式 hilog + 同一次会话的原始音频 | 两者必须是同一次会话，否则无法对齐 |
| 空档的起止时间 | 用手机本地时间，精确到秒 |
| 那段时间实际说了什么 | 口述大意即可，不需要逐字 |
| 说话人距麦克风多远、是否外放/免提/蓝牙耳机 | 决定输入增益是否够 |
| 录音链路参数 | 采样率、声道数，以及音频是否经过 AEC / 降噪 / AGC |

最有价值的仍是第 0 项的 `sdk-input.wav`。若确实无法提供，退一步的办法是**复现时用另一台设备
或录音机并行录一份**：若并行录音里听得清而 SDK 没出文字，问题在我方；若并行录音里也听不清，
问题在采集链路。

### 3. 问题三仍在（角色结果迟到）

| 材料 | 说明 |
| --- | --- |
| 覆盖整段会话的流式 hilog | 不能只给尾部。我方此前因只拿到尾部日志而得出过错误结论 |
| 会议实际人数 | `maxSpeakers` 上限为 4（见第五节）；超过 4 人时角色结果本身就会不准 |
| 两个回调的到达时间 | `onSpeakerDiarizationUpdate` 与 `onSpeakerDiarizationResult`，应用侧打点即可 |
| 会话总时长 | 权威角色结果按 120 秒提交周期产出，短会话本就会「迟到」。先确认是否属于这种情况 |

### 4. 材料怎么整理

- **一次会话一个目录**，内含 hilog、原始音频、一行说明（时间、机型、系统版本、SDK 版本、
  是否开说话人分离、是否锁屏、现象一句话）。
- **音频不要转码，不要重采样。** 若因会议内容敏感必须裁剪，请**保留空档前后各 2 分钟**
  并说明已裁剪——我方需要这段上下文来判断输入增益和有声占比，裁得太紧就判不了。
- **不要只给截图。** 我方需要可检索的文本日志。
- 日志里如含敏感内容，可自行替换，但请保留 `AmphionMetrics` / `AmphionRuntime` /
  `ASR_STRESS` 这几个标签的行不变——定位全靠它们。
