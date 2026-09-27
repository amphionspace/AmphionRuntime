# 四人录音：ITN 来源、编号与句内换人

## 范围和结论

输入是 Mate80 鼎桥 Demo 最新会话 `run-1790488085002/session-3`，完整 SDK PCM
102.38 秒。55 秒的 `last_sdk_input.wav` 是截断副本，未作为完整验收输入。
用户确认四人；MOSS 仅接收原音，独立输出四个角色，属于辅助标注，不能当作人工真值。

本次改变：新身份按首次可发布的声学出场顺序编号；ITN 通过实际选中路径提供来源关系；
SDK 新增原文到展示文字的角色范围 `speakerTextSpans`，调用方在明确换人处直接显示“说话人 N：对应文字”。
句级汇总仍表达整句参与者，不再被调用方当作每个字的归属。已发布身份、原始声学区间、文字、推断标记、
回调及生命周期语义保持不变。不改模型、FST、阈值、窗口、hop、timeout 或默认定稿周期。
用户听审确认轻声插话只有不完整单字，并明确要求不要围绕该 hard case 继续投入。
本轮优先修复正常音量主讲人的文字归属传递；不补写漏词，不修改轻声声学边界，
不把 SDK 对齐修复称为声学身份精度提升。原生 ASR 错词单独记录。

## 第一个错误状态与修复

1. ID：`CommunitySpeakerIdentity.assign` 原按 native cluster 数字分配新 ID，
   导致实际出场顺序为 2、4、1、3。新身份按可发布声学 turn 的首次出现时间分配，
   已定稿身份的历史投票和 ID 不变；预览 fork 不占用正式编号。
2. ITN：原始 token 和角色证据明确，但 `WetextItn.normalize` 只返回文字，丢失转换来源。
   两条原句含“一百二十秒→120s”“九十→90”，`TranscriptState` 因无法精确对齐而整句 UNKNOWN。
   新接口沿实际选中的 tagger 路径记录输入消费位置，以语法 record 为不可拆分转换单元，
   保留重排、合并和展开的来源；验证 record 输出拼接与既有完整 Normalize 输出相同。
   无法对应时保留空映射，文字不变。没有 edit distance、字符串去重或均匀时间分配。
3. SDK 文字归属：原句 u11 在 94.840 秒（原文 UTF-16 offset 5）已有女声 token
   对应的已知角色，但 `sentenceUtterances` 将整个混合句汇总为 UNKNOWN，公共结果没有
   保留已知文字范围。固定 token、时间戳及声学 turns，仅插入标点，后半句就变为已知。
   第一个归属信息损失在 SDK 句级聚合；调用方随后忠实显示该汇总，并非 UI 自行误认。
   新增 `speakerTextSpans`，在原始 utterance 上先计算文字角色及推断，再按精确 ITN 来源
   投影到展示文字；标点分句仅选择已有范围。每段保留主/副角色、UNKNOWN、overlap、
   `speakerInferred` 和 confidence。跨角色的不可拆分 ITN record 保持 UNKNOWN，
   包括未落到 token 起点的短暂相反声学证据；映射不明时返回空范围。
4. 调用方根据 SDK 文字范围在明确的主角色变化处分行，直接显示“说话人 N：对应文字”，
   编号不重排。同人连续范围合并；UNKNOWN、overlap 或推断状态变化本身不触发拆段。
   含 UNKNOWN 的可读组明确标“部分文字归属不确定”，并保留 SDK 原始范围；不会把这些
   文字的 SDK 身份改成相邻角色。重叠及推断分别显示提示，confidence=0 继续保留。
   真实单字回答仍可形成不同角色的可读组，不设置字数或时长阈值。
   只改“句内换人”提示文案的旧候选不算此缺陷修复。旧调用方需要读取新字段才能显示
   句内每段的归属；原句汇总、回调和 final/last/complete 语义均未修改。

角色先在原始 utterance/token 时间轴上计算；ITN 来源及标点只选择原有证据，
不重算邻接补全。跨人物的转换单元保持 UNKNOWN，来源不完整亦保持 UNKNOWN。
有限 UNKNOWN 补全仍标 `speakerInferred=true`、confidence 0，原始 speakerTurns 不变。
Speaker VAD 拒绝结果同时清除新增的来源文字，保持原有拒绝语义。

## 同输入状态回放

复用原始窗口 segmentation/embedding、原生 ASR、输入到达顺序和异步完成时刻，
执行生产 Session / Identity / Transcript；不把独立离线聚类当作在线行为。

| 项目 | 原结果 | 修复候选 |
|---|---:|---:|
| 首次出场编号 | 2、4、1、3 | 1、2、3、4 |
| UNKNOWN 文字字符数（含标点） | 95 | 10 |
| 原始声学区间变化 | — | 0（仅 ID 置换） |
| 文字变化 | — | 0 |
| 新增强制身份合并 | — | 0 |

上表 95→10 是 ITN 来源修复后的**句级 UNKNOWN 字符数**，不能当作身份准确率。
新增文字范围后句级指标仍为 10，但这些文字不再全部显示为未知：前 5 个原文字符
属于说话人 1，后 4 个属于说话人 2，其中末尾 2 字为有限邻接推断，confidence=0。
文字仍是原生 ASR 输出；未用听审答案替换错词或补上轻声插话。

用户听审确认 90–97 秒有不完整的轻声插话，来自先前发言的男声（按出场为说话人 4），
并非 MOSS 给出的完整词语。以下证据区分了各层，未据此宣称模型能力已经到顶：

- 原生 ASR final 在 92.760–94.840 秒之间没有对应插话 token；女声原文也存在错词。
  错误在 ITN 前已出现，但尚未用解码状态分叉确定其最内层原因。本补丁不修 ASR 漏词/错词。
- 固定 PCM 的 5 个 10 秒窗口：主机同一 ONNX 的 589 帧输出与手机 segmentation mask
  逐帧一致（0 差异），排除所查窗口输入和 native powerset 解码差异。
- 重叠窗口对轻声插话有冲突：93.30 秒两窗投给说话人 4，三窗投给说话人 1。
  2:2 平票区间仅置换 cluster 标签再还原，边界变化 135 ms，证明重建存在编号相关的
  平票行为；不是“native 异常因此模型无能”的证据。此轻声范围未修，不继续叠加阈值。
- 完整在线状态回放保留 48 窗、10 次预览、真实完成顺序；仅 finish 提交一次，之前无
  已定稿身份、无跨提交历史裁剪。回放公共 turns/文字与手机一致，排除本样本的冻结、
  历史身份分配及裁剪导致差异。
- 新增字段后原始完整在线回放的旧公共字段、文字和 raw turns 均不变；同 token 的公共
  文字归属、UNKNOWN、overlap 和推断标记在只改标点的对照中一致。

0e057a55 真机对照：48 窗，推理平均 551.875 ms / 最大 684.632 ms；
pending 最大 0、in-flight 最大 1、完成时音频延迟最大 580 ms；ASR 队列最大 780 ms，
结束归零。finish 932 ms，finish 前 last=0，之后 last/complete 各 1，无 error/timeout。
10 次预览聚类合计 123 ms，finish 聚类 232 ms。RSS 峰值 671.49 MiB，活跃尾部
450.55 MiB，卸载后 308.01 MiB。该 UI 播放 102.38 秒音频耗时 123.142 秒，
因此不以 inference/hop 或本次录音单独宣称长期实时无积压。新字段提交 bc78b58d 的同条件真机已通过：48 窗均值 560.662 ms / 最大 673.506 ms，
pending=0、in-flight≤1、音频延迟最大 560 ms；ASR 未处理音频最大 680 ms，结束归零。
finish 989 ms，last/complete 各 1，finish 前 last=0，无 error/timeout、无空 endpoint final。
预览聚类合计 138 ms（10 次），finish 聚类 244 ms；RSS 峰值 671.24 MiB，卸载后 307.84 MiB。
102.38 秒 PCM 喂入耗时 124.861 秒，不能据此宣称最大实时吞吐或长时 RSS 稳定。

真机 SDK 新字段与在线回放一致，旧公共字段逐项完全不变；实际页面保留完整句子，
但只用颜色及图例，用户仍无法直接看到每段的 ID，因此该版本的最终可读归属验收为 FAIL，
阻断合入。新增直接标签版本 115e42d5 已在同一 Mate80 通过原录音复验：混合句在文字前直接标出
说话人 1/2，按明确主角色变化分行；同人直接与推断范围合并为可读文字，同时保留推断提示。
无需颜色或图例即可读出各段角色，原生文字、声学 turns 和所有公共范围逐项与上一版一致。
完整词语不拆段，短暂的说话人 4 声学区间仍在原始 turns，不补造缺失 token。

## 定稿周期

当前默认 120 秒是工程冻结周期，现有证据不证明它是身份准确性的最优值。
10 秒预览在可用推理窗口和 ASR 进度达到预览边界时触发；正式提交还需相应 ASR endpoint
和声学窗口完成。finish 处理剩余尾段，不等待周期凑满。缩短周期改变不可回滚身份及文本
提交边界、聚类调用次数和参与窗口组合；完整历史证据仍保留，不据此假定更快或更省内存。

复用 600 秒 AMI TS3003c 四人标注片段（原会议 330–930 秒）及设备采样顺序。
唯一候选变量为 30/60/120 秒定稿：模型 10 秒、native 160000 samples、hop 2 秒、
预览 10 秒、窗口 timeout 10 秒、finish barrier 15 秒均不变。

| 周期 | 首次预览 | 首次定稿 | ASR final 后平均/P95 等待 | 身份误认 | 同人 ID 切换 | 预览/定稿聚类次数 |
|---|---:|---:|---:|---:|---:|---:|
| 30 秒 | 13.163 秒 | 34.725 秒 | 14.675 / 30.494 秒 | 1.70 秒 | 2 | 46 / 24 |
| 60 秒 | 13.163 秒 | 64.638 秒 | 27.675 / 54.588 秒 | 1.06 秒 | 1 | 54 / 13 |
| 120 秒 | 13.163 秒 | 124.548 秒 | 45.880 / 103.338 秒 | 1.70 秒 | 2 | 56 / 6 |

三者 overlap 召回均为 0（参考 overlap 0.76 秒），均仍存在身份错误。
短插话的首个错误已在 native 聚类结果中出现；其已选定区间不能通过调定稿周期变成
可靠身份。因所有候选均未通过身份门禁，停止参数路线，默认保持 120 秒；这不表示推荐
120 秒为最优，也不表示 60 秒必然更慢。未启动缺乏决策价值的 60 秒真机长跑。

逐句等待、参与窗口量、聚类耗时及评分细节保留在 `replay/comparison.json`。
桌面聚类时间含进程启动且复用缓存，只用于诊断，不作为手机性能结论。
文字 UNKNOWN 在三种周期均为 426 字：历史捕获没有 ITN 来源字段，本表仅比较周期，
不能将该文字指标混入本次 ITN 修复前后的对照。

## 验证与证据

- ID 顺序、ITN 来源和句内展示均保留最小红灯；100 项相关 SDK 状态测试通过。
- 原生 ITN 测试覆盖数值、百分比、日期、Unicode、重复字、规范化以及无法回溯来源的
  人工延迟输出 FST，普通 Normalize 输出逐项不变。
- 已覆盖已定稿冻结、预览不建档、短插话、UNKNOWN、overlap、推断标记及拒绝结果清除来源。
- 0e057a55：Harmony ZH_EN 构建/签名/安装、原录音 UI、18 模式 61 轮真机矩阵、
  Android 381 项单测及 CI 通过，全部 review threads 已拉取（0 条）。这是新增字段之前的证据。
- 新文字范围：37 项相关回归通过，原始在线回放通过。覆盖只改标点、ITN 跨角色、
  映射不明、短插话、UNKNOWN、overlap、提交冻结及真实公共结果到页面的推断标记传递。
- bc78b58d：新 HAP 构建/签名/安装、原录音 UI、当前 HEAD CI 均通过。
  同步最新主线后 Android Debug/Release 379 项测试通过；无错误、失败或跳过。
  最终真机生命周期矩阵、finish 兼容门禁和最后一次 review 检查在汇总中记录。

私有证据根：`~/.cache/amphion-runtime/diagnostics/four-speaker-tail-20260927-135910/`。
原音及完整转写不入库。`input-map.json` 绑定完整 WAV/PCM；`session-3-events.ndjson` 是原始
事件顺序；`session-3-itn-mapped.ndjson` 仅补原生来源映射用于回放，不能当作手机采集日志。
完整 WAV SHA-256：`0b31db1204abd6687c66dfea5e86ed2f2848e54bb67993f8930f81ec0957dc2b`。
`original-device-metrics.json` 保留逐窗口与队列数据；`moss-run.json`、`moss-annotation/`
保留辅助标注及绑定。模型/短插话精度问题继续由 #222 跟踪，长时稳定性由 #224 跟踪。

白盒证据位于私有根 `tail-whitebox/`：`public-attribution-red.json`、
`text-spans-red.log`、`online-tail-spans-replay.json`、`text-spans-regression.log`、
`window-channels.json`、`segmentation-parity.json`、`reconstruction-frames.csv`、
`reconstruct-label-permutation.json`、`asr-tail-events.json` 以及 `human-review-*.json`。
轻声短插话/overlap 的未解决范围由 #222 单独跟踪，不能写成本补丁已修复。

SDK 新字段阶段的基线产物绑定 `bc78b58d545924e3ff40ed6de4f238a617e6d8b5`；
`device-ui-text-spans/` 保存相同 PCM 校验、窗口/队列/内存/回调数据、公共范围及真实页面截图。
这次只修 Harmony 文字归属及调用方；Android 生命周期没有另外修改，新增公共文字字段
尚未迁移 Android。这里的 PASS 分别限于 SDK 对齐、编号顺序和对应生命周期，
不宣称 ASR 错词、轻声召回或角色分离整体精度问题已解决。

新增调用方红灯：`tail-whitebox/explicit-label-red.log`；修复后 16 项句级/调用方回归
`explicit-label-green-v1.log` 通过，覆盖原始混合句拓扑、同人连续 span、词中 UNKNOWN、
真实单字换人、overlap、推断/零置信度及 SDK 公共结果不被展示代码修改。
旧颜色页面截图保留为 non-canonical 体验失败证据，不当作直接标签版本的验收通过。

bc78b58d 的 24 模式 SDK 生命周期门禁及 finish 兼容门禁已全部通过，已归档至
`delivery/harmony-dingqiao/build/pr230-bc78-evidence/report.json`（私有构建目录），
私有证据根同时保留 `pr-gate-evidence-bc78/`。首轮调用方检查未达到 60 秒，保留其有效
结果并补充 14 轮 paced（超过 60 秒），没有放宽资源门禁。颜色版 UI 的体验失败不影响
这批 SDK 生命周期数据；直接标签版本须另外比较四个 HAR 内容并完成原录音 UI 验收。
此为 PR 验证 HAP，不是客户交付 ZIP；未更新正式交付发布账本或宣称已交付。

直接标签版本真机数据：48 窗推理均值 576.066 ms / 最大 714.358 ms，
pending 最大 0、in-flight 最大 1，音频延迟最大 580 ms，
ASR 未处理音频最大 680 ms、结束为 0；finish 936 ms，
finish 前 last=0，结束后唯一 last 再唯一 complete。RSS 峰值 675.80 MiB，
卸载后 303.18 MiB。本次不是长期内存平台期证明。
`device-ui-explicit-labels/` 保留 UI 截图/布局、公共结果、完整同输入校验和队列/回调/RSS 数据。

展示测试另保护“同样文字在定稿后必须刷新角色、迟到临时结果不得覆盖定稿”。旧测试只
读取段落标题，未读取新增文字前的标签；已改为从实际页面表达式读取完整可见内容，
保留原有身份及冻结断言。运行代码没有因该测试适配再次变化。

最终 HAP 的两份 native 封装库由构建重新生成，虽然 SDK 源码不变，不能宣称与旧 HAR
逐字节一致；因此最终生命周期门禁另绑定 115e42d5 产物。原有白盒、身份及单测结论仍保留，
不重复精度实验或轻声插话分析。没有模型、阈值、窗口、hop、timeout 或周期调整。

主要修改文件与行为：

- `CommunitySpeakerIdentity.ts`：新身份按首次可发布的声学出场顺序编号。
- `SpeakerDiarizationTranscriptState.ts`：原始 utterance 证据上的角色归属及精确 ITN 投影，
  新增句内文字范围，保留 UNKNOWN、overlap、推断和冻结。
- `DingqiaoModels.ets`、`SpeakerDiarizationSession.ets`：发布 `SpeakerTextSpan`，沿用公共编号。
- `Runtime.ets`、`Types.ets`、sherpa patch `0030`：保留实际 ITN 路径来源；
  原有 Normalize 文字不变，VAD 拒绝时清除相应来源字段。
- 鼎桥 Demo `Index.ets`：明确换人时直接标 ID；同人合并，未知不放大为词语碎片。
- 句级/调用方/身份/拒绝生命周期测试、原生 ITN 测试、符号检查及接口文档同步更新。

最终门禁：115e42d5 的 24 模式、90 轮真机 SDK 检查全部 PASS，含唯一 last→complete、
finish 前 last=0、cancel/重入/冷加载同步写入/卸载重载/恢复和 numeric-edge。
`run_finish_compat_release_gate.py` 的两个模式均 PASS。最长 paced 观测超过 60 秒；
这不代表长期 RSS 平台期或所有外部故障均已覆盖。Android Debug/Release 379 项通过。
最终规范证据：`delivery/harmony-dingqiao/build/pr230-115-evidence/report.json`，
私有根另保留 `pr-gate-evidence-115/`，逐轮结果、内存、hilog、输入映射和失败现场均保留。
报告 SHA-256：`c886f3dcd571cff10cf9a8ad969d8ffc837d32df01be39459118484e345da73c`。

后续提交只更新展示测试适配和本报告，不改变 HAP/HAR 输入；复用 115e42d5 的最终真机
证据。当前 PR HEAD 的 CI 和全部 review threads 以 PR 合入记录为准，未完成不得合入。
