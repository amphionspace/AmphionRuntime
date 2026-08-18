# Harmony AudioCapturer SourceType 外放评测（2026-08-18）

## 结论

在本次固定外放、同设备、同语料配对条件下，`SOURCE_TYPE_VOICE_RECOGNITION`
的总体字符错误率（CER）最低，为 7.68%；`SOURCE_TYPE_MIC` 为 8.28%，高 0.60
个百分点；`SOURCE_TYPE_VOICE_COMMUNICATION` 为 9.68%。

这个排序不能简单解释为 MIC 音频质量更差：MIC 的平均电平、估算信噪比和源波形
包络相关性均优于 VOICE_RECOGNITION，且没有削波。MIC 与 VOICE_RECOGNITION
的 CER 差距主要由少数偶发离群结果造成；去掉唯一一条 MIC 空结果后，两者差距从
0.60 个百分点缩小到约 0.21 个百分点。追加的顺序复验也没有复现“MIC 排在第三次
播放时系统性变差”。

`SOURCE_TYPE_VOICE_COMMUNICATION` 有 61/108 轮发生共 80 次 AudioCapturer
overflow，因此其 CER 受到丢帧混杂，不能与另外两类作无条件质量归因。当前验收条件
下可优先使用 `SOURCE_TYPE_VOICE_RECOGNITION`；MIC 可作为强调原始声学保真度的
可选项；VOICE_COMMUNICATION 应先解决 overflow，再重新评估识别率。

## 测试范围

- Git：`d976331fb51eb4956118c78398d42240f24be543`，测试前后均确认等于当时的
  `origin/main`。
- Harmony 设备：`VYG-AL30`，系统 `6.1.0.135(SP8C00E120R5P7)`。
- 测试载体：最新 main 构建的中英 `ZH_EN` HAP；HAP SHA-256 为
  `1b871a11eef2d2e7b2565fb9cc7b56f2482103f2980afbb14e01f4aa4f787841`。
- 数据：真实业务测试集中的车牌、警务术语、派出所名称三个主题，每个主题 36 条，
  合计 108 条唯一音频。
- 每条音频分别走 MIC、VOICE_RECOGNITION、VOICE_COMMUNICATION，合计 324 个
  独立 session；三种类型按轮换顺序播放，避免一种类型固定落在同一位置。
- 唯一源音频总时长 550 秒，三种类型合计外放 1650 秒；完整运行墙钟时间约
  1 小时 40 分钟。
- Mac 扬声器固定 45% 音量，Harmony 设备通过真实 `AudioCapturer` 采集 16 kHz、
  mono、S16LE PCM；每个 session 重启测试应用，除 SourceType 外保持识别参数一致。
- CER 使用 Unicode NFKC、小写化并移除空白、标点和符号后的中文字符级 micro CER。

## 总体结果

| SourceType | 样本 | micro CER | 字符错误 / 参考字符 | 空结果 | 平均 RMS | overflow 事件 / 受影响轮次 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MIC | 108 | 8.28% | 195 / 2356 | 1 | -32.9 dBFS | 0 / 0 |
| VOICE_RECOGNITION | 108 | **7.68%** | 181 / 2356 | 0 | -37.6 dBFS | 0 / 0 |
| VOICE_COMMUNICATION | 108 | 9.68% | 228 / 2356 | 0 | -30.9 dBFS | 80 / 61 |

## 分主题结果

| 主题 | 参考字符 | MIC | VOICE_RECOGNITION | VOICE_COMMUNICATION |
| --- | ---: | ---: | ---: | ---: |
| 车牌 | 747 | 3.61% | **3.08%** | 3.88% |
| 警务术语 | 818 | 8.31% | **8.07%** | 9.17% |
| 派出所名称 | 791 | 12.64% | **11.63%** | 15.68% |

三个 SourceType 在派出所名称主题上都更难，说明专名是本数据集的主要精度风险。

## MIC 与 VOICE_RECOGNITION 的配对分析

108 个同语料配对中，MIC 更好 20 条、持平 63 条、更差 25 条。MIC 总计比
VOICE_RECOGNITION 多 14 个字符错误，但差距集中在少数离群样本：

- 唯一一条 MIC 空结果贡献 18 个错误；同条 VOICE_RECOGNITION 也有 9 个错误，
  因而该样本贡献净差 9 个错误。
- 另外几条主要表现为偶发句首漏识别，而不是全量样本上的稳定退化。
- 排除空结果样本后，MIC 为 177/2338（7.57%），VOICE_RECOGNITION 为
  172/2338（7.36%），差距约 0.21 个百分点。

因此，本轮结果支持“VOICE_RECOGNITION 在该条件下点估计最低”，但不支持“MIC
采集路径整体或稳定地更差”。

## 音频信号指标

| 指标 | MIC | VOICE_RECOGNITION |
| --- | ---: | ---: |
| 平均 RMS | -32.87 dBFS | -37.59 dBFS |
| 中位估算 SNR | 21.20 dB | 16.68 dB |
| 与外放源的中位包络相关性 | 0.896 | 0.837 |
| 最大削波率 | 0 | 0 |

这些指标表明，本次实验中 MIC 捕获的波形更接近外放源且基础信号指标更高；但
RMS、估算 SNR 和包络相关性不是完整的感知音质或 ASR 可识别性指标。
VOICE_RECOGNITION 的系统语音前处理会改变波形，其相关性降低不等同于主观听感或
识别价值降低。因此应表述为“MIC 在本实验中的原始声学保真指标更好”，而不是泛化为
“MIC 音频质量一定更好”。

## 播放顺序复验

长测中按 MIC 所在位置汇总，MIC 相对 VOICE_RECOGNITION 的配对字符错误差为
第 1 位 -13、第 2 位 -1、第 3 位 +28。进一步检查发现：

- 三个位置的配对差中位数均为 0。
- 第 3 位的 +28 完全由 4 条离群样本聚集造成；移除这 4 条后变为 -6。
- 固定分组置换检验得到约 `p=0.129`，不足以证明稳定顺序效应。
- 使用一条原长测中 MIC 丢句首的典型语料追加 9 次 MIC 真机复验：
  `VOICE_RECOGNITION → MIC`、`VOICE_COMMUNICATION → MIC`、
  `VOICE_RECOGNITION → VOICE_COMMUNICATION → MIC` 各 3 次。9 次中 8 次完全
  正确；原始第三位丢句首没有复现，最后一种三步顺序 3/3 完全正确。

结论是：现有证据没有证明第三次播放或 SourceType 切换会导致 MIC 系统性劣化；
原长测的顺序差异应视为离群结果的偶然聚集，而不是已确认缺陷。

## 有效性边界

- 这是扬声器到设备麦克风的端到端实验，结果包含房间声学、扬声器、设备
  AudioCapturer 前处理和 ASR 的共同影响，不等同于直接喂同一 PCM 的纯模型 CER。
- 每条语料每种 SourceType 在主实验中只运行一次；0.60 个百分点的小差距没有通过
  多设备、多房间或整集重复实验建立统计稳定性。
- VOICE_COMMUNICATION 的 overflow 是明确混杂；修复丢帧前不能把其全部差距归因
  于 SourceType 前处理或模型。
- 测试只覆盖当前一台 Harmony 设备及其系统版本，不代表所有 Harmony 机型。
- 原始 PCM、逐句文本、本机路径和设备唯一标识未纳入仓库，避免提交业务语料与本地
  环境信息；仓库仅保留脱敏汇总。

结构化汇总见
[`evidence/source-type-evaluation/20260818-d976331/report.json`](../evidence/source-type-evaluation/20260818-d976331/report.json)。
