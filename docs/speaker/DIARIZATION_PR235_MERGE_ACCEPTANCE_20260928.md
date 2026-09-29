# PR #235 运行时合入验收（2026-09-28）

**合入评估：接受本 PR 的有限运行时改进。** 用户明确指示“内存增长是正常的，推进合入”。本轮接受已观察到的 RSS 增长，补齐剩余 SDK 生命周期验证；不修改内存阈值、原始 FAIL 报告或 timeout。最终合入仍须当前 PR HEAD 必需 CI 通过且全部 review threads 无未处理阻断。

**角色分离整体交付仍未完成。** 公开集少数说话人漏失、混合 run 边界和客户短段 UNKNOWN 仍需后续工作；完整四锚点、16 段实录、长会议及正式 Debug/Release 交付尚未全部验收。本次没有把已有身份错误标为修复，也没有生成正式交付 ZIP。

## 合入内容与回退保护

保留每窗共享 encoder 和精确 mask 复用、恢复模型校准的 1 秒证据密度、短段 fallback 保留 VBx 长段合并、前景证据容量选择、短 clean mask 独立归属、跳过必定失败的 AHC 重拟合，以及无 live allocation 时的 XNNPACK arena 销毁回收。SDK 继续离线运行；Qwen/MOSS 只用于研发辅助标注。

复用逐修复的同输入差分和四实录/公开片状态回放证据。AHC 成本修复在 171 窗的真机公开片保持 ASR、冻结身份和调用方 41 段结果相同，聚类耗时 8075→2600 ms，RTF 0.592→0.552，finish→complete 2045→1134 ms；这些是相应提交的性能与等价性证据，不是本轮新的身份精度成绩。边界切分和短段识别实验没有接入生产路径。详情沿用[成本修复](DIARIZATION_AHC_COST_20260928.md)、[短 mask 归属](DIARIZATION_SHORT_MASK_OWNERSHIP_20260928.md)、[容量修复](DIARIZATION_CAPACITY_FIX_20260928.md)及[arena 回收](DIARIZATION_ARENA_RELEASE_20260928.md)。

## 本轮验证

| 项目 | 结果与范围 |
| --- | --- |
| 针对性测试 | 127 项通过；ORT provider completion/teardown 所有权检查通过 |
| Android | Debug/Release 共 379 项测试实际重跑，通过；保留整窗 clustering 接口，不宣称与 Harmony run 路径精度等价 |
| Harmony | ZH_EN diagnostics HAP 构建、签名、源输入和五个 HAP/HAR 哈希校验通过 |
| Mate80 SDK | 25 个模式、70 轮的 SDK 契约通过；23 个模式原始总体 PASS，paced 与 voiceprint-fallback 仅 RSS 超线，由用户接受 |
| finish 兼容 | 官方脚本根报告 PASS；覆盖 3 种回调内 API 重入及 2 轮 finish-shutdown；另有 2 轮 finish-shutdown-relicense 通过 |
| 精度及体验 | 复用已有逐修复回归证据；没有新增完整集 PASS 声明 |

设备矩阵逐项包括 burst、超过 60 秒的 paced、vad-begin、vad-begin-silence、voiceprint、voiceprint-fallback、voiceprint-vad-begin、voiceprint-vad-begin-idle、cancel、cancel-full、recreate、reconfigure、max-duration、edge、reentrant、start-cancel、start-write、start-write-reload、speaker-vad-onstart、endpoint-reentrant、user-sequence、numeric-edge、finish-shutdown-relicense、callback-api-reentrant 和 finish-shutdown。每模式的实际轮数、分支、回调、native stream、内存采样、hilog 和输入映射均由[证据索引](evidence/DIARIZATION_PR235_MERGE_ACCEPTANCE_20260928.json)绑定。

`start-write` 与 `start-write-reload` 分别覆盖 32/88 帧缓存，在 `onStart` 调用栈内同步写入后继续识别/立即 finish。声纹覆盖短句、正数门槛、低音量、前置静音、多句、非注册源和 cold/warm fallback。最初起音预检缺少 Python ONNX 依赖，未开始设备运行；使用仓库已有固定环境后完成，未改用绕过预检的方式。

## RSS 决定与原始证据

| 模式 | 原始结果 | 观测 | 合入判断 |
| --- | --- | --- | --- |
| paced，4×19.58 s，默认结束观察 | FAIL，仅 RSS | 增长 85.650 MiB；阈值 64 MiB；87.733 s 观察；斜率 −17.813 MiB/min；thread growth −0.5；stream 全部归零 | 用户接受增长 |
| voiceprint-fallback，cold/warm | FAIL，仅 RSS | 增长 68.113 MiB；阈值 64 MiB；27.973 s 观察；thread growth −10；stream 全部归零 | 用户接受增长 |

原先零结束观察的 paced 失败仍作为 non-canonical 协议变体保留，不算额外通过轮次。短观察的内存 INCONCLUSIVE 保持不变。本次接受增长不等于已证明长会议无持续增长；没有新增线程泄漏、SDK 错误或 stream 残留的豁免。

## 同产物绑定及复用

测试运行提交为 `6578c787f26d181253861f8c5e203208ae8a65a0`，Mate80 `7GK0226326015655`，系统 `OpenHarmony-6.1.1.120`。HAP SHA-256 为 `c4583f3031dc39a743783770d2edcdae6d54a23263c27b309ea3c1e9a17e3317`，source fingerprint 为 `aa6808711b228d1258f32a6253d3c51bb20946798f0ff68e153b6ac8cc5d8c36`。

分支 `41b7fdbe` 与该运行提交仅有三份文档/证据索引差异；本次收敛也只增加或更新文档及证据。运行输入、模型/native 哈希和五个 HAP/HAR 完全相同。补测在原运行提交执行，严格 build identity 校验通过；没有把旧产物的构建提交改写为新提交，也没有为文档变化重复构建和重跑已通过模式。finish 根报告及两份子报告均来自相同运行提交、设备和产物。

此前[合入阻断索引](evidence/DIARIZATION_PR235_MERGE_BLOCK_20260928.json)保持不变，新索引单独记录用户决定和新增结果。原始 PCM、识别文本和 embedding 不进入 Git；完整私有 artifact 的路径、大小和 SHA-256 保留以便复核。
