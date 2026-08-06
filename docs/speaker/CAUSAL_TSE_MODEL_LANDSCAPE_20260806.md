# Causal Target-Speaker TSE 开源模型图谱与 Linux 验证计划（2026-08-06）

## 结论摘要

截至 2026-08-06，开源 target speaker extraction（TSE）并不是只有
`tse-conv-tasnet-48k`。此前调研遗漏了 REAL-TSE 官方 causal BSRNN、PS4、DENSE、正负 enrollment
TSE、ESPnet TD-SpeakerBeam、USEF-TSE、ConVoiFilter、SoloSpeech 等候选。

但必须区分三种不同的“可用”：

1. **可下载验证**：有代码和权重，能在 Linux 对混合音频与 enrollment 做推理；
2. **网络结构 causal**：输出不依赖未来输入，或满足公开的有界延迟约束；
3. **可持续流式部署**：公开接口显式传递跨 chunk 状态，固定小帧输入，定义 flush，并可导出到端侧
   runtime。

公开候选中，多数只满足第一项；REAL-TSE causal baseline、DENSE 等满足前两项，但官方推理仍以整段
forward 为主；目前接口层最接近第三项的是 `penta2himajin/tse-conv-tasnet-48k`，它提供固定 10 ms
输入和显式状态张量，但公开质量证据存在尚未解释的矛盾，不能未经独立评测直接定为生产模型。

面向 AmphionRuntime，推荐组合是：

- **causal 质量基线**：REAL-TSE `spk_emb_causal_100` 与 `tfmap_context_causal_100`；
- **真实中英文、ASR-friendly teacher**：PS4；
- **stateful runtime 原型**：`tse-conv-tasnet-48k` v3；
- **后续训练参考**：REAL-TSE/WeSep recipe、DENSE、SpeakerBeam-SS；
- **离线交叉基线**：ESPnet TD-SpeakerBeam、ClearerVoice SpEx+、USEF-TSE、ConVoiFilter。

所有有公开代码和权重的候选都可以先在 Linux 服务器完成算法验证；但 Linux 结果不能代替
Android/Harmony 的算子、内存、功耗、音频线程和热降频验收。

## 本项目任务边界

- 输入为 16 kHz 单通道 PCM；目标身份由独立 enrollment 音频指定。
- 输出保持时间轴的目标人波形，继续送入当前中英 `ZH_EN` 流式 ASR。
- C2/C3 是完全或部分重叠下的内容归属，不是单纯 speaker verification、VAD 或 diarization。
- 生产模型必须支持 target-absent，不得在只有非目标人的音频中“救回”伪目标语音。
- 主指标为目标 ASR CER/WER、目标关键词保留、非目标词泄漏和 clean/no-overlap 退化；SI-SDR、
  speaker similarity、DNSMOS 只作互补诊断。
- “RTF 小于 1”不代表 causal；“网络为 causal”也不代表已有跨 chunk 状态接口。
- 最终端侧目标仍是 16 kHz、小型、enrollment-conditioned、stateful causal TSE，不直接交付大型
  offline checkpoint。

## 可用性分级

| 等级 | 定义 | 可得出的结论 |
| --- | --- | --- |
| L1：Linux offline 可运行 | 公开代码和权重，整段输入可推理 | 算法质量、领域迁移、ASR 可懂度 |
| L2：causal 可验证 | 模型结构或官方 track 有因果/有界延迟约束 | 可用前缀一致性实验检查未来依赖 |
| L3：stateful streaming 可运行 | 固定小 chunk，显式输入/输出状态和 flush | 可验证长期流式语义、分帧一致性和 RTF |
| L4：端侧可交付 | 已通过目标 runtime 导出、量化和真机资源门 | 才能进入 Android/Harmony SDK pilot |

当前没有公开候选可以未经适配直接标为 L4。

## 候选总表

| 候选 | Exact TSE | 权重 | Causal | 公开 stateful chunk API | Linux 验证 | 当前定位 |
| --- | --- | --- | --- | --- | --- | --- |
| REAL-TSE `spk_emb_causal_100` | 是 | 有 | 是，online baseline | 无 | 可以 | causal 质量基线 |
| REAL-TSE `tfmap_context_causal_100` | 是 | 有 | 是，online baseline | 无 | 可以 | causal 质量基线，优先于纯 embedding A/B |
| `tse-conv-tasnet-48k` v3 | 是 | 有 | 是，zero-lookahead | **有，10 ms + 显式状态** | 可以，CPU/ORT 也可 | runtime ABI 原型；质量待独立确认 |
| Positive/Negative Enrollment TSE | 是 | 有 | extraction branch 为 causal TF-GridNet | 无 | 可以 | 嘈杂 enrollment 专项候选 |
| DENSE | 是 | 大文件/权重不完整 | 是 | 论文式 chunk-wise 评测，非部署 API | 部分可以 | 动态 embedding 与训练参考 |
| SpeakerBeam-SS | 是 | 无可靠官方权重 | 是 | 未公开 | 不能可靠复现 | 轻量 SSM 架构参考 |
| PS4 | 是 | 有 | 否 | 无 | 可以，推荐 GPU | 真实中英文、ASR-friendly teacher |
| WeSep BSRNN + ECAPA Vox1 | 是 | 有 | 否，默认双向 LSTM | 无 | 已验证 | 内容恢复 teacher；资源门失败 |
| ESPnet TD-SpeakerBeam | 是 | 有 | 否，公开配置为 `causal: false` | 无 | 可以 | 可复现标准基线 |
| ClearerVoice SpEx+ | 是 | 有 | 否 | 无 | 可以 | 8 kHz 传统 TSE 上界 |
| USEF-TSE | 是 | 有 | 默认离线 | 无 | 可以 | embedding-free 对照；非商用许可 |
| ConVoiFilter | 是 | 有 | 默认离线/长 chunk | 无 | 可以 | TSE 与 ASR 联合训练参考 |
| SoloSpeech | 是 | 有 | 否 | 无 | 可以，推荐 GPU | 生成式质量/OOD 上界；非商用许可 |
| USEF-Laura-TSE | 是 | 有 | 否 | 无 | 只可做公开推理 | 生成式研究参考；训练未完整公开 |
| MeanFlowTSE 社区 ONNX | 是 | 有 | 否 | 无 | 可以 | 数百 MB、推理慢，不进入端侧候选 |
| TSExcalibur | 工具箱 | 部分有 | 依模型而定 | 无统一接口 | 可以但需整理 | 多模型 offline benchmark |

`Exact TSE` 表示模型以目标人的 enrollment/reference 为条件输出该目标人的波形。盲分离后按声纹选流、
主导说话人抑制、target sound extraction 和 diarization 均不等价。

## 第一优先级：公开 causal 候选

### REAL-TSE causal BSRNN baselines

[REAL-TSE Challenge](https://real-tse.github.io/challenge/) 定义了普通话和英语真实会话中的 target speaker
extraction，并把在线轨有效延迟限制为不超过 100 ms。官方提供四个 16 kHz、基于 BSRNN、在
Libri2Mix-100 训练 150 epochs 的 baseline：

- `spk_emb_100`：offline，ECAPA speaker embedding；
- `spk_emb_causal_100`：online，ECAPA speaker embedding；
- `tfmap_context_100`：offline，TF-Map + contextual embedding；
- `tfmap_context_causal_100`：online，TF-Map + contextual embedding。

2026-08-04 的旧调研写着 checkpoint 只通过邮件发给已注册团队；该信息随后发生变化。当前
[REAL-TSE WeSep baseline 仓库](https://github.com/REAL-TSE/wesep-real-tse) 已在 README 提供四个目录对应的
公开 Google Drive 下载入口，并给出 `mixture + enroll -> output` 的推理命令。因此两套 causal baseline
现在应进入“Linux 可下载验证”集合。

限制：官方 `evaluate.py` 是整段文件推理，模型 forward 没有把 recurrent hidden/cell state 暴露为跨
chunk 输入输出。它可以验证 causal 网络质量，但不能据此声称已经有 SDK 可用的持续流式实现。若质量门
通过，还需要实现：

- streaming STFT/iSTFT overlap-save；
- 各层 LSTM 状态缓存与 session 隔离；
- 固定 chunk 输入、尾帧 flush 和 reset；
- 整段 causal reference 与 stateful 输出 parity；
- ONNX 导出和目标 runtime 算子检查。

官方也明确提醒这些 baseline 训练于合成 Libri2Mix、固定 3 秒和完全重叠条件，真实会话结果应视为
lower bound，而不是生产上限。

### `penta2himajin/tse-conv-tasnet-48k`

[模型卡](https://huggingface.co/penta2himajin/tse-conv-tasnet-48k) 与
[mellonella 仓库](https://github.com/penta2himajin/mellonella)提供了当前候选中最完整的公开 stateful
接口：48 kHz 下固定 480 samples/10 ms 输入、89 个状态张量、zero lookahead、ONNX 和 Rust runtime
示例，约 1.45M 参数，speaker condition 为 192 维 ECAPA embedding。

它应进入第一轮，但定位是 **流式工程候选而不是默认质量冠军**：

- [PR #151](https://github.com/penta2himajin/mellonella/pull/151) 记录 v1/v2 的 EMA 在
  `torch.compile` 下静默失效，旧版本曾导出近似随机初始化权重；只允许测试修复后的 v3。
- 当前模型卡声称 train/validation/test SI-SDR 约为 `9.96/8.61/8.55 dB`，但仓库公开
  [`metrics.json`](https://huggingface.co/penta2himajin/tse-conv-tasnet-48k/blob/main/metrics.json)
  的末轮 validation SI-SDR 约为 `0.735 dB`。在作者解释或本项目独立复验前，质量结论记为
  `INCONCLUSIVE`。
- 训练数据路径需要核对 enrollment 是否来自与目标混合源不同的独立 utterance；若 condition 总是从同一
  target utterance 生成，可能高估跨句和跨信道身份泛化。
- 48 kHz 与本项目 16 kHz ASR 不匹配，会增加重采样、前端与时域网络计算。若方案成立，仍应评估重训
  16 kHz 版本。

### Positive/Negative Enrollment TSE

[官方实现](https://github.com/xu-shitong/TSE-through-Positive-Negative-Enroll)公开代码和 checkpoint，目标是
从带噪 enrollment 中同时利用 target-active positive segment 与 target-inactive negative segment。其
extraction branch 使用 causal TF-GridNet blocks，适合注册素材本身来自嘈杂真实录音的情况。

它不是现有“单段干净 enrollment”API 的直接替换：业务必须能够可靠构造正、负 enrollment 片段；官方
也没有提供跨 chunk state runtime。因此只在普通 enrollment 基线失败、且产品能提供正负片段时提升优先级。

### DENSE

[DENSE](https://github.com/wyw97/DENSE) 是 Dynamic Embedding Causal Target Speech Extraction，官方代码
包含真实 chunk-wise causal evaluation，适合研究目标人在会话中声学特征动态变化时如何更新条件表示。
仓库同时说明大型文件未上传，代码和权重完整性不足以支撑直接部署；定位为训练结构参考。

### SpeakerBeam-SS

[SpeakerBeam-SS](https://www.isca-archive.org/interspeech_2024/sato24_interspeech.html)使用 S4D/state-space
模型和轻量 Conv-TasNet，论文报告在质量相近时相对 causal Conv-TasNet 降低 78% RTF。没有确认到官方
公开权重或完整 runtime。社区 checkpoint 缺模型卡、来源、许可和可复现指标，不能进入正式下载候选。

## 第二优先级：offline teacher 与交叉基线

### PS4

[PS4](https://huggingface.co/TaurenMountain/PS4) 是 16 kHz BSRNN + ECAPA TSE，Apache-2.0 模型卡公开
checkpoint。它从公开 WeSep backbone 出发，在 AISHELL-4、AliMeeting、AMI、CHiME-6 的真实会议数据上
构造 REAL-PS4，联合优化：

- Whisper large-v3 ASR cross-entropy；
- speaker similarity ranking；
- frame-level target VAD；
- differentiable DNSMOS。

它包含中文和英文真实远场条件，目标也直接包含 ASR 可懂度，因此是当前最相关的 offline teacher/质量
上界之一。但模型是 full-context BSRNN，checkpoint 约 283 MB，不能直接作为 causal 端侧候选。

### ESPnet TD-SpeakerBeam

[ESPnet LibriMix TD-SpeakerBeam](https://huggingface.co/espnet/Wangyou_Zhang_librimix_train_enh_tse_td_speakerbeam_raw)
公开 recipe、权重和指标，模型卡配置明确为 `causal: false`，test enhanced SI-SNR 约 10.74 dB；
[WSJ0-2mix 版本](https://huggingface.co/espnet/Wangyou_Zhang_wsj0_2mix_train_enh_tse_td_speakerbeam_raw)
报告约 17.11 dB。它适合做稳定、可复现的英语 synthetic offline 基线，不应被当作端侧候选。

### ClearerVoice SpEx+

[ClearerVoice-Studio audio-only TSE](https://github.com/modelscope/ClearerVoice-Studio/tree/main/train/target_speaker_extraction)
提供 SpEx+ 代码和 checkpoint，公开复现报告 WSJ0-2mix-extr SI-SDRi 17.1 dB、SDRi 17.5 dB。其条件
是 reference speech，但模型为 8 kHz、英语、noncausal。ClearVoice 易用推理包中的 TSE 入口主要是带
视频条件的 AV_MossFormer2，不能误认为同一模型；audio-only SpEx+ 需要使用训练/评测目录适配推理。

### USEF-TSE、ConVoiFilter 与生成式模型

- [USEF-TSE](https://github.com/ZBang/USEF-TSE)：universal speaker embedding-free TSE，公开代码与权重；
  可比较固定 speaker encoder 是否成为跨域瓶颈。许可证为 CC BY-NC 4.0，不进入商用交付候选。
- [ConVoiFilter](https://github.com/nguyenvulebinh/voice-filter)：公开代码和权重，论文把 TSE 与 ASR 联合
  优化；适合研究“增强指标提高但 CER 退化”的问题。当前实现默认长 chunk/整段，不是真流式。
- [SoloSpeech](https://github.com/WangHelin1997/SoloSpeech)：级联生成式 TSE，公开 demo、代码和权重；
  适合质量/OOD 上界，不适合低时延端侧，且为非商用许可。
- [USEF-Laura-TSE](https://github.com/ZBang/USEF-Laura-TSE)：判别式与生成式结合，公开 inference 和
  checkpoint，但训练代码尚未完整发布，许可证为 CC BY-NC 4.0。
- [MeanFlowTSE](https://huggingface.co/nmj21c/MeanFlowTSE)：社区 ONNX 转换包含数百 MB 权重，公开延迟
  已明显超出端侧预算；只保留离线研究价值。
- [TSExcalibur](https://github.com/youzhenghai/TSExcalibur)：汇集 SpeakerBeam、SpEx+、SpEx++、
  DPRNN-TSE、DPRNN-IRA、X-SepFormer 等模型与部分权重，适合搭统一 benchmark，但当前文档和调用接口
  仍偏研究阶段。

### AnyEnhance / AnyEnhance2

[AnyEnhance](https://arxiv.org/abs/2501.15417) 可以通过 prompt/reference 表达 TSE，但其核心是两阶段、
masked generative enhancement，并包含迭代 self-critic。它适合离线 demo、可行性上界或 teacher，不满足
本项目的 causal、低延迟、低资源端侧边界。即使本地 AnyEnhance2 工程能在 Linux 跑通，也不能因此提升
为生产候选。

## 论文级工业参考：方向相关但没有可直接复用权重

- [VoiceFilter-Lite](https://research.google/pubs/voicefilter-lite-streaming-targeted-voice-separation-for-on-device-speech-recognition/)：
  streaming、on-device、feature-domain、ASR-oriented；论文公开量化资源和 WER 收益，但没有官方模型
  权重，是最终产品形态的重要参考。
- [E3Net](https://arxiv.org/abs/2204.00771)：实时 personalized speech enhancement，包含知识蒸馏及
  ASR/target-speaker-over-suppression-aware 目标；没有官方权重。
- [Personalized PercepNet](https://arxiv.org/abs/2106.04129)：实时低复杂度个性化增强；没有可直接复用模型。
- [TargetVoice](https://www.isca-archive.org/interspeech_2025/pallala25_interspeech.html)：面向 edge 的小型
  speaker encoder 与 extraction model；未找到官方代码和权重。

这些资料用于确定网络、loss、量化和 latency 预算，不能列入当前 Linux checkpoint A/B。

## 相邻模型：可以运行但不是 exact target-speaker TSE

| 模型 | 实际任务 | 为什么不能替代 TSE |
| --- | --- | --- |
| NVIDIA Real-time RE-USE | 单通道实时 speech enhancement | 没有 enrollment/target identity |
| Hush | zero-lookahead 背景说话人抑制 | 保留主导说话人，不能指定注册目标人 |
| Waveformer | streaming target sound extraction | 条件是声音类别，不是 speaker identity |
| RE-SepFormer / Conv-TasNet | 盲两人分离 | 输出流无目标身份，仍需声纹 permutation selection |
| diarization / speaker VAD | 说话人活动区间 | 完全重叠时不能生成目标人的独立波形 |
| AV-MossFormer2 / AV-CrossNet | audio-visual TSE | 依赖目标人视频，不符合当前 audio-only 输入 |

本项目已经用盲 Conv-TasNet 证明：C1～C3 小样例内容可以恢复，但在 60 个 speaker-disjoint other-only
测试中有 8 个 false rescue。因此不能用“轻量且能分离”替代 enrollment-conditioned 和 target-absent 门。

## Linux 服务器验证能力与边界

### 可以在 Linux 完成

- 下载、哈希和许可证快照；
- PyTorch/ONNX 整段推理与 CPU/GPU RTF；
- C1～C3、target-only、other-only、target-absent、clean no-overlap；
- 独立 enrollment、跨语言、跨设备和带噪 enrollment；
- 同一前缀接不同未来的 causal prefix-invariance；
- 相同 PCM 使用 10/20/40 ms 和随机 chunk 切分的结果一致性；
- silence、短 utterance、长 utterance、30 分钟 session 的 NaN、RSS 和状态漂移；
- 下游 ZH_EN ASR 的 CER/WER、目标词保留和非目标词泄漏；
- PyTorch/ONNX FP32 parity 和初步量化退化。

### 不能由 Linux 替代

- Harmony NNRT / Android NNAPI 或实际 CPU backend 的算子支持；
- 目标 ARM 设备持续 RTF、峰值 RSS、功耗和热降频；
- 音频 callback 线程抖动、系统调度和实时采集边界；
- SDK session 隔离、`onStart` 重入、`finish/cancel`、`isFinal/isLast/onComplete` 生命周期；
- 最终 FP16/INT8 在目标 runtime 的数值偏差。

因此 Linux 是模型筛选门，不是发布门。

## 统一 Linux 验证矩阵

第一轮只运行四个互补候选：

1. REAL-TSE `spk_emb_causal_100`；
2. REAL-TSE `tfmap_context_causal_100`；
3. PS4；
4. `tse-conv-tasnet-48k` v3。

第二轮仅在第一轮结果需要解释时补充 ESPnet TD-SpeakerBeam、Positive/Negative Enrollment TSE 和
ClearerVoice SpEx+。不并行搭建全部生成式模型。

每个模型使用独立 Conda/容器环境，避免 WeSep、ESPnet、ClearerVoice 和生成式栈的 PyTorch/CUDA 依赖
互相污染。所有模型统一接收：

- `mixture.wav`；
- 与 mixture 中目标源不同句的 `enrollment.wav`；
- 如有条件，target 和 other 独立源及对齐文本；
- 固定 16 kHz mono 评测副本；48 kHz 原生模型另保留一次原生输入，分别归因重采样损失。

建议结果目录：

```text
results/tse/<model>/<case>/
  input.json
  extracted.wav
  metrics.json
  asr.json
  timing.json
  streaming.json
  environment.json
```

其中：

- `input.json`：音频 SHA-256、采样率、时长、speaker/enrollment 对应关系；
- `metrics.json`：SI-SDR、speaker similarity、DNSMOS 及 target-active/absent 能量；
- `asr.json`：mixture/extracted/reference 的完整 final 文本、CER/WER 和关键词断言；
- `timing.json`：CPU/GPU、线程数、wall time、RTF、峰值 RSS；
- `streaming.json`：chunk 尺寸、lookahead、state 数量、flush、分帧 parity 和 prefix-invariance；
- `environment.json`：代码 commit、checkpoint 哈希、Python/PyTorch/ORT/CUDA 版本与许可证链接。

## 通过门与停止条件

### 算法门

- C2/C3 extracted ASR 保留目标词且不泄漏已知非目标词；
- target-only/clean 不产生不可接受的 CER 退化；
- other-only/target-absent 不产生非空伪目标文本；
- enrollment 必须来自独立 utterance，不能用 mixture 内的目标真值作为 condition；
- 至少在受控集报告 target-present 与 target-absent 两类指标，不能只报告平均 SI-SDR。

### causal/stateful 门

- 相同输入前缀、不同未来输入，在有效 lookahead 之外的输出一致；
- 同 PCM 以不同 chunk 切分时输出和 endpoint 决策一致；
- state 可按 session reset，两个 session 交错时不串扰；
- silence、尾帧补齐和 flush 不产生 NaN、重复样本或丢失尾音；
- 连续运行 30 分钟后 RSS 和 state 数量有界。

### 资源初筛门

- Linux CPU 先证明 sustained RTF `< 1`；
- 只有通过算法门的模型才做 ONNX 和量化；
- 端侧 pilot 建议预算继续使用模型 `< 30 MB`、额外 RSS `< 150 MB`、目标设备 sustained RTF
  `< 0.2`，这些是项目门槛，不是公开 checkpoint 的性能承诺。

任一公开模型若只在 C1～C3 三个案例通过、但 target-absent/open-set 失败，必须停止真机扩展，不能通过
调能量、事后文本选流或放宽全局空结果率掩盖。

## 推荐决策顺序

1. **先在 Linux 复验 REAL-TSE 两套 causal baseline。** 它们最接近 16 kHz、enrollment-conditioned、
   online TSE 目标，可回答公开 causal 模型的质量下限。
2. **以 PS4 冻结真实中英文 offline 上界。** 若 PS4 显著改善 CER/目标泄漏，说明数据与 ASR-aware
   训练比继续更换合成集 separator 更重要。
3. **以 `tse-conv-tasnet-48k` v3 验证 stateful runtime。** 必须独立核对质量、独立 enrollment、
   target-absent、silence NaN 和任意 chunk 切分，不复用模型卡单一指标。
4. **若 REAL-TSE 质量可用但不满足资源门，启动 16 kHz 小模型训练/蒸馏。** teacher 可用 PS4/WeSep，
   student 优先考虑 cached-state Conv-TasNet、TD-SpeakerBeam、DENSE 或轻量 BSRNN。
5. **通过 Linux 算法与流式语义门后再进入 Harmony/Android。** 不把模型集成和 SDK 生命周期修改混成
   一个补丁。

## 调研更正与证据状态

- **已更正**：REAL-TSE baseline 已从“注册团队邮件可得”变为 baseline 仓库公开下载入口；挑战真实
  dev/eval 数据仍限注册团队，两者必须区分。
- **已更正**：公开 causal TSE 不只 `tse-conv-tasnet-48k`；但后者仍是当前最完整的公开 stateful
  chunk runtime 示例。
- **保持不变**：WeSep offline checkpoint 已证明 C1～C3 内容可恢复，但约 1.94 GB 峰值 RSS，不直接进
  Harmony。
- **保持不变**：盲 Conv-TasNet 的 open-set/target-absent 失败证明 enrollment-conditioned TSE 是必要
  条件。
- **尚未证明**：上述新候选尚未在本项目相同 C1～C3、60 speaker open-set 和 ZH_EN ASR 上完成统一
  实测；本文件是候选与验证计划，不把论文或模型卡结果写成项目 PASS。

## 一手来源

- [REAL-TSE Challenge](https://real-tse.github.io/challenge/)
- [REAL-TSE WeSep baseline 与公开 checkpoint 入口](https://github.com/REAL-TSE/wesep-real-tse)
- [WeSep](https://github.com/wenet-e2e/wesep)
- [PS4 模型卡](https://huggingface.co/TaurenMountain/PS4)
- [`tse-conv-tasnet-48k` 模型卡](https://huggingface.co/penta2himajin/tse-conv-tasnet-48k)
- [mellonella](https://github.com/penta2himajin/mellonella)
- [Positive/Negative Enrollment TSE](https://github.com/xu-shitong/TSE-through-Positive-Negative-Enroll)
- [DENSE](https://github.com/wyw97/DENSE)
- [SpeakerBeam-SS](https://www.isca-archive.org/interspeech_2024/sato24_interspeech.html)
- [ESPnet TD-SpeakerBeam LibriMix](https://huggingface.co/espnet/Wangyou_Zhang_librimix_train_enh_tse_td_speakerbeam_raw)
- [ClearerVoice-Studio TSE](https://github.com/modelscope/ClearerVoice-Studio/tree/main/train/target_speaker_extraction)
- [USEF-TSE](https://github.com/ZBang/USEF-TSE)
- [ConVoiFilter](https://github.com/nguyenvulebinh/voice-filter)
- [SoloSpeech](https://github.com/WangHelin1997/SoloSpeech)
- [USEF-Laura-TSE](https://github.com/ZBang/USEF-Laura-TSE)
- [TSExcalibur](https://github.com/youzhenghai/TSExcalibur)
- [AnyEnhance](https://arxiv.org/abs/2501.15417)
- [VoiceFilter-Lite](https://research.google/pubs/voicefilter-lite-streaming-targeted-voice-separation-for-on-device-speech-recognition/)
