# 标点与 ITN 后处理的原句角色对齐

本轮修复 SDK 的证据边界，不修改模型、聚类、窗口、hop、预览、定稿周期或 timeout。此前时间轴与完整 session 证据修复继续保留。声学身份与 overlap 的既有失败独立跟踪，本补丁不宣称角色分离整体精度通过。

## 第一个错误状态

原始录音长 47.82 秒；UNKNOWN 是“你好。”3 个字符，不是 3 秒。原生 u6 为“可以听见我说话吗？你好。”，末两字 token 在 20.660/20.860 秒，附近声学区间止于 20.65221875 秒。

生产 `sentenceUtterances` 先 `punctuationUnits`，再按展示分句进行角色关联及 UNKNOWN 补全。这一步错误地把问号当成证据边界。固定 tokens、时间、声学区间，仅去掉问号就改变归属的回归在修改前稳定失败。

修复后先在原始 utterance 内计算直接关联与有限推断，再把已计算结果按精确源偏移投影到展示分句。“你好”符合既有 2500 ms 同原句规则，标记 `speakerInferred=true`、`confidence=0`；原始 `speakerTurns` 不延长。展示合并或 UNKNOWN 汇总也不能丢失推断标记。

另外移除无覆盖 token 直接继承整句唯一角色的路径：缺少声学覆盖先保持 UNKNOWN，只能由已有有限规则补全。Android 原本没有按标点先分句，但同步移除这一路径并保留推断标记。

## 精确映射和不确定性

BBPE 到原文的逐字节核验与原生时间映射保留；插入标点、空白以及标点替换词间空格使用已有精确映射。原生 token 的关联及推断不依赖展示文字。

当前 Wetext ITN 与标点接口只返回字符串，没有转换来源区间。移除以最小编辑距离猜测词语改写后分句边界的路径。数字合并、展开、替换、重复删除等无法精确追溯时，转换后的整句保持 UNKNOWN、confidence=0，并保留 rawText 与 speakerTurns；不均匀分配时间，不复制邻句身份，不覆盖多数角色。

同一原句中的展示段可以因分句方式不同而汇总为不同粒度；这不重新运行原始 token 的归属。混合角色、真实短插话及 overlap 保留声学区间，不能用 UNKNOWN 减少证明身份正确。

## 验证

- Harmony 87 项相关回归中 86 项首次通过；剩余定稿测试夹具缺少必需 rawText，补齐原生输入后单项通过。公共 SDK 与真实 Demo 展示方法的附加回归通过，显示“说话人 1 · 含推断补全”。
- Android SDK / dingqiao Debug 与 Release 共 381 项单测通过；归档门禁在冻结提交后执行全部 128 个 Gradle 任务。新增标点同输入及无映射 ITN 测试修改前均失败，修改后通过。
- 相邻场景：真实换人、短插话、同角色未知空隙、不同角色间未知、2500/2501 ms、零时长尾字、已知/未知副角色、无来源 overlap、跨原始 utterance、数字合并/展开/替换、重复文本映射不明、冻结和回调生命周期。
- 复用同设备 600 秒原始事件顺序及真实 segmentation/embedding，按设备聚类返回时序回放生产 Session/Clock/Identity/Transcript。62 次聚类调用、6 次定稿；每批 speakerTurns 完全相同，5436 字符及 SHA-256 不变，冻结、文本守恒和唯一结束断言通过。没有重新做模型长跑，桌面回放耗时不作为手机性能证据。
- 长样本展示 UNKNOWN 从 113 增为 426 字符。原因包括无覆盖 token 不再被无标记继承，以及 u32 原生尾部 UH 被文字后处理删除、无法精确追溯，整句保留未知。含推断标记的展示段覆盖 1580 字符，这不是新增声学已知字符数。声学误认仍为原有 1.70 秒，参考 overlap 召回仍为 0%，不是本次对齐引入，也没有被修复。

本地证据：`~/.cache/amphion-runtime/diagnostics/single-speaker-unknown-20260927/punctuation-alignment/`，包含 protocol.json、u6-red.log、harmony-regressions.log、cadence-fixture-green.log、presentation-invariants.log、caller-result.log、android-red.log、android-green.log、replay-long.log、replay-120000-recorded.json、long-differential.json。失败现场保留，不将其覆盖为通过。

## 原始录音同设备复验

Mate80，同一原始 WAV（SHA-256 `f3dd598f8fffd76b8877f59809432d98b5d2ab72c5c22badadb26e9923ad186a`），同参数、实时 20 ms 帧；运行代码冻结于 `185414b522976dd890a63f810ccfbb7d7f16f177`，ZH_EN diagnostics HAP。

| 指标 | 修复前 `9053566e` | 修复后 `185414b5` |
| --- | ---: | ---: |
| 原生原句 / 展示字符 | 11 / 125 | 11 / 125 |
| 最终说话人数 | 1 | 1 |
| UNKNOWN 展示字符 | 3 | 0 |
| 首次预览 | 10.760 s | 10.710 s |
| 最终声学区间末尾 | 44.834 s | 44.834 s |
| finish 到 complete 的诊断间隔 | 852 ms | 888 ms |
| u6“你好”处理 | 标点隔离后 UNKNOWN | 原句内规则推断，confidence=0 |

全部 `speakerTurns` 逐项相同，文本 SHA-256 仍为 `d354f6556d0df8a1c33e4f817725246acf8cf8eaf19cb2fd116e55a57b2f5853`。u6 保留问号，不改 ASR 文字；10 条包含无声学覆盖尾部的原句现在明确标记含推断，不能把它们算成直接声学确认。用户提供的单人身份只验证该症状，不推导泛化精度。

20 个模型窗口完整，推理均值 552.75 ms、最大 634.01 ms；完成处音频延迟均值 581 ms、最大 680 ms，pending 最大 0，ASR 队列峰值 51 帧。预览 4 次共 22 ms，定稿 1 次 180 ms。调用方停止等待 956 ms（与诊断 finish 事件时钟不同），无 error 和空 endpoint；独立空终止 last 保留原契约，finish 前 last=0，之后唯一 last 再唯一 complete，native stream=0。此短录音不能证明长期 RSS 平台。

手机实际定稿 payload 送入未修改的 Demo `handleSpeakerDiarizationResult` 与标签方法，11 条完整原句保留；u6 显示“说话人 1 · 含推断补全”。这是实际调用方代码及手机 payload 的复核，没有另跑一次录音，也不声称完成了手动屏幕操作验收。

证据：`device-original/20260927-130341-customer-meeting-minutes-f0256832/` 保留 report.json、逐轮结果、memory.csv、hilog 和输入映射；`events-original.ndjson`、`window-queue-original.json`、`device-original-metrics.json`、`original-symptom-comparison.json`、`caller-phone-output.json` 保留逐窗、SDK 原句、声学区间和展示结果。

## PR SDK 门禁与证据绑定

同一 HAP 的 24 种模式、143 轮测试全部通过。22 种常规模式启用角色分离，与已有 ASR 调用序列组合；独立 finish 兼容性脚本按其规定运行两个模式。

- burst、paced（20 轮）、vad-begin、vad-begin-silence、voiceprint、voiceprint-fallback（4 轮 cold/warm）、voiceprint-vad-begin（6 轮）、voiceprint-vad-begin-idle。
- cancel、cancel-full、recreate、reconfigure、speaker-vad-onstart、endpoint-reentrant、max-duration、edge、reentrant、start-cancel、start-write（6 轮）、start-write-reload、user-sequence（50 轮）、numeric-edge。
- `run_finish_compat_release_gate.py`：callback-api-reentrant、finish-shutdown 各 3 轮，根 report.json 与两个子模式 artifact 完整保留。

除注明外各模式 3 轮。paced 实际工作 105.559 秒；user-sequence 223.049 秒。每 session 的正常结束、取消快照、迟到调用、重入及恢复按 runner 原断言通过，没有放宽空结果、内存、timeout 或生命周期门禁。短模式内存 INCONCLUSIVE 如实保留；user-sequence RSS 增长 33.738 MiB，通过原阈值，但不等价于长会议内存稳定。未覆盖断电、进程被系统强杀、设备断连等外部故障。

HAP SHA-256：`f77108a04e6055a9bb7339fa62cbfc41575467fd2b9396359541d4382d739e26`；鼎桥 HAR：`d2253ca19f9ab6b0c2c0b1157fa01128ca4db7c325a3a126e0b2dd95de91df31`；完整构建身份绑定四个 HAR、授权、签名及源码 fingerprint，见 `build-identity-185414b5.json`。

`archive_release_gate_evidence.py` 生成不可覆盖的 `pr-gate-evidence-185414b5-v2/`，已有 release tracker 文件校验器验证所有引用文件、大小、哈希及归档结构。根 report.json SHA-256：`3992755856c6da048d5828de7a4978552f53df07fa48cdc138a9a6ee457423a0`。首个归档把 PR 标记写入 SemVer 字段，保留为 non-canonical；v2 只改为实际未变的 SDK 版本 0.3.17，不重跑测试、不覆盖旧证据。

本轮是 PR 门禁，无新版本、正式交付 ZIP 或客户发布；因此不伪造发布账本条目。正式发布时仍须将对应交付包绑定并执行 attach-evidence/verify-evidence。原始录音和模型输出未提交 Git。

运行提交的当前 CI（含 Android AAR、Harmony 生命周期）、本地 Harmony 构建和全部约定 SDK 真机门禁通过。全部 review threads/reviews 已拉取，无评论且无下一页；最终报告提交后再次核对当前 HEAD CI 与 review threads。仅报告变化不使运行产物失效，保留真实 `185414b5` 构建身份。

## 结论边界

原始 u6 对齐体验用例、相邻保守映射规则及生命周期通过。直接声学关联、规则推断与映射不明分别保留，没有将推断作为声学身份修复。

600 秒既有 native 误认与 overlap 漏检继续由 [#222](https://github.com/amphionspace/AmphionRuntime/issues/222) 跟踪；本轮相同 speakerTurns 证明此处声学结果未因 SDK 对齐变化。长会议积压及 RSS 问题 [#224](https://github.com/amphionspace/AmphionRuntime/issues/224) 保持开放。角色分离整体能力仍未通过这些困难场景，不能以本次 SDK 门禁宣布整体交付可用。

要进一步减少无映射 ITN 的 UNKNOWN，需要文字后处理保留精确转换来源。本轮不猜测来源，不修改模型、默认 120 秒定稿或其它参数。

修改文件：Harmony `SpeakerDiarizationTranscriptState.ts`、Android `DiarizationTranscriptState.kt`，两端相邻/原症状测试、定稿测试原生输入夹具，以及本报告和 UNKNOWN 规则说明。此前时间轴与 session 证据修复继续保留。
