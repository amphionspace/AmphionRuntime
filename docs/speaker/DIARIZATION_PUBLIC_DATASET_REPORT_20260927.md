# 角色分离公开集与公开方法对照报告（`711f5ae7`）

日期：2026-09-27

这份报告以已合入主线的 `711f5ae7b96d45dbe1590878b6d41532c43c135f` 为基线。结论分两层：

- 在已复测的 19.58 秒四人短会话和 123.8 秒长会话上，没有观察到本次短 run 建档修复引入的回退。123.8 秒样例与既有 canonical 结果的 40 个 `speakerTurns` 完全相同。
- 这不等于“公开集精度不会回退”或“角色分离已经达到公开方法水平”。当前固定公开集子集的精度仍是红灯：加权严格 DER 为 **29.41%**；AISHELL-4 四人片段只输出 2 个角色，多个参考说话人召回为 0。该结果阻断通用身份精度验收。

## 测试对象和条件

设备是 Mate80（设备号 `7GK0226326015655`），安装包为 `com.amphion.asr.harmony.demo` `0.3.17`（versionCode `317`），HAP fingerprint：
`D6CE6F943F7D8AF4C0121C1842BB46F9225F1AF6657D1B088734B0B10A97250D`。

公开集回放使用 6 个固定 180 秒片段：AISHELL-4 的 2/3/4 人片段各一个，AliMeeting 的 2/3/4 人片段各一个；输入为 16 kHz、mono、ch0、PCM16 WAV，20 ms paced feed，`maxSpeakers=4`，未向 SDK 提供真实人数。合计 1080 秒音频，RTTM 参考包含 18 个片段级说话人。

AISHELL-4 原始数据是 211 场、约 120 小时的会议语料；AliMeeting 是公开的中文多通道会议语料，官方说明包含 2–4 人、15–30 分钟会议。本轮只取固定诊断子集，不能写成两套语料的全量成绩。数据说明见 [AISHELL-4 论文](https://www.isca-archive.org/interspeech_2021/fu21b_interspeech.pdf) 和 [AliMeeting OpenSLR 页面](https://www.openslr.org/119/)。

评估脚本是 [`evaluate_speaker_diarization_report.py`](../../delivery/harmony-dingqiao/delivery/evaluate_speaker_diarization_report.py)。严格 DER 按 10 ms 帧、无 collar、计入重叠计算：

```text
DER = (miss + false alarm + speaker confusion) / reference speaker time
```

`classicDer250msNoOverlap` 是 250 ms collar 且排除参考重叠帧的辅助指标；说话人映射使用一一对应的最大帧重叠映射。指标定义与公开评估习惯可对照 [pyannote.metrics 的 DER 说明](https://pyannote.github.io/pyannote-metrics/reference.html)。

机器可读结果（不含原始 PCM）见 [`DIARIZATION_PUBLIC_METRICS_711F5AE7.json`](evidence/DIARIZATION_PUBLIC_METRICS_711F5AE7.json)。

## 测试音频与标注归档

原始录音、MOSS 辅助标注和 SDK 诊断日志不进入 Git，也不作为公开下载附件；本轮收集的数据已放入公司私有对象存储，并完成回下载哈希核对。使用 AmphionBucket 的 `ab pull` 和下面的精确对象地址即可取回。

| 内容 | AmphionBucket 对象地址 | 大小 | 回下载 SHA-256 |
|---|---|---:|---|
| 123.8 秒四人诊断包（MOSS、SDK 原始结果、聚类窗口） | `cos-amphion-audio-backup:customer-asr-sdk/2026-09-27-mate80-four-speaker-evidence/mate80-four-speaker-evidence-20260927.zip` | 3,391,470 B | `f2ad3ea18876e85aa65b70255fe616d25bde47971a081c38d670fbc247c6c590` |
| 当日录音与标注汇总（16 条音频、3 条标注音频，共 760.28 秒） | `cos-amphion-audio-backup:customer-asr-sdk/2026-09-27-recordings-annotations/mate80-recordings-annotations-20260927.zip` | 19,301,485 B | `2976fe59ddd49e32d0d98e1df83a7e295584531570b8b225446041537fd11b07` |

归档内的 manifest 还保存每条 WAV 的 SHA-256、采样率、时长、输入来源和标注性质；MOSS 输出明确标记为辅助标注，不能替代人工真值。对象存储桶为私有桶，报告只记录可审计的对象地址和哈希，不生成匿名公开链接。

```bash
ab pull 'cos-amphion-audio-backup:customer-asr-sdk/2026-09-27-recordings-annotations/mate80-recordings-annotations-20260927.zip' ./mate80-recordings-annotations-20260927.zip
```

PR 不包含这些 ZIP 或任何原始 PCM；合入内容只包含代码、测试和脱敏报告。这样可以复用同一输入做回放，同时避免把客户录音提交到版本库。

## 当前版本公开集结果

| 片段 | 参考/输出人数 | 严格 DER | 250 ms collar、去重叠 DER | 单人归属准确率 | 宏平均召回 | 少数说话人召回 | UNKNOWN 时长 |
|---|---:|---:|---:|---:|---:|---:|---:|
| AISHELL-4 2 人 | 2 / 2 | 10.11% | 3.15% | 93.38% | 90.56% | 84.71% | 5.47 s |
| AISHELL-4 3 人 | 3 / 2 | 18.08% | 2.67% | 95.43% | 56.53% | 0.00% | 12.42 s |
| AISHELL-4 4 人 | 4 / 2 | 42.78% | 25.36% | 71.50% | 29.99% | 0.00% | 29.85 s |
| AliMeeting 2 人 | 2 / 2 | 34.50% | 13.09% | 79.93% | 66.09% | 60.11% | 33.93 s |
| AliMeeting 3 人 | 3 / 3 | 21.60% | 5.50% | 92.99% | 83.34% | 76.62% | 13.06 s |
| AliMeeting 4 人 | 4 / 4 | 45.46% | 10.10% | 84.54% | 49.09% | 24.05% | 47.71 s |

按参考说话人时长加权，AISHELL-4 三个片段为 **23.97% DER**（545.70 s reference speaker time，130.81 s error），AliMeeting 三个片段为 **34.70% DER**（561.08 s，194.67 s error），六个片段合计为 **29.41% DER**（1106.78 s，325.48 s error）。三个片段只输出 2 个角色的事实不能用“整体人数接近”抵消；`AISHELL-4 3/4 人` 中至少一位参考人物的召回为 0，是身份精度失败。

本轮六次 SDK 载体状态均为 PASS：无空 final、无 error、native stream 归零。角色推理 RTF 为 0.565–0.673，finish 到 complete 为 1.19–2.24 s，单轮 RSS 增长为 -4.6–12.0 MiB（门限 64 MiB）。这些是本机 180 秒片段的性能观测，不等于所有设备和全量语料均无积压；当前载体没有公开队列深度字段，因此报告不把 RTF 单独当作队列证明。

## 与公开方法的对照

下表是公开项目各自报告的全量或标准测试集数字，作为参考线；不是在本轮六个片段上重新运行的 head-to-head 结果。数据集变体、通道、重叠处理、后处理和硬件不同，不能直接把百分比相减后宣称排名。

| 方法 | AISHELL-4 | AliMeeting | 条件和来源 |
|---|---:|---:|---|
| 本 SDK `711f5ae7` | **23.97%**（本地 3 片段加权） | **34.70%**（本地 3 片段加权） | 公开集固定子集；严格 DER、无 collar、计入重叠；Mate80 离线回放 |
| pyannote `Community-1` | 11.7% | 20.3%（channel 1） | 官方模型卡的标准公开基准；全自动、无 forgiveness collar、不跳过重叠 |
| pyannote `Precision-2`（托管） | 11.4% | 15.2%（channel 1） | 同一官方模型卡表格；托管商业模型，非端侧离线方案 |
| NVIDIA NeMo Streaming Sortformer v2.1 | — | 11.73% near / 13.55% far（30.4 s latency）；12.60% / 15.60%（1.04 s latency） | NVIDIA 官方 README；无 collar、计入重叠，标准 AliMeeting test near/far |

pyannote 的 `Community-1` / `Precision-2` 数字来自其模型卡的同一张 2025-09 基准表；NVIDIA 数字来自 NeMo 官方仓库对 Streaming Sortformer v2.1 的结果表。两者均说明了各自的评估设定，不能视为本 SDK 在同一切片上的实测对照：[pyannote Community-1 model card](https://huggingface.co/pyannote/speaker-diarization-community-1)、[NVIDIA NeMo diarization README](https://github.com/NVIDIA-NeMo/Speech/blob/main/examples/speaker_tasks/diarization/README.md)。

对照的含义是：当前 SDK 子集结果明显落后于公开方法在其标准测试集上报告的数字，尤其是 4 人和 AliMeeting 片段；本次“孤立短 run 建档”修复解决了一个短会话首人被丢弃的具体状态，但没有解决通用的多身份聚类稳定性、弱说话人召回和重叠/长历史误差。因此不能把短样例通过描述成通用公开集精度修复。

## 回退检查和当前结论

- **19.58 秒四人短会话**：同一 HAP 的公开 `speakerTurns` 为 4 个角色，编号按出场顺序为 0、1、2、3；SDK status PASS，`degraded=false`。
- **123.8 秒长会话**：当前报告有 23 个 final、40 个 turns、4 个角色；与既有 canonical 报告逐项相同，排序后的 `speakerTurns` 内容哈希均为 `2b8340b2767b0229a0b9e7344c5e2a2400af79df5a1e8831d100e81f93943fb8`。当前 RTF 0.522，既有 0.529；当前 finish→complete 1072 ms，既有 905 ms；两次均无 error、无 live stream，RSS 未出现红灯。
- **本次公开集回放**：六次 SDK 生命周期均通过，但身份精度红灯如上。没有做旧提交与 `711f5ae7` 在同一六片段上的 A/B，因此不能声称每一个公开片段都经过严格的版本差分“不回退”。

最终决策：`711f5ae7` 可以作为当前可复现的短会话修复基线和后续公开集优化基线；不能作为“角色分离公开集精度已通过”或“所有场景不会回退”的发布结论。后续若要关闭精度红灯，必须在同一公开集协议上先定位最早的身份丢失/合并状态，再做局部修复和同条件 A/B，不能通过隐藏 UNKNOWN、强制建组或调参掩盖。
