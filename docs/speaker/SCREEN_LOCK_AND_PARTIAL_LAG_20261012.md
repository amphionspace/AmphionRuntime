# 锁屏变慢与吐字慢：归因、改动与待客户验证项

日期：2026-10-12 · 版本：0.3.22 · 设备：Kirin 9020（客户与我方同型）

针对 0.3.22 现场反馈的两个问题给出根因、已完成的改动、以及需要客户配合完成的验证。
两个问题的根因都在 SDK 内部，不是集成方式或设备差异。

数据来源：客户提供的 60 分钟会议录音（`0937.wav`）与对应 hilog（5 个文件 26 MB）、
20:34 锁屏复现录音（`2034.wav`）与 hilog（3 个文件 14 MB），以及我方在同型设备上的对照实测。

---

## 一、根因

### 问题一：锁屏后识别变慢约 3 倍

角色分离的工作线程被默认放在 `QOS_BACKGROUND`。

```ts
// AsrSchedulingConfig.ts
return diarizationHopMs >= 2000 ? 'background' : 'inherit';
```

`diarizationQos` 默认 `auto`，`diarizationHopMs` 默认 `2000`，于是解析成 `background`。
客户日志里的 `role-qos requested=0 result=0 effective=0` 正是这个（`QOS_BACKGROUND = 0`）。

**关键影响：background QoS 隐含 background cpuset，所以应用侧配置的绑核大核拼不过它。**
此前观测到的「熄屏后 85 个线程被改写到 cpu 0–3」不是内核无视绑核，而是 SDK 自己先申请了
background。

SDK 注释中已记录该风险：background 在亮屏下把最坏情况 embedding 从 647 ms 拉到 1421 ms，
对 1500 ms 的窗口预算只剩 5% 余量，并注明「a slower part or heavier throttling would start
dropping windows」。熄屏移除大核集群，正是它所说的 heavier throttling。

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

### 验证状态

**问题一：机制已在设备上验证。** A/B 对照（同一构建、同一语料、亮屏、运行期间流式抓取 hilog）：

| 臂 | `role-qos` 行数 | 内容 |
| --- | --- | --- |
| 默认（`displayMayTurnOff=false`） | 3 | `requested=0 result=0 effective=0` |
| 开启（`displayMayTurnOff=true`） | **0** | 无 |

默认臂逐字复现了客户日志中的那一行；开启后 SDK 不再申请降档，应用侧的绑核大核不会再被覆盖。

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

### 1. 问题一：加一行配置并回传验证结果

```ts
scheduling.displayMayTurnOff = true;   // 会议纪要等可能熄屏继续录音的会话
params.scheduling = scheduling;
```

该改动默认关闭，不加则行为与现状完全相同（这样亮屏场景保留 background 的控热收益，
实测省 55.9 个 CPU 百分点）。

**请在熄屏场景重跑并确认两点：**

- hilog 中 `role-qos requested=0 result=0 effective=0` 这三行**消失**
- 锁屏期间 partial 间隔是否回到 0.45 s 量级（而非 1.36 s）

第二点我方无法验证——熄屏测试在我方环境不可靠，这正是该问题最初被搁置的原因。
观测点在客户侧：你们的日志里有这三行，我方压测环境的日志抓取反而看不到会话启动期。

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
| 问题一的熄屏症状 | **未验证** | 仅验证了「不再申请 background QoS」，未验证「因此变快」。需客户在熄屏场景确认 |
| 问题一的改动生效条件 | **需客户配合** | 默认 `false`，客户不加配置则无变化 |
| 问题二的主要症状 | **仍在** | 最大空档从 105 s 降到 72.5 s，用户仍会看到长时间无输出 |
| 问题二残余的归因 | **待客户确认** | 「该段无可转写语音」证据较强（三臂同一地板）但未经客户确认 |
| 问题二 25 秒上限的覆盖 | **有限** | 上限要求当前已有文字；解码器无文字时上限不生效，这正是残余空档的成因 |

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
