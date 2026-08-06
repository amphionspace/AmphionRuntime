# 目标说话人提取与重叠语音候选调研（2026-08-04）

> **2026-08-06 更新：** 本文保留 2026-08-04 当时的候选状态与已完成实验。REAL-TSE baseline
> checkpoint 后续已在官方 baseline 仓库提供公开下载入口，且补充调研发现了更多 causal、offline
> teacher 和研究级候选。最新模型图谱、可用性分级与统一 Linux 验证计划见
> [Causal Target-Speaker TSE 开源模型图谱与 Linux 验证计划](CAUSAL_TSE_MODEL_LANDSCAPE_20260806.md)。
> 下文“checkpoint 仅发注册团队/当前不可公开取得”只描述 2026-08-04 的信息状态，不再作为当前结论。

## 结论摘要

客户 C2/C3 的失败层不是句末声纹阈值，也不是 diarization，而是单通道重叠语音中的内容归属。当前
`ERes2Net + Speaker VAD + ASR` 只能决定“这一段像不像目标人”或“何时切断”，不能从同一时刻的混合
波形中恢复目标人的字词。因此，后续实验必须进入 speaker-conditioned target speaker extraction
（TSE）或真正的 target-speaker ASR（TS-ASR）。

截至 2026-08-04，旧结论“SpEx+ / 开源 TSE 没有公开权重”已经过期。现在至少有两个官方公开、可下载
的 audio-only、enrollment-conditioned TSE 权重：

1. **P0：WeSep BSRNN + ECAPA（16 kHz）**。这是与 C2/C3 任务最接近、可直接下载并调用的候选，优先
   做主机离线可行性实验；但它使用双向 LSTM、FP32 权重约 283 MB，官方部署路径是 TorchScript / LibTorch，
   不是 Harmony 可直接交付形态。
2. **P1：ClearerVoice-Studio SpEx+（8 kHz）**。同样是真正 reference-conditioned TSE，官方权重和代码
   均为 Apache-2.0，可作为第二个独立模型交叉验证；但它是 WSJ0 英语、非因果、8 kHz，且官方只给训练/
   评测入口，没有现成 ONNX 或端侧 runtime。

另设一个**短期无训练候选：Asteroid Conv-TasNet Libri2Mix 16 kHz 两人分离 + 当前 ERes2Net 选择目标流**。
它不是真正 TSE，但权重只有约 20.4 MB，能回答“通用分离是否已经足以让 C2/C3 的目标字词恢复”。
2026-08-04 补测后，整段和固定 2 秒分块形态都让 C1～C3 通过严格文本门，因此它从负对照提升为唯一
需要进入开放集 L2 的短期候选。后续 60 个 other-only test 出现 8 个非空 false rescue，归因证实错误
来自冻结 ERes2Net 短块工作点已接受原始非目标语音，而不是 RMS 残留放大；因此该候选已停止，不进入
Harmony 扩展 pilot。

这三个候选都只适合先证明算法可行性。当前没有一个同时满足“中文真实重叠、外部 enrollment、流式、
Harmony 端侧、官方 ONNX、可直接商用交付”。正式端侧目标仍应是 purpose-trained causal TSE；Google
VoiceFilter-Lite 已证明 2.2 MB INT8 流式模型可以成立，但没有发布可下载权重。

## 任务边界和硬约束

- 输入：16 kHz、单通道 PCM；目标人通过独立 enrollment 音频指定。
- 输出：保持时间轴的目标人波形，继续复用当前中英 `ZH_EN` ASR；不在第一阶段替换 ASR。
- 核心业务断言：C2/C3 的目标关键词（当前为“上海”）应保留，非目标关键词（当前为“你好”）不得泄漏。
- 纯 diarization 只能给出“谁在何时活动”；完全重叠时它不能生成两个独立波形，不能单独关闭 C2/C3。
- 通用两人分离没有 target identity，必须再用 enrollment embedding 做 permutation selection；它是负对照，
  不是最终架构。
- 离线候选通过不代表能上真机；流式因果性、模型大小、峰值 RSS、端到端 RTF、ONNX 算子和量化退化必须
  独立验收。

## 2026 年新增的一手证据

### REAL-TSE 已把真实中英 TSE 变成独立评测轨

[REAL-TSE Challenge](https://real-tse.github.io/challenge/) 明确定义了“混合语音 + enrollment → 目标人波形”，
覆盖普通话和英语真实会话、自然重叠、混响与噪声，并同时设在线和离线两条轨。官方提供四个 16 kHz
BSRNN baseline，其中包含 ECAPA speaker embedding 的 offline/causal 版本。这直接支持本项目将 C2/C3 从
speaker verification / endpoint 轨拆到 TSE 轨。

但该挑战的 baseline checkpoint 仅通过邮件发给已注册团队，且注册已于 2026-05-31 关闭，因此它们不是
当前可公开自动下载的候选。它们可作为后续训练设计基线，不能列为这次“立即可跑”的输入。

2026 年 7 月发布的 [MERL 获胜系统报告](https://www.merl.com/publications/TR2026-112) 还给出一个重要方向：
获胜系统没有更换核心 BSRNN 架构，主要收益来自真实远场伪目标、噪声/混响、enrollment 退化和分阶段训练。
这意味着若 P0 能在 C2/C3 上产生正信号，下一优化优先级应是中文真实域数据与训练配方，而不是继续堆更大
separator。

### WeSep 已有公开预训练 CLI，README 的 checkbox 落后于代码

[WeSep 官方仓库](https://github.com/wenet-e2e/wesep) README 仍把 “Pretrained models / CLI Usage” 显示为
未完成，但当前代码的
[`Hub`](https://github.com/wenet-e2e/wesep/blob/master/wesep/cli/hub.py) 已内置
`bsrnn_ecapa_vox1.tar.gz`，
[`Extractor`](https://github.com/wenet-e2e/wesep/blob/master/wesep/cli/extractor.py) 已提供混合音频与 enrollment
的直接推理接口。官方 [ModelScope 资产](https://www.modelscope.cn/datasets/wenet/wesep_pretrained_models/summary)
标记 Apache License 2.0。

本次直接检查下载产物得到：压缩包约 249 MiB，`avg_model.pt` 为 282,633,800 bytes；其中推理模型为
27.63M 参数，checkpoint 另含 42.85M 个 optimizer state 元素，二者合计约 70.5M storage，不能把后者
全算成推理参数。配置为 16 kHz、BSRNN、6 repeats、ECAPA-TDNN 192 维 embedding，
训练输入为 VoxCeleb1 动态两人混合。当前
[`BSRNN`](https://github.com/wenet-e2e/wesep/blob/master/wesep/models/bsrnn.py) 默认使用双向 LSTM，故该公开
权重应按 offline 模型处理；`run_online.sh` 的 “online” 指在线数据混合，不等于流式因果推理。

### ClearerVoice-Studio 已发布 audio-only SpEx+ checkpoint

[ClearerVoice-Studio TSE 官方说明](https://github.com/modelscope/ClearerVoice-Studio/tree/main/train/target_speaker_extraction)
列出了 audio-only、reference-speech-conditioned SpEx+，并给出
[官方 checkpoint](https://huggingface.co/alibabasglab/log_wsj0-2mix_speech_SpEx-plus_2spk)。模型卡标记
Apache-2.0；`last_best_checkpoint.pt` 为 134,255,410 bytes。配置和
[SpEx+ 论文](https://arxiv.org/abs/2005.04686) 都表明它是 8 kHz WSJ0-2mix-extr、101 个训练 speaker、
非因果模型。官方复现实验报告 SI-SDRi 17.1 dB、SDRi 17.5 dB，但这些数字不能外推到中文真实重叠。

### 当前公开流式/端侧结果仍没有可直接交付权重

[VoiceFilter-Lite 官方论文页](https://google.github.io/speaker-id/publications/VoiceFilter-Lite/) 展示了单通道、
target-conditioned、流式端侧方案：256 节点版本量化后 2.2 MB，并在 clean / non-speech-noise 不退化的
前提下改善 speech-noise ASR。它是端侧资源和训练目标的最佳参考，但 Google 没有发布模型权重或可复现
训练仓库，所以不能进入本轮下载实测。

## 候选 Go / No-Go 矩阵

| 候选 | 是否解决目标任务 | 官方权重 / 许可 | 采样率、训练域 | 流式 / 导出 | 体积与算力线索 | 本轮决定 |
| --- | --- | --- | --- | --- | --- | --- |
| **WeSep BSRNN + ECAPA Vox1** | 是；混合波形 + enrollment → 目标波形 | 有；ModelScope 标记 Apache-2.0，生产前仍核对 VoxCeleb/LibriMix 派生条款 | 16 kHz；英语 VoxCeleb1 动态混合，LibriMix 验证 | 默认双向 LSTM，offline；官方 TorchScript + LibTorch runtime；未发现官方 ONNX | `avg_model.pt` 282.6 MB（含 optimizer），推理模型 27.63M 参数；实测 RTF 约 0.31、RSS 约 1.94 GB | **算法门 PASS、资源门 FAIL**；不直接进 Harmony |
| **ClearerVoice SpEx+** | 是；真正 reference-conditioned TSE | 有；HF 模型卡 Apache-2.0 | 8 kHz；英语 WSJ0-2mix-extr | 非因果；官方为 PyTorch 训练/评测代码；无官方 ONNX/runtime | best checkpoint 134.3 MB；RTF 未发布 | **GO P1：独立交叉验证**；**NO-GO：直接端侧** |
| **Asteroid Conv-TasNet Libri2Mix 16k + ERes2Net 选流** | 否；先盲分两路，再按 enrollment 选目标流 | 有；[官方模型卡](https://huggingface.co/JorisCos/ConvTasNet_Libri2Mix_sepclean_16k) 的 metadata 与历史正文分别写 CC BY-SA 4.0/3.0，生产前必须澄清 | 16 kHz；英语 Libri2Mix clean；checkpoint 内 sample-rate metadata 为 8 kHz，需澄清 | 非因果；本轮已导出固定 2 秒 ONNX | 20.15 MB ONNX、5.07M 参数；桌面 ORT 1.16.3 RTF 0.0583 / RSS 267 MB；C1～C3 PASS，但 L2 other-only 8/60 false rescue | **NO-GO：开放集门失败**；只保留诊断/teacher 价值 |
| **ClearerVoice MossFormer2 SS 16K + ERes2Net 选流** | 否；通用两人分离 | 有；[官方权重](https://huggingface.co/alibabasglab/MossFormer2_SS_16K) Apache-2.0 | 16 kHz；公开和私有大规模数据，多基准统一模型 | 非因果、24 层；官方 PyTorch，未见 ONNX | checkpoint 670.4 MB；远超当前端侧预算 | **HOLD**：只有轻量负对照明显欠拟合时再跑 |
| **SpeechBrain SepFormer** | 否；通用两人分离 | 有；[16 kHz WHAMR 模型](https://huggingface.co/speechbrain/sepformer-whamr16k) Apache-2.0 | 16 kHz 英语 noisy/reverb；另有 8 kHz Libri2Mix | offline PyTorch；无官方端侧导出 | mask network 约 113 MB，完整训练仓库 319 MB | **NO-GO**：与 MossFormer/Conv-TasNet 重复，先不增加实验枝杈 |
| **REAL-TSE BSRNN causal/offline baselines** | 是；且评测含普通话、英语真实会话 | 官方有，但只发已注册团队；当前不可公开取得 | 16 kHz；Libri2Mix-100 baseline，REAL-T 评测 | 同时有 causal/offline recipe | 官方公开页未给可下载体积/RTF | **NO-GO 当前下载**；**GO 训练设计参考** |
| **VoiceFilter-Lite** | 是；最贴近最终端侧产品 | 无公开权重/训练代码 | 论文训练为英语 ASR 域 | 真流式；论文验证 INT8 | 2.2 MB，实时 | **NO-GO 复用**；**GO 端侧目标架构** |
| **DiCoW v3 / SE-DiCoW** | TS-ASR，但依赖 diarization mask，不是现有外部 enrollment API 的直接替换 | [DiCoW v3 MLC](https://huggingface.co/BUT-FIT/DiCoW_v3_MLC) 有权重，CC BY 4.0；默认 DiariZen 链含非商用组件 | Whisper large-v3-turbo，约 0.9–1.0B；多语但官方表无中文结果 | offline/GPU 栈；无 Harmony 端侧路径 | 约 1B 参数，另需 diarizer | **NO-GO**：状态边界、大小和依赖都不匹配 |
| **NVIDIA Multitalker Parakeet streaming 0.6B** | 能处理重叠 ASR，但明确不使用 enrollment；每个 diarized speaker 启一个实例 | [官方权重](https://huggingface.co/nvidia/multitalker-parakeet-streaming-0.6b-v1)，NVIDIA Open Model License | 英语、多说话人 ASR | 真流式，但需 Streaming Sortformer 和 GPU/NeMo | 0.6B × speaker 数量 | **NO-GO**：不是目标人注册语义，端侧资源不成立 |
| **单独 diarization** | 否；只能标活动区间，不能恢复重叠目标波形 | 多种公开权重 | 取决于模型 | 可离线或在线 | 另加模型与状态机 | **NO-GO 主方案**；只保留为负对照/标注辅助 |

## 最高优先级可运行实验

### P0：WeSep BSRNN + ECAPA 16 kHz

要证伪的风险：公开英语 TSE 是否完全无法迁移到客户中文 C2/C3；以及它在主机上是否已慢到失去端侧
讨论价值。

官方最短调用路径：

```bash
git clone https://github.com/wenet-e2e/wesep.git
cd wesep
pip install -e .

wesep --task extraction --language english --device cpu \
  --audio_file /path/to/C2.wav \
  --audio_file2 /path/to/enrollment.wav \
  --output_file /path/to/C2.target.wav \
  --resample_rate 16000 --vad
```

注意：仓库代码直接 import WeSpeaker，但当前 `setup.py` 没有声明 `wespeaker`；干净环境若导入失败，按
[WeSpeaker 官方安装说明](https://github.com/wenet-e2e/wespeaker) 安装，不应改模型代码绕过 speaker encoder。
模型会从官方 ModelScope asset 自动下载。

实验固定输出：

- 输入/输出 SHA-256、采样率、时长、峰值幅度和是否削波；
- 模型 commit、checkpoint SHA-256、下载许可快照；
- wall time、CPU time、峰值 RSS、整段 RTF；
- 提取前后当前 ERes2Net 与三段 enrollment 的分数；
- 使用同一个 ZH_EN ASR 对 mixture 和 extracted waveform 解码，保留完整 final 文本；
- C1、C2、C3 分别报告，不允许用三条聚合 PASS 掩盖单条失败。

P0 进入下一步的最低门：

- C2、C3 的 extracted ASR 都包含目标关键词“上海”；
- extracted ASR 不包含已知非目标词“你好”；
- C1 不比当前 `1000/300 ms` Speaker VAD 的已通过结果退化；
- 输出长度与输入时间轴一致，不能靠裁掉整段重叠区“通过”；
- 主机 CPU RTF `< 1.0`，峰值 RSS `< 1 GiB`。这只是继续优化门，不是端侧门。

任一条业务断言失败时，先听检并比较目标声纹分数；若提取波形仍由目标人主导但 ASR 失败，归因到 8/16 kHz、
中文域或分离失真；若目标人没有成为主导流，归因到 TSE conditioning/domain。两者不得混称为 ASR 回归。

### P1：ClearerVoice SpEx+ 8 kHz

要证伪的风险：P0 的失败是 BSRNN/ECAPA 特定实现，还是公开英语 TSE 对客户中文域普遍失配。

官方仓库提供训练和 `evaluate_only.sh`，但没有单文件推理 CLI。复现时只做薄适配：加载官方
`config_wsj0-2mix_speech_SpEx-plus_2spk.yaml` 与 `last_best_checkpoint.pt`，调用现有 `network_wrapper`；不得
重写模型。混合和 enrollment 统一下采样到 8 kHz，输出再上采样 16 kHz 供现有 ASR，比对时必须把
“TSE 收益”和“8 kHz 带宽损失”分别记录。

停止条件：如果 P0 已在 C2/C3 达到业务最低门，P1 不再运行；如果 P0 未通过，P1 只跑 C2/C3 与一个
非重叠 target anchor。P1 也失败且两者均无法提高 extracted target embedding dominance 时，停止公开
英语 checkpoint A/B，进入中文/真实域 causal TSE 训练，不再盲换 separator。

### 短期候选：Conv-TasNet 16 kHz + ERes2Net permutation selection

官方调用：

```python
import torch
from asteroid.models import BaseModel

separator = BaseModel.from_pretrained(
    "JorisCos/ConvTasNet_Libri2Mix_sepclean_16k"
)
separator.eval()
with torch.no_grad():
    sources = separator(mixture_tensor)  # 形状按模型卡约定，输出两路波形
```

对每一路按与当前 SDK 完全相同的 enrollment 聚合和有效语音规则计算 ERes2Net 分数，选择分数更高的一路后
送入 ZH_EN ASR。不得用输出能量、流序号或事后文本选择目标流。

本轮结果：整段推理以及固定 2 秒、0.5 秒交叠的分块推理都让 C1/C2/C3 满足“含上海、无你好”。C3
分块时发生输出流换序，但每块 ERes2Net 选择跟随目标流，证明不能固定取流序号；分块 ASR 首字出现一字
退化，不能声称精度无损。固定 ONNX 为 `20,147,162 bytes`，桌面 ORT 1.16.3 4 线程中位 RTF
`0.0583`、进程最大 RSS `267 MB`。这只解除主机内容/图兼容门，ARM 真机资源、target-absent 和许可门
仍需独立验证。

## 从离线可行到端侧优化的顺序

1. **先证明内容可恢复。** 只跑 P0、必要时 P1 和一个轻量负对照；不要同时拉 SepFormer、MossFormer2、
   DiCoW 全矩阵。
2. **补齐受控真值。** 客户三条 WAV 只能做回归。下一数据必须包含 target/other 独立源、混合波形、对齐
   文本、enrollment、SNR/overlap 比例，并覆盖普通话、英文、同/异性、远近场、前置静音和 target-absent。
3. **冻结离线门。** 主指标为 target ASR CER/WER、非目标词泄漏、target-absent 抑制和 clean no-overlap
   退化；SI-SDRi、speaker similarity、DNSMOS 只能作诊断，不能单独判 PASS。REAL-TSE 获胜报告已指出
   similarity/DNSMOS 可被过优化。
4. **再选 causal 架构。** 若 P0 有正信号，复用 WeSep/REAL-TSE BSRNN recipe 训练中文真实域 causal 版；
   若需要更小端侧模型，以 VoiceFilter-Lite 的流式 masking、asymmetric loss、adaptive suppression 为目标，
   而不是量化当前 283 MB 双向 checkpoint 后直接交付。
5. **最后做导出和真机。** 先在 PyTorch 冻结 reference，再做 ONNX parity（整段/分块、短/长 enrollment、
   target absent、全重叠、无重叠）；只有 FP32 parity 和业务门都通过，才做 FP16/INT8、HAR 集成和 Harmony
   真机生命周期矩阵。

## 端侧生产门与停止条件

离线 prototype 进入 Harmony 之前，至少同时满足：

- 真因果或有明确有界 look-ahead；分块边界不改变目标选择，跨 chunk 不发生 speaker permutation；
- 16 kHz mono，支持动态 session 长度和 enrollment cache；
- ONNX Runtime 支持全部算子；同 PCM 的 PyTorch/ONNX 输出波形与下游 ASR 业务断言一致；
- 量化后模型建议 `< 30 MB`、目标设备持续 RTF `< 0.2`、峰值额外 RSS `< 150 MB`。这些是 pilot 预算，
  不是通过当前公开 checkpoint 推导出的承诺；
- clean/no-overlap ASR 不退化，target-absent 不产出伪目标语音，C1 的尾音控制仍由独立 endpoint 轨验收；
- 公共 `speakerSimilarity` 可选性、`isFinal/isLast/onComplete/cancel` 和 `onStart` 重入契约全部保持不变。

满足以下任一条件即停止当前候选，不继续靠参数搜索掩盖：

- 同一 checkpoint 在 C2/C3 都不能让目标 embedding dominance 或目标关键词出现；
- 只能通过事后查看文本选择输出流，或分块后 permutation 不稳定；
- clean/no-overlap 目标语音明显失真，导致 ASR 相对原始输入持续退化；
- 模型无法在 1 小时内完成官方权重加载与一次 C2 推理，或主机 CPU RTF `>= 1.0` / RSS `>= 1 GiB`；
- 没有可确认的模型/训练数据商用许可链；
- 官方图无法导出到端侧 runtime，且需要引入完整 LibTorch/Whisper/NeMo 才能运行。

## 2026-08-04 实验回填

P0 WeSep 已按同一 C1～C3 严格门完成主机实验：三条提取后文本都包含“上海”且不包含“你好”；C2
分别使用 far/mid/near 三段 enrollment，三次结果一致。目标声纹 whole 分数为 C1 `0.690`、C2
`0.638～0.641`、C3 `0.568`。分离 RTF `0.302～0.322`，但进程最大 RSS 约 `1.94 GB`，因此算法可行性
成立，公开 checkpoint 的端侧资源门失败。

另以 SpeechBrain RE-SepFormer 做通用两人分离正对照，再用当前 ERes2Net 选目标流。C1/C2/C3 同样逐条
通过；固定 4 秒模型已成功导出 83.6 MB ONNX，与 PyTorch 输出 cosine `1.0`，主机中位 RTF `0.0276`、
RSS 约 430 MB。它不带 enrollment identity、非因果且资源仍超预算，只证明内容可恢复与 ONNX 图可行，
不改变 TSE 主路线。完整逐例文本、分数、哈希和停止理由见
[重叠前端离线实验](VOICEPRINT_OVERLAP_FRONTEND_EXPERIMENT_20260804.md)。

## 推荐的立即动作

短期不训练时停止 C2/C3 盲分离前端，把原始 ASR/fallback 保留为公开结果；C1 继续独立验证
`1000/300 ms` Speaker VAD。Conv-TasNet、RE-SepFormer 和 WeSep 只保留为内容可恢复/teacher 证据，
不再做真机资源或生命周期扩展。后续若投入训练，使用带独立源中文数据和 enrollment conditioning，目标
为 `<30 MB`、额外 RSS `<150 MB`、有界 look-ahead 的 causal TSE。
