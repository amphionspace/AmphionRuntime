# 选择 C1 尾音控制架构

- 类型：`wayfinder:prototype`（HITL）
- 状态：open / 参数候选已否决，缓冲候选待验证
- 生产选择仍依赖：`冻结 target-only 产品契约与成功门`
- 路线图：[机主识别下一阶段路线图](../VOICEPRINT_NEXT_STEP_MAP_20260804.md)

## Question

针对“目标人说完、非目标人立即接话”的轮流讲话，哪个最小 coherent change 能在冻结的泄漏/截断门下
通过，同时保持生命周期、分帧无关和跨端语义？至少比较：

1. 参数基线：当前窗口/步长/连续低分与有限的阈值/迟滞扫描，用来量化可达上限，不作为默认答案。
2. **缓冲提交 + 尾部回退/重解码**：在 Speaker VAD 决策前暂存最近窗口，不让未确认尾音进入公开
   ASR；目标离场后丢弃未提交尾音并 final，持续目标则按有界延迟提交。
3. 是否需要把 partial 同样放在确认门后，防止 final 虽干净但非目标 partial 已泄漏到 UI。
4. 对 correctness、final/partial latency、CPU/内存、异常恢复、native/public state boundary、
   Android/Harmony 演进成本逐项比较。

原型必须使用 C1 和独立 target→other 语料，同时保护纯目标连续语音、短停顿、快速换气、纯非目标、
低音量、分帧差异和 finish/cancel/reentrant 生命周期。若只能通过不可接受的目标截断换取低泄漏，应关闭
票据并记录当前单麦/embedding 窗口的上限，而不是把参数写成“修复”。

## 首个候选

`0.2.9` 真机已证明 `1000 ms` 窗、`300 ms` 步长、连续 2 个低分窗、阈值 `0.35` 能让 C1 的
“准备明天去上海”单独放行并阻止“你好”进入放行 final。该结果只解除原型阻塞；在独立 turn 集验证
目标尾字截断、partial 泄漏和相邻生命周期前，不修改 Harmony 正式默认值。

## 独立合成复验（2026-08-05）

已用 `asr/tools/speaker/15_eval_c1_turn_transition_synthetic.py` 在冻结 AISHELL-2
speaker-disjoint enrollment/probe 上执行 target→other 复验。参数固定为 `0.35 / 1000 ms / 300 ms /
连续 2 个低分窗`，没有使用 test 调阈值。30 个 dev、60 个 test target 分别与不同 speaker 配对；
主矩阵覆盖 `-0.3/0/0.3/0.6s` 间隔和 `0.3/0.6/1.0/2.0s` 非目标尾音，另有音量、分帧、
target-only 和 other-only anchor，共 3060 行。

test 主矩阵结果：

- 目标确认率 `100%`；平均非目标音频泄漏 `0.973s → 0.455s`，降幅 `53.24%`。
- 原始 session CER `14.09%`，公开前缀 CER `4.17%`，接近 target-only CER `2.96%`；但
  `30/960` 行仍发布了可归因的非目标文本。
- `16/960` 行发生目标截断，全部来自同一个长目标 probe 的重复场景；独立 target-only anchor
  仍有 `1/60` 在实时 20 ms 下提前 endpoint，不能以矩阵重复解释掉该风险。
- other-only anchor 在实时 20 ms 下有 `2/60` 被误确认，说明冻结 ERes2Net 工作点仍存在开放集误接收。
- 相对实时 20 ms，irregular 分帧 state mismatch `13.33%`、exact endpoint match `26.67%`；
  single-block state mismatch `99.17%`。这与 Android/Harmony 当前每次公开 `writeAudio` 最多处理一个
  跨越 hop 的分数一致，违反同一 PCM 不应随调用方分帧改变决定的不变量。

严格门结论为 **FAIL**：`1000/300 ms` 能明显减少 C1 拖尾，但不能作为正式默认值。legacy 结果同时包含
模型层的目标误拒/非目标误接收和调度层的分帧依赖；后续 absolute replay 已把两层分离。继续在同一
test 上搜索阈值不能解决尾音提交问题，也会污染开放集结论。

## 下一候选

hop 调度修复和冻结重放均已完成，模型层 anchor 仍失败。纯 Speaker VAD 参数路线不再作为默认方案；
下一候选固定为“缓冲提交 + 尾部回退/重解码”，并把 partial 一并置于确认门后。实现前必须冻结最多
可接受提交延迟、回退 PCM 边界以及 finish/cancel/reentrant 时未提交缓冲的归属。

## 缓冲提交实验冻结（2026-08-05）

工具 15 已增加 `--publication-policy buffered_tail_commit`，只改变离线公开前缀的选择，不改
`0.35 / 1000/300 ms / 连续 2 窗` 和 score timeline。策略固定如下：

- 保留 `2 × 300 ms = 600 ms` 尾部；持续目标的已提交 partial 稳态最多延迟 600 ms，首次 partial 仍须
  等 1 秒窗口确认目标。
- 两个低分窗确认离场时丢弃保留尾部，只用提交前缀重新解码并形成 final；不允许已丢弃文本进入 partial。
- 显式 `finish` 时，若没有未决低分则提交尾部；已有一个未决低分则丢弃尾部；从未确认目标则拒绝。
- `cancel` 丢弃未提交缓冲且不产生 final/complete；reentrant 写入仍归当前串行 session 队列。离线工具
  只验证 PCM 水位和重解码文本，生命周期后置条件留给进入 SDK 实现后的状态机/真机门。

Linux 使用同一 baseline、模型哈希、seed 和新目录执行：

```bash
python asr/tools/speaker/15_eval_c1_turn_transition_synthetic.py \
  --baseline-dir <frozen-baseline-dir> \
  --speaker-model <eres2net.onnx> \
  --asr-model-dir <ZH_EN-model-dir> \
  --output-dir <new-buffered-tail-result-dir> \
  --score-schedule absolute_samples \
  --publication-policy buffered_tail_commit
```

停止条件不变：`target truncation > 0`、`published other text > 0`、target-only 提前 endpoint 或
other-only 误确认任一出现即为 **FAIL**，关闭无训练 C1 正式默认路线；不以扩大 holdback、改阈值或
覆盖旧 artifact 规避失败。

## Hop 调度修复状态（2026-08-05）

Android/Harmony 已新增同语义的 `SpeakerVadScoreScheduler`：评分终点锚定 native segment 内的绝对 PCM
sample；一次大块写入会在喂入 ASR 前切到每个 score deadline，endpoint 后的剩余 PCM 由重置后的新段
继续处理。没有修改 `0.35 / 1000/300 ms / 连续 2 窗`、ERes2Net 或 final 状态机。

修复前红灯证明 320-sample、irregular、single-block 对同一 32000-sample PCM 产生不同时间线；修复后
三种分块均固定为 `16000/19200/24000/28800`。Android Debug/Release 的 `sdk`、`sdk-dingqiao`
单测和 Harmony `amphion_asr`、`amphion_dingqiao` HAR 编译通过；Python/Harmony 相邻状态测试 31 项通过。

冻结 3060 行 `absolute_samples` replay 已在保留 baseline/trials 的 Linux 服务器完成。2340 条实时路径
与 legacy 逐行一致；720 条 irregular/single-block 对照全部与实时参考一致，state mismatch 从
`13.33%/99.17%` 降到 `0%/0%`，exact endpoint match 均为 `100%`。这证明调度修复没有改变实时路径，
且消除了调用方分帧依赖。

严格业务门仍为 **FAIL**：test 主矩阵仍有 `16/960` 目标截断和 `30/960` 非目标文本；target-only
仍有 `1/60` 提前 endpoint，other-only 仍有 `2/60` 误确认。结果符合修复前对模型层 anchor 的预测，
因此调度票据可以收口，参数候选保持否决，下一实验进入缓冲提交/尾部回退。

absolute ignored artifact 为
`asr/tools/speaker/results/voiceprint_pilot_20260805_c1_turn_transition_absolute_full/`；`summary.json` /
`trials.jsonl` SHA256 分别为 `93edbfb5…dfc2` / `3387daf7…94c3`。当前 USB 设备 `7GK…5655` 不在任何
本地授权清单中，签名 HAP 构建/安装仍在 license 校验前停止；没有修改白名单、重签或覆盖设备产物。
本轮没有覆盖 Silero/ASR 更早 endpoint、真实设备声学或 `isLast/onComplete/cancel` 真机生命周期。

## Harmony 真机生命周期补验（2026-08-05）

设备 `VYG-AL30 / HarmonyOS 6.1.0.135` 已加入本机私有 demo 授权，授权文件和完整设备标识未提交。
分支 `94e8e8c` 仅构建、签名并安装 `ZH_EN` HAP；模型、native、签名、license、安装和 runtime-ready
smoke 全部通过。被测 HAP SHA256 为
`a41bba39067f9e9edaee363044420453173b1a5c9d7b7086fb132010893cce64`。

先误用 `voiceprint-fallback/000_enroll.wav` 执行 `speaker-vad-onstart`。该文件总长 3.28 秒，但按
20 ms 能量窗统计只有约 0.70～0.94 秒活动，低于 `minSegSec=1.5`；4 轮因此都没有满足“足够长的
同源有效语音必须产生带分数非空 final”的输入前提。失败 artifact
`20260805-160056-speaker-vad-onstart-9c5c8491` 保留，不把它覆盖或归因为 SDK 回归。

纠正后从固定 `001_recognize.wav` 截取 `[0.5s, 3.5s)` 作为同源注册/识别输入；SHA256 为
`247c08578ef2bb7beb0ba33632643ede15f85b46264300a1fe683757db5c0815`，前 200 ms RMS 为
`0.022`，3 秒内约 2.22 秒活动。`speaker-vad-onstart` 的 burst/paced × 直接起音/800 ms 前置静音
四种组合 **4/4 PASS**：每轮第一条非空 final 都有 `speakerSimilarity`，显式 `finish` 前
`isLast=0`，结束时恰好一次 last/complete，无 error、跨 session 回调或 live native stream，并且每轮
都能立即启动并取消恢复 session。RSS `+8.914 MiB`、线程 `-6`，按硬门 PASS；观察仅 21.8 秒，资源
斜率仍为 `INCONCLUSIVE`。有效 artifact 为
`20260805-160600-speaker-vad-onstart-80ad4882`。

该补验关闭了“绝对 PCM hop 调度是否破坏 Harmony 公共 API 生命周期/运行期开关”的风险，不改变
参数候选的业务 **FAIL**：它没有客户 C1 原始 PCM，不证明尾音泄漏已解决，也不替代完整发布真机矩阵。
下一步仍是 Linux 冻结集的 `buffered_tail_commit` 全量 replay，而不是重复真机 Speaker VAD 参数矩阵。
