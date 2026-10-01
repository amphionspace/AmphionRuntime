# ASR 开放 PR 后续工作与验收边界

2026-09-29：原开放范围的 #228、#229、#237、#241 已合入 main；#203 被 #228 替代、#206 被 #229 替代，均已关闭。本文承接这些 PR 明确留下的问题及其引用的历史记录。**代码合入不代表角色分离正式交付；当前交付仍 BLOCKED。** 本文用于持续更新，不以文档合入关闭下面的运行问题。

## 已落地主线的工作

| 来源 | 合入提交 | 已完成范围 |
| --- | --- | --- |
| [#237](https://github.com/amphionspace/AmphionRuntime/pull/237) | `5d2528a3` | 资源报警解释；保留原始测量、硬失败和 INCONCLUSIVE。 |
| [#229](https://github.com/amphionspace/AmphionRuntime/pull/229) | `90ac8ceb` | Android VAD 起音补发；Debug/Release 单测及当前 CI native 库的 24 项真机用例通过。短/长语音结束延迟 1680/1618 ms，不声明严格 800 ms SLA。 |
| [#228](https://github.com/amphionspace/AmphionRuntime/pull/228) | `ec25a879` | 显式离线包授权与旧授权兼容；Android ASR/TTS 各 7 项签名授权真机测试、Harmony 12 场景核心授权门禁及各平台构建通过。Harmony 授权门禁不等于 ASR/TTS 推理验收。 |
| [#242](https://github.com/amphionspace/AmphionRuntime/pull/242) | `e742301a` | 分开静音音频截止与异步回调排空；原载体错误计入截止后被忽略的音频帧。没有放宽截止断言。 |
| [#241](https://github.com/amphionspace/AmphionRuntime/pull/241) | `acf477c2` | UNKNOWN 回退、Harmony 文字归属；补齐 Android 构建、单测与现有窗口路径真机验证。最终 HAP 的 4 轮静音和 19.58 s 四人 SDK 用例通过，4 HAR 的 API 23 实际内容检查通过。 |

这些 PR 的全部 review threads（含 suggestion）、reviews、行内评论和 issue comments 均已拉取；合入时数量为 0。这不是人工 APPROVED 的替代说明。

## 独立修复 PR

| 项目 | 当前工作 | 尚未满足的完成条件 |
| --- | --- | --- |
| 普通口语“这这”误改为“浙J” | [#243](https://github.com/amphionspace/AmphionRuntime/pull/243)：两端只在完整车牌可解析时替换；原用例红灯，Harmony 803 例通过，Android Debug/Release 各 518 通过、2 项原有跳过。2026-09-29 补齐门禁：Mate80 真机在 `219075d9` 跑完 API 23 内容检查（4 个 HAR）与 10 段输入，raw 文本与声学轮次同基线一致，只出现 3 处预期回退、0 处意外改动、无 span 字符为 0；主机差分 44,956 条语料的 4,802 处变化全部为纯回退，20,160 例车牌召回 0 丢失。报告见该 PR 的 `docs/speaker/DIARIZATION_PLATE_CONTEXT_DEVICE_20260929.md`。 | 门禁已完成，待该 PR 合入后本行转入上表。通用冒烟仍因设备缺少 RECORD_AUDIO 权限失败，属既有问题，不构成本项结论，也不替代 D1 的界面验收。 |
| Android CT 空格对齐 | [#244](https://github.com/amphionspace/AmphionRuntime/pull/244)：同步 Harmony 的中英空格/标点替代规则，保留英文粘连和无 provenance 改词时的 UNKNOWN。旧实现红灯，Debug/Release 各 130 项及 Release AAR 通过。2026-09-29 补齐调用方验证：真机 A/B（`acf477c2` 对 `c27faac5`，相同忽略构建输入）三段定向输入均未降级，声学轮次与最终结果逐项一致，9 句中 7 句由 -1 变为具名角色。报告见该 PR 的 `docs/speaker/DIARIZATION_ANDROID_TEXT_ALIGNMENT_20260929.md`。 | 调用方验证已完成，待该 PR 合入后本行转入上表。剩余 2 句已定位且与对齐无关：一句的覆盖声学轮次本身是 UNKNOWN，另一句命中既有 overlap 规则并受 A1 影响。验证设备算力低，超过约 20 s 的输入两端都 FINISH_TIMEOUT，性能以 Mate80 为准，本项不给性能结论。此项仍不涵盖下面的完整 Android 差异。 |

## 仍需实施或裁定的项目

| ID | 来源与当前证据 | 下一步与关闭条件 |
| --- | --- | --- |
| A1 Android 改写位置追踪 | #241；Harmony 已通过 `PoliceTextTrace` 保留原文到改写文字的位置，Android 尚未实现。无记录的改词仍会失去 token 对齐。 | 先以术语、车牌、人名、派出所各自的真实改写建立失败样例，再沿同一原句传递位置记录；记录能逐字重建输出、改写区间不可拆、无记录不猜。验证公共原句、时间区间和最终调用方呈现，保持两端警务输出一致。 |
| A2 Android run 级声学证据 | 检查 `CommunityDiarizationInference.kt`：窗口只有 segments/embeddings，cluster 没有 Harmony 的 runEmbeddings/runRanges/runRms 参数。现有 Android 真机聚类一致性仅证明旧窗口路径可用。 | 首先比较同一输入两端的 window/run 输出，锁定第一个差异；同步 JNI 数据归属、有效范围和释放生命周期后，以同一捕获窗口和真实 PCM 做逐项对照。不能把共享 C++ 编译通过等同于该路径已调用。 |
| Q1 逐段误认与换号 | #241 接受的是合计不差于官方。公开 6 段误认从 base 10.69 s 增至 32.25 s（官方 44.19 s），换号 15→27（官方 56）；AliMeeting 四人和独立 M1/M2 分别比官方多 2.94/5.88/0.27 s。 | 已知代价不应隐藏。使用已有分歧帧和标注，分别定位 overlap、run 缺证据及身份注册表的首次分叉；只有有证据的局部修复才新增代码。保护公开集、独立留出集和真实短插话，分开报告误认与未知，不用 UNKNOWN 减少证明身份正确。 |
| Q2 客户四主讲人 UNKNOWN | #241/#235；客户录音可见 UNKNOWN 仍为 36.6%，剩余证据指向声学 turns，文字整句缺 span 已由 1206 字降到 0。 | 复用已有 MOSS 辅助标注及争议清单，从缺失轮次定位声学层；只保证已明确的四位较响主讲人，轻声/背景允许 UNKNOWN 且不能占用其名额。辅助标注不能当人工真值，客户原音未验证部分不能用替代语料结案。 |
| R1 内存稳定性 | #237/#241/#235；历史 paced 增长约 102.9 MiB，前序 paced/voiceprint-fallback 为 85.650/68.113 MiB，混有模型驻留及释放阶段。 | 复用内存采样，先标出加载、稳定识别、释放阶段；比较相同阶段后再决定是否需要一轮有假设的长会议验证。原通用 FAIL 保留，资源保持 INCONCLUSIVE；不放宽显式预算、线程或生命周期门禁。 |
| R2 实时性结论 | #241 最新 10 输入中 6 项 INCONCLUSIVE：AISHELL-4 二人、AliMeeting 二/四人、124 s 四人、20 s 四人、47.8 s 单人，涉及观察不足及尾延迟变化。 | 先复核既有逐窗口时间线、累计解码、排队及尾延迟证据。短于观察窗不得给稳定性 PASS；没有同产物对照不能断言回归；平均 RTF 不能代替积压与尾部延迟。 |
| D1 最终交付 | #241/#237/#235；完整 16 段实录、长会议、最终发布矩阵、真实调用方界面截图未完成；本次通用 UI 冒烟因录音权限缺失未通过，文件 SDK 用例不替代麦克风体验。 | 修复相关运行问题后冻结最终提交/授权/签名/组包，按 `ASR_VALIDATION.md`、默认交付规范运行一次完整矩阵并归档；复用同产物有效证据。接口契约、身份精度、可读性及界面结果分开给结论，核心体验失败即阻断交付。 |

## 引用的历史问题：尚无当前缺陷或关闭证据

以下来自 [#204](https://github.com/amphionspace/AmphionRuntime/pull/204)、[#207](https://github.com/amphionspace/AmphionRuntime/pull/207) 和 [SEPT14_FEEDBACK_TRIAGE.md](../../delivery/harmony-dingqiao/docs/SEPT14_FEEDBACK_TRIAGE.md)。本轮未逐项复现，不把旧记录直接当作当前 HEAD 缺陷。

| 历史记录 | 继续处理的证据要求 |
| --- | --- |
| 四轮无 VAD begin/end、38/41 句 UNKNOWN、无增量 update | 需客户原 PCM、构建身份、完整调用与回调；同类修复通过不能宣称原会话关闭。 |
| 后台吞吐下降及长会话积压 | 将实际前/后台状态与 accept/decode/result/finish 时间轴对应；结束截断修复不证明后台实时性。 |
| Harmony RTF 漏计流式解码 | 先核对当前统计点及累加范围；单次末尾 drain 耗时不能代表整句成本。 |
| 核心 VAD 大块混合输入遗漏尾静音 | 在核心 SDK 用同 PCM 整块/分块对照；鼎桥 640 字节接口约束不能覆盖核心接口。 |
| 客户原始声纹注册音频缺失 | 保留替代注册测试的边界；获得原始条件后才可裁定该会话的偶发分支。 |
| 旧离线说明与文档提交影响构建身份复用 | 核对当前实现和实际产物哈希；不能据过时服务化说明否定已存在的端侧实现，也不能改提交号伪造产物身份。 |

## 证据及执行顺序

- 精度、文字归属：[UNKNOWN 回退报告](../speaker/DIARIZATION_UNKNOWN_FALLBACK_20260928.md)、[文字归属报告](../speaker/DIARIZATION_SPEAKER_SPAN_PROVENANCE_20260928.md)及其 `docs/speaker/evidence/` 哈希索引。
- 本轮主线合入证据位于 `~/.cache/amphion-runtime/pr-completion-20260929/` 的各 PR 目录；失败调用及无效载体现场保留。原始 PCM、完整转写、embedding、私钥和授权文件不提交。
- #243 的 Harmony 平台门禁与 #244 的调用方验证已于 2026-09-29 完成，证据分别在 `~/.cache/amphion-runtime/diagnostics/pr243-harmony-20260929/` 和 `pr244-android-20260929/`，两个 PR 仍待合入；接着按 A1/A2 做独立根因与修复；Q1/Q2、R1/R2 先复用现有证据定位。D1 在最终产物冻结后执行，不能为了补文档反复跑发布矩阵。
- 此文档的检查只需链接/事实及差异核对。后续运行代码的测试按各项具体风险选择，不把清单视为已执行结果，也不以关闭本 PR 关闭未完成项。
