# 2026-09-23 离线会议与结束超时反馈

状态：**问题 59 的 215.42 秒客户原音已通过本机候选修复验证：收尾 17.06 秒 → 12.56 秒，无降级、尾文完整、资源归零。会议身份仍有阻断项，候选未合入或发布，不能据此宣称离线会议能力整体通过。**

来源：[客户反馈页面](https://ccnuebbmik1f.feishu.cn/wiki/JaccwHakcit4Fnkk4IycN8UgnOE)，读取版本 235。
只读取得问题报告、两份完整日志、215.42 秒原音及四个 RAR 分卷；原音、转写和原始日志保留在私有目录，不提交仓库。

## 范围与验收断言

- 问题 59：相同 16 kHz、单声道、16-bit PCM、20 ms 实时写入、`vadEnd=800`，停止后应完成已接收音频，角色尾批不因队列积压触发 `FINISH_TIMEOUT`；记录 finish 到 last、尾批和 complete 的各自耗时，单独检查客户 15 秒等待窗口。
- 保持：finish 前 last=0；结束后唯一 last、唯一尾批和唯一 complete，顺序不变；真实取样、模型资产、身份阈值、UNKNOWN/重叠和已提交窗口冻结不变；出错仍等待在途 native 工作释放，不用延时、跳窗、空结果或身份覆盖掩盖问题。
- 会议：定向检查 9 月 23 日 128.56 秒与 9 月 18 日 168.2 秒两段会议，分别核对 SDK 原句、声学角色区间和最终文字段。真实换人、短插话、重叠和不确定性必须保留。8 段会议不因超时单项通过就整体判通过。
- 不处理：本页在线引擎问题 58、重新设定人数、通用轻声识别及本轮正式发布回归。主讲人的已确认人数及客户指定异常时间点尚待补充；不把 MOSS 标签数量当真实人数。

## 已证实的时间线与根因

客户复测停止于 19:10:43.179，公开 last 为 19:10:59.710，角色尾批及 complete 为 19:10:59.747：分别耗时 16,531 和 16,568 ms，尾批 reason=4、speakerCount=0。

同一日志中，内部 `FINAL_TAIL` 解码仅 151 ms；19:10:44.683 已产生内部 utterance final 和 soft reset。因此“718 字长句的尾解码本身耗时 16 秒”不成立。

Harmony 的 15,000 ms 从**内部** ASR 尾结果就绪后起算；公开 last 被收尾协调器保留，等待角色结果后与尾批、complete 顺序发出。Android 同名路径为 10,000 ms。公开 last 与尾批只相隔 37 ms 不能用来推断计时起点；两端源码已核对，计时语义不在本轮修改范围。

USB 原音基线重现 finish-to-complete=17,058 ms、reason=4，角色处理仅覆盖到约 151 秒。随后 main `26f85ca7b91688961633557f138105e323639a76` 的诊断构建确认：

- 停止时正在处理第 53 窗，另有 33 窗排队；内部 ASR 尾已到达，`asrTailObserved=true`，`processDrained=false`。
- 从音频约 32.5 秒起，多数窗口需要 4–5 秒，窗口步长却只有 2.5 秒，积压在录音期间已形成。
- 等待期间仍持续完成窗口，排除该现场“等不到下一个 ASR endpoint”或整个推理线程死锁的假设。
- 超时快照 native stream=1 表示还有在途作业；这是收尾/资源门禁失败证据，尚不能据此认定持续内存泄漏。
- 长句未定稿前全局身份窗口未提交，临时角色存在但最终 speakerCount=0；这既不能解释为没有检测到声音，也不能作为身份识别正确的证据。

## 修复与验证

Harmony 在同一窗口内并行主/辅助声纹计算，对逐样本完全相同的 channel/run PCM 复用本窗结果；局部身份查询由两份主模型、两份辅助模型分别处理原网格的偶/奇位置，按原位置收集。主模型各 2 线程、辅助模型各 1 线程。每个模型仍至多一个在途调用，不跳过、不重排窗口，不减少查询，不调整音量/身份阈值或 15 秒时限。模型权重和取样不变，新增两份模型驻留是明确代价。

所有计算完成后才发布结果；一侧失败也等待其他 native 工作归还，并按原 cell/主辅顺序选择错误，不能由异步完成顺序改变错误分类。副本加载失败会释放已创建模型。临时队列/耗时插桩已撤除。

| 对照 | 音频 | finish → complete | 结论 |
|---|---:|---:|---|
| 原安装包基线 | 完整 215.42 秒 | 17,058 ms | `FINISH_TIMEOUT`，stream=1 |
| main 诊断基线 | 完整 215.42 秒 | 16,959 ms | 同症状，停止时排队 33 窗 |
| 双模型并行 | 前 60 秒 | 15,553 ms | 仍积压，不足 |
| 加主模型双线程 | 前 60 秒 | 12,766 ms | 忙段仍平均 3,180 ms/窗，不足 |
| 加相同 PCM 复用 | 前 60 秒 | 9,626 ms | 长会话尚不能通过 |
| 加第二份主模型 | 前 60 秒 | 5,621 ms | 忙段约 2,529 ms/窗，进入完整复验 |
| 三队列完整复验 | 完整 215.42 秒 | 16,039 ms | SDK 脚本 PASS，但客户 15 秒断言 FAIL，不能当修复完成 |
| 四队列最终候选 | 完整 215.42 秒 | **12,555 ms** | SDK、尾文、客户 15 秒及资源单项 PASS |

最终原音运行：`four-queues-issue59/20260923-212104-customer-meeting-minutes-420a8abe/report.json`。设备为 HUAWEI Mate 80，20 ms 实时输入、`vadEnd=800`，同一个 ZH_EN diagnostics HAP；授权、签名和组包规则未变。源码基于 main `26f85ca7` 的未提交候选，构建 fingerprint `2e2f17ee7516d3574cd09572ec6562e626eb9e39f3f2e159ed427c20bff3bb6c`，HAP SHA-256 `9e8a1deaae2c6e60f8887003827946dc599cba9c67685be826f7ca2d3af03700`。四个 HAR 及模型哈希见 `four-queues-build-identity.json`。

finish 前 last=0；之后唯一 last、唯一角色尾批、唯一 complete，无 error，native stream=0；last/尾批分别在 12,480/12,481 ms 返回。峰值 RSS 826.969 MiB，报告增长 26.957 MiB、线程增长 1，约四分钟范围内资源门禁 PASS；平均设备 CPU 占用约 39.24%，不作为长稳或其他设备的结论。

SDK 完整识别文字 709 字符与 main 基线逐字符一致；四队列与三队列的最终角色窗口除耗时字段外逐字段一致，不能把并发提速描述为身份精度提升。尾文断言“考试答题版简短”同时来自独立 MOSS 与原 SDK 基线，只检查末尾保留，不代替全文准确率。

主机检查：先通过 52 项相关检查；四队列变化后重跑受影响的 10 项，另补 1 项模型副本加载失败/关闭检查，均通过。覆盖真实生产方法的反向完成顺序、原 PCM 与网格、窗口隔离、同长度不同 PCM 不复用、失败等待全部工作、错误选择顺序与回收。未重复未受影响的长跑。Android 同名收尾逻辑已检查，本轮未改 Android 推理或声称其性能已修复。

短前缀使用的多窗口脚本整体 FAIL 包含“不足两个提交窗口”的前置条件，不放宽该门禁。完整原音因长句可能只有一个角色窗口，采用现有 `customer-meeting-minutes` 模式及哈希绑定尾文断言；另独立执行客户 15 秒断言，未以脚本 PASS 掩盖三队列的 16.04 秒失败。

## 同产物相邻会议验证

复用同一个 HAP，原始 PCM 20 ms 实时写入、`vadEnd=800`，同一进程连续两会话，未重新构建：

| 原音 | 时长 | 非空文字段 / 最终角色窗口 | finish → complete | 结果 |
|---|---:|---:|---:|---|
| `会议室-20260918-143215-130.wav` | 168.2 秒 | 23 / 2 | 3,246 ms | SDK / 资源 / 15 秒收尾 PASS |
| `会议室-20260923-181634-521.wav` | 128.56 秒 | 10 / 2 | 4,401 ms | SDK / 资源 / 15 秒收尾 PASS |

两会话各有唯一 last/complete，finish 前 last=0，无 error、无降级、无窗口冻结违规，native stream 各自归零。两段均返回 4 个 SDK 身份，但人数匹配不作为身份正确证据。最终文字段拼接与 SDK 全文逐字符一致，无单字文字碎片；推断段 confidence=0。`rawText` 是标点/ITN 前内容，不能直接拿它与带标点的最终 text 做相等断言。检查的是公共 SDK 结果及其最终文字段，未取得客户实际应用界面。

本轮峰值 RSS **886.688 MiB**，报告增长 43.215 MiB、线程增长 1；约五分钟范围内 PASS，不代表长稳无泄漏。完整结果：`meeting-controls-result/20260923-212625-diarization-windows-554c36be/report.json`，呈现对照为同目录 `presentation-assessment.json`。身份精度仍未经听审，不以接口 PASS 代替产品验收。

## 身份阻断项：长段正文仍 UNKNOWN

原音候选最终有 3 个文字段、1 个身份，其中 683 字正文仍 UNKNOWN。诊断中 132 个区间带 `RELATIVE_LEVEL_FILTERED`，累计约 196.1 秒；参考 RMS 为 0.11039，准入线约 0.05520，很多区间已有声纹/查询却因相对音量被过滤。此为规则执行证据，不是正式误认率，也不证明全部声源身份。

这与结束队列积压分别记录：本轮提速未修改准入规则，不把文字守恒、UNKNOWN 减少或回调恢复当身份修复。按现有“四位较响主讲人、轻声/背景允许 UNKNOWN”的范围继续复核，未获得客户指定时间点或已确认人数前，不强行归并或补假身份。会议身份和最终呈现不能判整体通过。

按[阿里云官方 API 文档](https://help.aliyun.com/zh/model-studio/fun-asr-flash-recorded-speech-recognition-http-api)，使用 `qwen-audio-3.1-asr-flash` 的说话人分离对问题 59 和两段定向会议独立辅助标注；只输入原始音频，未提供 SDK 标签或人数。问题 59 从约 26.72 秒到结尾均为 Qwen 的同一编号，MOSS 对应约 26.38 秒到结尾也为同一编号；原候选 SDK 在此区间几乎全部 UNKNOWN。Qwen 漏掉了前段短句，因此它与 MOSS 的总编号数分别为 2 和 3，不作为人工真值。

据此试验过“连续低音量主声源可越过全局峰值门槛”的局部候选。同一问题 59 原音真机运行：收尾 6.03 秒、无降级、资源归零，但最终 683 字正文仍为 UNKNOWN；输出身份从 1 个增至 4 个，Qwen 持续讲话区间被零散分配到多个身份。该候选没有修复用户体验且可能加剧重复建档，**已撤回，不属于当前源码或验收证据**。失败补丁及原始报告留在私有证据目录，标记 non-canonical；当前正式候选仍为上文的收尾提速。后续身份定位须检查被放行后的声纹一致性、聚类及建档决策，不能只放宽音量门槛或按 Qwen 编号直接覆盖 SDK 输出。

## 会议材料与辅助标注

RAR 已完整解出 8 段原始 WAV：66.8、168.2、81.12、870.96、128.56、109、164.14、2480.48 秒。格式均为 16 kHz、单声道、16-bit；清单保存文件 SHA-256 与原始 PCM SHA-256。

按 MOSS 工作流，在 `amphion-42` 只输入音频，对问题 59 和全部 8 段会议做了独立辅助转写。模型固定 revision `704aa4a9c304e8520be88901e0d1960158ef5b15`，贪心解码；保留原始输出、输入/模型校验、依赖与运行参数。SDK 标签、期望人数和预期答案均未作为输入。

问题 59 得到 22 段，最后时间 215.39 秒。8 段会议共 4069.26 秒：两段短录音整段生成，其余长录音固定按 180 秒切片，共 25 片；辅助语段分别为 15、33、20、335、77、49、21、651。未达到 token 上限，未发现超过 500 ms 的明显时间越界；尾部有无漏语音仍待听审，跨片身份未对齐。私有目录 `会议音频辅助标注索引.md` 链接原音、原始输出、原时间轴区间和运行参数。这些不是人工真值：交叠、角色数和身份分歧待复核，不能计算正式误认率或宣称主讲人身份已通过。

Qwen 对 9 月 18 日 168.2 秒会议标出 4 个编号，与 MOSS、SDK 的编号数量一致；逐句重叠对照仍有约 22 秒 SDK UNKNOWN。对 9 月 23 日 128.56 秒会议，Qwen/MOSS/SDK 分别给出 3/5/4 个编号，短插话及重叠区间分歧明显，须听审后才能判断谁漏人或重复建档。逐句时间、文本、音频 SHA-256、模型返回与用量均保留在私有目录 `Qwen31辅助标注索引.md`、`qwen31-speaker-labels.csv` 和原始 JSON，API key 未落盘；云端标注不进入正式离线 SDK 链路。

## 证据定位与结论边界

私有证据根目录：`~/.cache/amphion-runtime/diagnostics/sept23-feedback-84dnuai8/`。

| 内容 | 路径（相对证据根目录） |
|---|---|
| 来源与音频绑定 | `wiki.json`、`input-manifest.json`、`audio-manifest.json` |
| 客户日志时间线 | `issue59-original.log.timeline.json`、`issue59-retest.log.timeline.json` |
| 原安装包基线 | `baseline/20260923-202617-diarization-windows-bf32738b/report.json` |
| main 诊断红灯 | `diagnostic/20260923-203317-diarization-windows-75e60a9b/report.json`、`diagnostic-runtime/` |
| 诊断构建与状态 | `diagnostic-build-identity.json`、`diagnostic.patch`、`diagnostic-state-timeline.json` |
| 并行候选不足 | `pair-prefix60/20260923-204251-diarization-windows-36b1267b/report.json`、`pair-prefix60-events.ndjson` |
| 分阶段耗时 | `pair-profile.txt`、`profile-prefix40/` |
| MOSS 与输入来源 | `moss-source-provenance.json`、`moss-issue59/`、`moss-meeting-181634/`、`moss-meeting-181931/` |
| 每轮假设与停止条件 | `experiment-plan.md` |
| 最终候选原音验证 | `four-queues-issue59/20260923-212104-customer-meeting-minutes-420a8abe/report.json`、`four-queues-build-identity.json` |
| 最终相邻会议验证 | `meeting-controls-result/20260923-212625-diarization-windows-554c36be/report.json` |
| 身份阻断项 | `issue59-unknown-evidence.json`、`full-three-queue-runtime/` |
| 全部辅助标注与结论 | `会议音频辅助标注索引.md`、`moss-remaining/`、`assessment.json` |
| Qwen 3.1 辅助标注 | `Qwen31辅助标注索引.md`、`qwen31-speaker-labels.csv`、`qwen31-assessment.json`、`qwen31-*.json` |
| 撤回的身份原型 | `qwen31-identity-prototype-noncanonical.patch`、`qwen31-fix-issue59/20260923-232640-customer-meeting-minutes-1be8e012/report.json` |

接口收尾：问题 59 原音的候选修复通过本机定向验证。识别文字：与基线完全一致，不代表全文准确率。身份/用户体验：长段 UNKNOWN 仍阻断，8 段会议尚未完成听审和完整 SDK 精度验收。候选在隔离工作区，尚未回流 canonical main，不构成主线已修复或客户发布；正式发布矩阵及长会议/其他设备未覆盖。
