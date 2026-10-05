# ASR 开放 PR 后续工作与验收边界

2026-09-29：原开放范围的 #228、#229、#237、#241 已合入 main；#203 被 #228 替代、#206 被 #229 替代，均已关闭。本文承接这些 PR 明确留下的问题及其引用的历史记录。**代码合入不代表角色分离正式交付；当前交付仍 BLOCKED。** 本文用于持续更新，不以文档合入关闭下面的运行问题。

2026-10-05：#243、#244 已合入，转入下表；#253–#255 处理了角色分离的息屏变慢与长会议饱和，相关进展记在 R2 和历史问题中。

## 已落地主线的工作

| 来源 | 合入提交 | 已完成范围 |
| --- | --- | --- |
| [#237](https://github.com/amphionspace/AmphionRuntime/pull/237) | `5d2528a3` | 资源报警解释；保留原始测量、硬失败和 INCONCLUSIVE。 |
| [#229](https://github.com/amphionspace/AmphionRuntime/pull/229) | `90ac8ceb` | Android VAD 起音补发；Debug/Release 单测及当前 CI native 库的 24 项真机用例通过。短/长语音结束延迟 1680/1618 ms，不声明严格 800 ms SLA。 |
| [#228](https://github.com/amphionspace/AmphionRuntime/pull/228) | `ec25a879` | 显式离线包授权与旧授权兼容；Android ASR/TTS 各 7 项签名授权真机测试、Harmony 12 场景核心授权门禁及各平台构建通过。Harmony 授权门禁不等于 ASR/TTS 推理验收。 |
| [#242](https://github.com/amphionspace/AmphionRuntime/pull/242) | `e742301a` | 分开静音音频截止与异步回调排空；原载体错误计入截止后被忽略的音频帧。没有放宽截止断言。 |
| [#241](https://github.com/amphionspace/AmphionRuntime/pull/241) | `acf477c2` | UNKNOWN 回退、Harmony 文字归属；补齐 Android 构建、单测与现有窗口路径真机验证。最终 HAP 的 4 轮静音和 19.58 s 四人 SDK 用例通过，4 HAR 的 API 23 实际内容检查通过。 |
| [#243](https://github.com/amphionspace/AmphionRuntime/pull/243) | `f7aeba28` | 普通口语“这这”不再被改成“浙J”：两端只在完整车牌可解析时替换。Harmony 803 例、Android Debug/Release 各 520 项（2 项原有跳过）通过；Mate80 在 `219075d9` 的 10 段输入只出现 3 处预期回退；44,956 条主机差分的 4,802 处变化全为纯回退，车牌召回 0 丢失。Android 只有主机单测，没有真机验收。 |
| [#244](https://github.com/amphionspace/AmphionRuntime/pull/244) | `b9c61a64` | Android CT 空格对齐与 Harmony 一致；英文粘连和无 provenance 改词仍为 UNKNOWN。新增真实换人处删空格的用例，Debug/Release 各 142 项通过。KI8 调用方 A/B 中 9 句有 7 句由 -1 变为具名角色；剩余 2 句与对齐无关（一句声学轮次为 UNKNOWN，一句命中 overlap 且受 A1 影响）。 |
| [#253](https://github.com/amphionspace/AmphionRuntime/pull/253) | `0c7bab72` | Harmony 声纹 encoder 改为两路单线程并行、低于识别的线程优先级，去掉 4 线程 XNNPACK 池的忙等；息屏且角色运行时 ASR 处理量约多 50%。 |
| [#254](https://github.com/amphionspace/AmphionRuntime/pull/254) | `b3324dbc` | Harmony 预览聚类按自身开销限流，定稿结果不变。 |
| [#255](https://github.com/amphionspace/AmphionRuntime/pull/255) | `5d540d08` | 两端改用 per-channel INT8 encoder，主机身份精度与 FP32 持平。nova 16 分钟会议收尾 3.8 s、整进程 CPU 比 main 低 49%；KI8 180 s 会议不再收尾超时。 |

这些 PR 的全部 review threads（含 suggestion）、reviews、行内评论和 issue comments 均已拉取。#228–#242 合入时数量为 0；#243 的 1 条和 #244 的 3 条已逐条修复后解决，#253–#255 为 0。这不是人工 APPROVED 的替代说明。

## 仍需实施或裁定的项目

| ID | 来源与当前证据 | 下一步与关闭条件 |
| --- | --- | --- |
| A1 Android 改写位置追踪 | #241；Harmony 已通过 `PoliceTextTrace` 保留原文到改写文字的位置，Android 尚未实现。无记录的改词仍会失去 token 对齐。 | 先以术语、车牌、人名、派出所各自的真实改写建立失败样例，再沿同一原句传递位置记录；记录能逐字重建输出、改写区间不可拆、无记录不猜。验证公共原句、时间区间和最终调用方呈现，保持两端警务输出一致。 |
| A2 Android run 级声学证据 | 检查 `CommunityDiarizationInference.kt`：窗口只有 segments/embeddings，cluster 没有 Harmony 的 runEmbeddings/runRanges/runRms 参数。现有 Android 真机聚类一致性仅证明旧窗口路径可用。 | 首先比较同一输入两端的 window/run 输出，锁定第一个差异；同步 JNI 数据归属、有效范围和释放生命周期后，以同一捕获窗口和真实 PCM 做逐项对照。不能把共享 C++ 编译通过等同于该路径已调用。 |
| Q1 逐段误认与换号 | #241 接受的是合计不差于官方。公开 6 段误认从 base 10.69 s 增至 32.25 s（官方 44.19 s），换号 15→27（官方 56）；AliMeeting 四人和独立 M1/M2 分别比官方多 2.94/5.88/0.27 s。 | 已知代价不应隐藏。使用已有分歧帧和标注，分别定位 overlap、run 缺证据及身份注册表的首次分叉；只有有证据的局部修复才新增代码。保护公开集、独立留出集和真实短插话，分开报告误认与未知，不用 UNKNOWN 减少证明身份正确。 |
| Q2 客户四主讲人 UNKNOWN | #241/#235；客户录音可见 UNKNOWN 仍为 36.6%，剩余证据指向声学 turns，文字整句缺 span 已由 1206 字降到 0。 | 复用已有 MOSS 辅助标注及争议清单，从缺失轮次定位声学层；只保证已明确的四位较响主讲人，轻声/背景允许 UNKNOWN 且不能占用其名额。辅助标注不能当人工真值，客户原音未验证部分不能用替代语料结案。 |
| R1 内存稳定性 | #237/#241/#235；历史 paced 增长约 102.9 MiB，前序 paced/voiceprint-fallback 为 85.650/68.113 MiB，混有模型驻留及释放阶段。 | 复用内存采样，先标出加载、稳定识别、释放阶段；比较相同阶段后再决定是否需要一轮有假设的长会议验证。原通用 FAIL 保留，资源保持 INCONCLUSIVE；不放宽显式预算、线程或生命周期门禁。 |
| R2 实时性结论 | #241 最新 10 输入中 6 项 INCONCLUSIVE：AISHELL-4 二人、AliMeeting 二/四人、124 s 四人、20 s 四人、47.8 s 单人，涉及观察不足及尾延迟变化。#253–#255 后，nova 960 s 亮屏会议收尾 3.8 s，KI8 三段 180 s 会议都正常收尾（[调查记录](../speaker/DIARIZATION_SCREEN_OFF_AND_HEAT_20261004.md)）；Mate80、Android 更长会议和逐窗口尾延迟仍未复核。 | 先复核既有逐窗口时间线、累计解码、排队及尾延迟证据。短于观察窗不得给稳定性 PASS；没有同产物对照不能断言回归；平均 RTF 不能代替积压与尾部延迟。 |
| D1 最终交付 | #241/#237/#235；完整 16 段实录、长会议、最终发布矩阵、真实调用方界面截图未完成；本次通用 UI 冒烟因录音权限缺失未通过，文件 SDK 用例不替代麦克风体验。 | 修复相关运行问题后冻结最终提交/授权/签名/组包，按 `ASR_VALIDATION.md`、默认交付规范运行一次完整矩阵并归档；复用同产物有效证据。接口契约、身份精度、可读性及界面结果分开给结论，核心体验失败即阻断交付。 |

## 引用的历史问题：尚无当前缺陷或关闭证据

以下来自 [#204](https://github.com/amphionspace/AmphionRuntime/pull/204)、[#207](https://github.com/amphionspace/AmphionRuntime/pull/207) 和 [SEPT14_FEEDBACK_TRIAGE.md](../../delivery/harmony-dingqiao/docs/SEPT14_FEEDBACK_TRIAGE.md)。本轮未逐项复现，不把旧记录直接当作当前 HEAD 缺陷。

| 历史记录 | 继续处理的证据要求 |
| --- | --- |
| 四轮无 VAD begin/end、38/41 句 UNKNOWN、无增量 update | 需客户原 PCM、构建身份、完整调用与回调；同类修复通过不能宣称原会话关闭。 |
| 后台吞吐下降及长会话积压 | 将实际前/后台状态与 accept/decode/result/finish 时间轴对应；结束截断修复不证明后台实时性。2026-10-04 已在 nova 定位：角色分离 4 线程池忙等抢占 ASR，#253 修复；但 nova 后台降频下只开 ASR 也只有约 0.27 倍实时，属于平台约束，需在 Mate80 复核（见 R2 链接的调查记录）。 |
| Harmony RTF 漏计流式解码 | 先核对当前统计点及累加范围；单次末尾 drain 耗时不能代表整句成本。 |
| 核心 VAD 大块混合输入遗漏尾静音 | 在核心 SDK 用同 PCM 整块/分块对照；鼎桥 640 字节接口约束不能覆盖核心接口。 |
| 客户原始声纹注册音频缺失 | 保留替代注册测试的边界；获得原始条件后才可裁定该会话的偶发分支。 |
| 旧离线说明与文档提交影响构建身份复用 | 核对当前实现和实际产物哈希；不能据过时服务化说明否定已存在的端侧实现，也不能改提交号伪造产物身份。 |

## 证据及执行顺序

- 精度、文字归属：[UNKNOWN 回退报告](../speaker/DIARIZATION_UNKNOWN_FALLBACK_20260928.md)、[文字归属报告](../speaker/DIARIZATION_SPEAKER_SPAN_PROVENANCE_20260928.md)及其 `docs/speaker/evidence/` 哈希索引。
- 本轮主线合入证据位于 `~/.cache/amphion-runtime/pr-completion-20260929/` 的各 PR 目录；失败调用及无效载体现场保留。原始 PCM、完整转写、embedding、私钥和授权文件不提交。
- #243 的 Harmony 平台门禁与 #244 的调用方验证证据分别在 `~/.cache/amphion-runtime/diagnostics/pr243-harmony-20260929/` 和 `pr244-android-20260929/`，两个 PR 已于 2026-10-05 合入；接着按 A1/A2 做独立根因与修复；Q1/Q2、R1/R2 先复用现有证据定位。D1 在最终产物冻结后执行，不能为了补文档反复跑发布矩阵。
- 此文档的检查只需链接/事实及差异核对。后续运行代码的测试按各项具体风险选择，不把清单视为已执行结果，也不以关闭本 PR 关闭未完成项。
