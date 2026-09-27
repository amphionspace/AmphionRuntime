# 短段 embedding 的 mask 归属修复（2026-09-28）

**已修复混合 overlap 声纹被短 clean run 借用建档的缺陷；不宣称身份精度提升或整体交付完成。** 修复提交 `25391d12`，真机运行提交 `196caeec`。55项相关测试通过，包含能使旧版本稳定失败的最小用例。相同新真机张量在修复前后生产聚类中得到完全相同的公开结果、临时更新与身份状态；原有客户短段 UNKNOWN 和公开集误认仍保留为阻断项。

## 最早错误状态与局部修复

native `Process` 只有在 clean 超过2帧时才使用 clean mask；否则整窗 embedding 的池化范围是原始通道，可能包含 overlap。旧短段建档只检查“本通道恰好一个 clean run”，不能证明这个 run 拥有整窗向量。最小用例有一个已知长段，后接1或2帧 clean 与22帧 overlap；旧代码借用混合向量建立第二个确定身份，断言稳定失败。

修复在 `community_cluster.h` 增加实际 mask 归属条件：超过2帧时沿用 clean mask；不超过2帧时，要求本通道全部活动都属于该 run。没有调整人数上限、时长准入、窗口、模型、分数或 UNKNOWN 规则。纯净1帧/2帧证据、3帧及80帧 clean，以及使用独立 clean mask 的 overlap 场景均保留原行为；这不是统一删除短段。

已有四个实录锚点未出现该混合 mask 形态。AISHELL-4固定切片的第36、127个窗口出现该形态，但原生产快照中均未实际获准短段建档。因此，它是已证明的准入所有权缺陷，不是当前公开集误认的已证根因，也不能用本次修复解释 DER 改善。

## 验证与数据来源

五段已存张量（四实录锚点及 AISHELL-4）上，候选公开结果与临时更新均不变。复用前核实了候选 C++ 头文件逐字节相同，避免重复编码和无新增信息的回放。55项 Harmony/native/session/public/spool 测试实际执行通过。Android 共用 C++ 重新编译通过；48项未改动的 JVM 角色状态机测试由 Gradle 复用有效缓存，未冒充新执行或 Android 真机结果。

新增真机验收只使用固定 AISHELL-4 四人180秒切片。Mate80 `7GK0226326015655`，系统 `OpenHarmony-6.1.1.120`；HAP SHA-256 为 `348a61568450e0a833f5e8f31ac7260f9fcead771d8bf470213b94f382a6ecc0`。HAP/HAR、构建身份、输入与 RTTM、原红灯、测试日志、完整事件、callback、RSS、hilog、评分器和不可变源码快照见[证据索引](evidence/DIARIZATION_SHORT_MASK_OWNERSHIP_20260928.json)。原始 PCM 和含文本结果未提交 Git。

| 检查 | 结果 |
| --- | --- |
| 声学归属 | 171窗的分割、范围与PCM-derived RMS与既有主机张量一致；历史真机共有的86个绝对PCM窗口，分割、整窗/run embedding及范围逐位一致 |
| 同输入代码分叉 | 新真机171窗分别经过修复前后生产C++；2个公开窗口、24次临时更新、全部身份记录（除耗时）一致；新真机公开结果与修复前分叉一致 |
| SDK及最终展示 | ASR对齐一致；真实调用方函数产生的41个段落、角色文字段与修复前分叉一致，文字守恒且已提交段冻结；不是截图或完整人工可读性验收 |
| 生命周期 | 唯一last后角色最终结果，再complete；无error，native stream=0 |
| 实时 | RTF=0.5916，pending最大0，in-flight最大1，最大音频延迟1120 ms，finish到complete=2045 ms；严格趋势规则为INCONCLUSIVE |
| 内存 | runner门禁PASS，RSS增长28.807 MiB、峰值654.809 MiB；三段中位数614.979 / 638.637 / 644.033 MiB，严格长期内存INCONCLUSIVE |

首次逐位比较保留了一个分析红灯：把主机的171窗张量作为旧真机向量，会得到整窗/run embedding最大差约`2.56e-6 / 3.10e-6`。回溯 `prepare_replay.py` 与 density分叉provenance后，确认对照来源不同；旧真机是2秒hop、86窗，主机分叉为1秒hop、171窗。按绝对PCM位置对齐后，86个共有真机窗口全部逐位相同。随后再对新真机全部171窗做修复前后状态分叉，排除本次准入改动带来的输出变化。没有修改精度阈值、覆盖原失败文件，或把跨来源小数值差异直接忽略。当前1秒hop来自更早的协议密度修复，本提交未改动它。

## 公开集结论与未决项

评分沿用冻结manifest：16 kHz mono PCM16、AISHELL-4 channel 0、原会议690–870秒、官方RTTM offset=690秒；10 ms评分帧，strict零collar且计入overlap。一一映射只在评分器中使用；SDK没有oracle人数输入。

| 指标 | 当前真机 | 修复前同张量分叉 |
| --- | ---: | ---: |
| strict DER | 33.6679% | 33.6679% |
| speaker-count error | 0 | 0 |
| minority recall | 22.2909% | 22.2909% |
| speaker confusion | 2.07 s | 2.07 s |
| UNKNOWN turn time | 27.20 s | 27.20 s |
| overlap detection recall | 65.2022% | 65.2022% |
| 同一reference的ID switch（原评分定义） | 2 | 2 |

这是固定诊断切片，不是官方完整Test集。不能与官方AISHELL-4总体数字直接相减，也不能把较早版本到当前版本的变化归因于本补丁。004-M仍有已知误认，少数说话人召回仍低；最终展示一致不等于已有错误可接受。

最新候选包含先前的[arena回收修复](DIARIZATION_ARENA_RELEASE_20260928.md)，但没有把该修复旧提交的四项设备结果挪作本提交的完整发布矩阵。当前提交仅新增上述公开切片真机证据及对应主机回归；四实录同张量不变证据明确标记为host。客户开场短段UNKNOWN、长时内存/实时趋势、完整实录与最终离线发布矩阵仍阻断交付，未合入最终PR或生成正式发布ZIP。
