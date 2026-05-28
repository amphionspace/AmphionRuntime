# 目标说话人识别与流式模型挑战

## User

我在端侧上使用sherpa-onnx部署的zipformer+transducer流式asr模型。我现在接受一个需求，只识别目标说话人的音频内容（对方可以先注册一段音频）
我认为流式不好做，所以妥协为另一个方案：每次vad或者endpoint后，拿整段音频去做目标说话人语音识别。
但这会引申出另一个问题，onnx模型都是形状固定的，没办法用流式模型去做非流推理，除非内存里再放一个模型。
关于目标说话人识别，我的初步想法使用cam++这样的speaker encoder通过相似度拿取出目标说话人的音频然后做推理
我要求你详尽调研，重点是有无真实实践作为反馈

## Assistant

这是一个端侧目标说话人 ASR 的工程问题，我会按第一性原理工作流，先做详尽调研，重点找真实实践反馈再下结论。先开多路并行调研：

### Tool Todo Write

### Tool Web Search

```
{"searchTerm":"sherpa-onnx zipformer streaming model non-streaming offline inference difference","toolCallId":"toolu_bdrk_019p5krpPHDTvAL3AokYJoyn"}
```

### Tool Web Search

```
{"searchTerm":"sherpa-onnx CAM++ speaker embedding target speaker 识别 实践","toolCallId":"toolu_bdrk_01VfhXw5uvthreHFZmSSKAGH"}
```

### Tool Web Search

```
{"searchTerm":"target speaker ASR TS-ASR end-to-end on-device deployment open source","toolCallId":"toolu_bdrk_01HRrCfuPwS5bdWaRR91Aomo"}
```

### Tool Web Search

```
{"searchTerm":"VoiceFilter SpEx+ target speaker extraction on-device mobile real-time deployment","toolCallId":"toolu_bdrk_01NgXKNVoCo7JACsoDpYWVgS"}
```

## Assistant

继续深入几个关键问题：流式 zipformer 直接喂整段音频的可行性、级联方案的真实精度反馈、TS-VAD 等替代路径。

### Tool Web Search

```
{"searchTerm":"sherpa-onnx speaker diarization pyannote 3d-speaker 流式 ASR 整合 实践","toolCallId":"toolu_bdrk_01AebW6k7vdZpZ3f3qPWzVeV"}
```

### Tool Web Search

```
{"searchTerm":"streaming zipformer same model offline decoding accuracy degradation","toolCallId":"toolu_bdrk_01Y3rzj3YpvR4eTiLAadNj9K"}
```

### Tool Web Search

```
{"searchTerm":"CAM++ onnx 端侧 实时 移动端 性能 ms 推理","toolCallId":"toolu_bdrk_01WBaoyq44Jukp3WE9x5E8bD"}
```

### Tool Web Search

```
{"searchTerm":"TS-VAD target speaker voice activity detection edge device deployment","toolCallId":"toolu_bdrk_012gYCH2uSXGvv4j5qQACUdD"}
```

### Tool Web Search

```
{"searchTerm":"sherpa-onnx streaming zipformer feed entire audio one shot batch decode","toolCallId":"toolu_bdrk_017qdSBDf1p8gGTezyYRHkV3"}
```

### Tool Web Search

```
{"searchTerm":"3D-Speaker CAM++ EER 中文 cnceleb 声纹 实际部署 阈值 短音频","toolCallId":"toolu_bdrk_01MGmxxepR6K7k2cWYkpFHmT"}
```

### Tool Web Search

```
{"searchTerm":"target speaker recognition VAD chunk speaker verification ASR pipeline failure cases overlap","toolCallId":"toolu_bdrk_018Hib8vTWACnbYRYKnPKbdv"}
```

### Tool Web Search

```
{"searchTerm":"sherpa-onnx 目标说话人 识别 项目 github 实践 注册 验证 ASR","toolCallId":"toolu_bdrk_01K1nrty2xGehZpESJzkJHkH"}
```

### Tool Web Search

```
{"searchTerm":"speaker verification short utterance 1 second 2 second EER degradation real world","toolCallId":"toolu_bdrk_01RCoxr6U4Efvao6NMzDvEaS"}
```

### Tool Web Search

```
{"searchTerm":"VoiceFilter-Lite open source onnx implementation pretrained model Pixel feature","toolCallId":"toolu_bdrk_016quiJy9M3KfFdTRxBRru2z"}
```

### Tool Web Search

```
{"searchTerm":"sherpa-onnx 流式 ASR 同时 说话人 验证 demo 麦克风 集成","toolCallId":"toolu_bdrk_01M1XnqL7SXYJPRZMBcDebkk"}
```

### Tool Web Search

```
{"searchTerm":"personal VAD personalized speech recognition wake word target speaker enrolled real implementation","toolCallId":"toolu_bdrk_01PqWu989p97P5ShtkCP3GpZ"}
```

## Assistant

读一下 sherpa-onnx 的 c-api 与 README 关键段，验证流式模型整段处理的实际机制：

### Tool Ripgrep Raw Search

```
{"pattern":"streaming|chunk|right.context|left.context|num_left_chunks|chunk_size|encoder.*states|cached","path":"/Users/boxp/.cursor/projects/empty-window/agent-tools/5f12397e-3537-418e-b4fb-b68dc6ff3cd1.txt","outputMode":"content","caseInsensitive":true,"headLimit":40,"multiline":false,"toolCallId":"toolu_bdrk_01XX7yYR3Ltg3zNP4EZgNDH6","offset":0}
```

### Tool Ripgrep Raw Search

```
{"pattern":"VAD\\+ASR|Speaker.*ID|speaker_identification|speaker.*verification|speaker_embedding","path":"/Users/boxp/.cursor/projects/empty-window/agent-tools/307ba8d1-d443-449e-921e-5b531859502d.txt","outputMode":"content","caseInsensitive":true,"headLimit":40,"multiline":false,"toolCallId":"toolu_bdrk_01PQAv4TJp4cmDNVdvUXvMHz","offset":0}
```

### Tool Web Search

```
{"searchTerm":"sherpa-onnx speaker identification microphone realtime VAD Chinese 实时 麦克风 issue","toolCallId":"toolu_bdrk_011oUmbZ7AdTsaWqmpzFNZ2U"}
```

### Tool Todo Write

## Assistant

以下是按第一性原理工作流给出的调研结论。

---

## 1. 问题复述

你真正要解决的问题：在端侧（已部署 sherpa-onnx 流式 zipformer-transducer 的设备）上，让 ASR **只输出"已注册目标说话人"的文字**，而忽略其他说话人。

但你提出的两个表面陈述里，至少有一个是被工程包袱误导的，需要先纠偏：

| 你的陈述 | 实际情况 |
|---|---|
| "流式不好做，妥协为 VAD/endpoint 后整段做 TS-ASR" | 妥协方向合理，但理由（"流式做不了"）只有部分正确——可见下文假设 A1 |
| "onnx 模型形状固定，没办法用流式模型做非流推理，除非内存里再放一个模型" | 假设错误。流式 zipformer 的 onnx 形状本来就是 chunk-level，整段推理只是循环喂 chunk + 内部 cache 状态。无需双模型，但精度上限就是流式模型上限——见假设 A1 |

---

## 2. 关键假设（含风险）

| # | 假设 | 风险 | 证据 |
|---|---|---|---|
| A1 | "流式 onnx 形状固定 → 不能做整段非流式推理" | 高风险错误假设 | sherpa-onnx C++/Python 示例都直接对流式模型做 `AcceptWaveform(整段)` + `InputFinished()` + `while IsReady: Decode`，本质是把整段切成 chunk 顺序喂入并维持 left/right context 状态。形状（input shape）固定的是 chunk，不是整段 |
| A2 | "VAD 切片后片段总是足够长，能稳定提取 speaker embedding" | 高风险 | 短音频 EER 暴增是普遍规律：VoxCeleb1 baseline 3s 6.64% / 2s 8.93% / 1s 20.41%，CAM++ 在 CN-Celeb 全长 EER 6.78%，但片段越短退化越严重；阿里官方建议输入 3-10s |
| A3 | "VAD/endpoint 切到的每段只有一个说话人" | 中-高风险 | 双方对话/电话/会议中重叠语音占比可达 10-20%，一旦切片包含 overlap，speaker embedding 会被污染，CAM++ 这类纯 embedding 方案对 overlap 是无能为力的（这是 VoiceFilter / TS-VAD 类方法存在的根本理由） |
| A4 | "目标说话人和注册时声学条件一致" | 中风险 | 跨设备/距离/方言场景下 CAM++ EER 从 6.78% 升到 11-13%；端侧麦克风、远场拾音、信道差异都会触发这个退化 |
| A5 | "纯 embedding 余弦相似度 + 阈值就够用" | 中风险 | 阈值（CAM++ 默认 0.31，金融场景建议 0.5-0.7）需要按你的实际场景标定，否则 FAR/FRR 不可控；Modelscope / 3D-Speaker 自己也说"测试已知样本分布来校准最佳阈值" |

---

## 3. 推导链

### 第 1 步：纠正 onnx 形状的误解

流式 zipformer 的 onnx 接口定义：encoder 输入是固定 chunk_size（如 32 帧 ≈ 0.32s，外加 left context cache）+ 一组 cache 张量；输出是新的 cache。这是 **chunk-级别的固定形状**，不是整段级别。

所以"用流式模型推全段音频"在实现上等同于"循环把全段切成连续 chunk 投喂同一个模型 + 一直保留 cache"——sherpa-onnx 的 `OnlineRecognizer` 本来就是这个工作方式。**不需要再装第二个模型**。

但精度上限就锁死在流式模型的上限：根据 ACL 2025 industry track 论文（arxiv 2506.14434），流式和非流式 zipformer 在同等数据上仍有固有的 WER gap，靠"训练时加 dynamic right-context"才能逐步逼近，不靠这个 trick 的纯流式模型整段推理 WER 不会变成离线水平。

**结论**：你已经有的流式 sherpa-onnx 模型可以直接处理 VAD 切出的整段音频，无需追加非流式模型。**但如果业务上能接受多 100MB+ 内存，并行加一个非流式 zipformer 仍是值得评估的精度选项**。

### 第 2 步：把"目标说话人 ASR"拆成原子组件

任何一种 TS-ASR 都必然由以下功能子集构成：

- F1：判断"这一段/这一帧"是不是目标说话人（speaker gating）
- F2：把目标说话人的音频/特征送进 ASR
- F3：抑制非目标说话人对 ASR 的输出污染（尤其在重叠区域）

不同方案在 F1/F2/F3 的实现位置不同：

| 方案家族 | F1 位置 | F2 粒度 | F3 能力 |
|---|---|---|---|
| 方案 A：你的初步方案（VAD 切段 + Speaker Verification + ASR） | 切段后整段二分类 | 整段全送/全弃 | 重叠区域无能为力 |
| 方案 B：Personal VAD（Google PVAD 1.0/2.0） | 帧级三分类 ns/tss/ntss | 帧级 gating | 重叠区域有限识别 |
| 方案 C：VoiceFilter-Lite（Google 上线 Pixel） | 帧级 mask 滤波器 | 直接修改 ASR 输入特征 | 在 fbank 域抑制非目标 |
| 方案 D：端到端 TS-ASR（TS-RNNT / CONF-TSASR） | 编码器中 FiLM 注入说话人 | ASR 模型本身只看目标 | 内置（end-to-end 训练） |
| 方案 E：Diarization 后整理 | 完整 diarization | 按说话人聚簇 | 取决于 diarization 是否支持 overlap |

### 第 3 步：按真实可落地性筛选

| 方案 | 端侧可落地的开源工件 | 真实生产案例 | 你能直接用 sherpa-onnx 实现吗 |
|---|---|---|---|
| A：VAD + SV + ASR | sherpa-onnx 内置 SpeakerEmbeddingExtractor、SpeakerEmbeddingManager、CAM++ / 3D-Speaker eres2net onnx 模型直接发布 | 大量"声纹识别 + ASR"的 demo 项目（modelscope、CSDN、阿里云开发者社区都有） | 完全可以，零开发新算子 |
| B：Personal VAD | 仅有论文级实现，开源代码不齐 | Google 内部使用 | 不能直接用，需自训 |
| C：VoiceFilter-Lite | Google 仅发了 TFLite 模型未开源权重；maum-ai 有 PyTorch 非官方实现，但是是老版 VoiceFilter（不是 Lite） | Google Pixel 已上线 | 不能直接用，需自训 + 自转 onnx |
| D：TS-RNNT / CONF-TSASR | NeMo 仓库有 conformer 时频域版（CONF-TSASR）；TS-RNNT 仅论文 | NVIDIA Riva 服务器侧；端侧落地证据极少 | 不能直接用 sherpa-onnx，需要重训 + 重新走 onnx 导出链 |
| E：完整 Diarization | sherpa-onnx 已支持 OfflineSpeakerDiarization（pyannote-segmentation-3.0 + 3D-Speaker/NeMo embedding + 聚类） | 多个端侧 demo（Sophon/M5Stack 等） | 完全可以；但是离线模型，且 RTF 较高（3D-Speaker int8 RTF≈0.24） |

**真实生产已验证的端侧 TS-ASR 路径只有 C（Google Pixel VoiceFilter-Lite），其它 D 类端到端方案在端侧没有公开上线证据。** 但 C 没有现成可下载的预训练权重。

### 第 4 步：你的方案 A 的真实风险点（用调研到的数字定量）

| 风险 | 数字证据 |
|---|---|
| 短切片 EER 退化 | VoxCeleb1 baseline：3s 6.64% → 2s 8.93% → 1s 20.41%（3 倍）；ResNet：2s 7.97% → 6s 3.39%（2 倍多） |
| 短切片需要的最低长度 | 学术界共识阈值 ≈ 2s；阿里 CAM++ 官方建议 3-10s |
| 重叠语音命中率 | 切片包含两人时整段 embedding 会向"两人混合中心点"漂移，余弦相似度对真实目标的 score 显著下降，FAR/FRR 同步恶化（VoiceFilter / TS-VAD 类工作的核心 motivation） |
| 跨域退化 | CAM++ 跨设备/距离/方言：6.78% → 11-13%（差不多翻倍） |
| 单次延迟 | CAM++ 一段 < 2s 输入，BM1684X ~58ms，主流移动端 CPU FP32 大概 50-200ms（按特征长度线性变化），叠加在 ASR 延迟之上 |

### 第 5 步：失败域定位

把方案 A 的失败模式按"什么时候会出错"归类：

1. 切片太短（< 2s）→ embedding 不稳定 → 阈值越界 → 误判（漏识别 / 误识别）
2. 切片含重叠（overlap）→ embedding 被污染 → 同上
3. 跨域（远场、方言、信道）→ 注册音频和实时音频分布不一致 → 阈值漂移
4. 注册音频本身偏短或不干净 → 整个系统退化

这些都是工程上**可观测、可缓解但不可消除**的问题。

---

## 4. 推荐方案 + 主要 trade-off

### 4.1 推荐分阶段策略（务实路径）

**阶段 1（MVP，1-2 周可上线）**：方案 A 的工程化加固版

```
[mic stream]
  → silero-vad (frame-level)                           # 已内置
  → endpoint 切段
  → CAM++ / 3D-Speaker eres2net 提 embedding           # sherpa-onnx 已内置
  → 与注册 embedding 余弦相似度 (≥3 段平均，多注册增强)
  → 决策（接受 / 拒绝 / 边界态丢给 ASR 但低置信度返回）
  → sherpa-onnx 流式 zipformer 直接 AcceptWaveform 整段
```

关键加固点（解决推导链第 4 步的 5 类风险）：

1. **多模板注册**：注册不少于 3 段、每段 5-10s、不同语速/距离的音频，取均值或 multi-prototype，**直接抵消"短音频不稳"和"跨域退化"**
2. **片段最短长度门限**：< 1.5s 的切片不进入说话人判别，要么直接丢弃，要么累积到下一段（这个数字按 EER 表来定）
3. **滑窗内多次打分**：长片段不要只做一次 embedding；按 2-3s 窗口 + 0.5-1s 步长打多个分，取**多数票或最高分**，对 overlap 场景有缓解（但不能根治）
4. **双阈值**：高阈值（如 0.5-0.6）直接接受，低阈值（如 0.2-0.25）直接拒绝，中间区域可走"先识别再标注低置信"或"丢弃"。**先用真实数据采 100-300 对样本标定 ROC，不要直接用默认 0.31**
5. **流式 zipformer 做整段推理（无需再加非流式模型）**：用 sherpa-onnx 现成的 `AcceptWaveform(整段) + InputFinished + Decode` 流程；如果发现精度差距明显再考虑加非流式模型

主要 trade-off：

| 维度 | 表现 |
|---|---|
| 延迟 | endpoint 后才出文字，会比纯流式增加 endpoint silence + 整段 ASR 推理时长 |
| 一致性 | 整段决策粒度，重叠片段会整段被当做"目标"或"非目标"，无法分词标注 |
| 失败域 | overlap 段、短切片、跨域 → 见上文风险表 |
| 状态边界 | 注册 embedding 是全局状态，VAD 切片是流式状态，两者解耦干净 |
| 演进成本 | 低；后续阶段 2/3 的更换不需要重训 ASR |

**阶段 2（如果 MVP 暴露 overlap / 短切片问题严重）**：升级 F1 到帧级

候选 a：自训一个轻量 Personal VAD（130K 参数，可以塞进端侧），把"目标说话人"的判别从段级降到帧级，把 overlap 段的"非目标帧"剥离掉再喂 ASR。

候选 b：把 sherpa-onnx 的 OfflineSpeakerDiarization（pyannote-segmentation 3.0 + 3D-Speaker + 聚类）当作一种"段级 + overlap aware"的 F1，再做"哪个簇是目标"的余弦匹配。代价是离线、RTF≈0.24（3D-Speaker int8）-0.11（NeMo TitaNet int8）。

**阶段 3（如果 MVP+2 仍不够，且业务可投入算法资源）**：考虑前端 TSE

VoiceFilter-Lite 思路自训：speaker embedding + ASR 同特征域的 mask 网络，前端过滤 fbank。**端侧已有真实生产案例（Google Pixel）**。代价：需要数据、训练能力，且需要让 mask 网络的输入 fbank 与 sherpa-onnx zipformer 的特征对齐（log Mel-fbank 80-dim，比较容易对齐）。

### 4.2 另一种值得评估的端到端候选（如果团队有训练能力）

NVIDIA NeMo 的 CONF-TSASR 已开源，是 conformer + speaker embedding + mask + ASR 的端到端模型，但端侧落地几乎没有公开案例，工作量主要在 onnx 导出和量化。**如果你已经在 sherpa-onnx 体系里，方案 A + 阶段 2 的渐进路径性价比明显更高。**

---

## 5. 代码（落地骨架）

下面给出阶段 1 的最小骨架，所有组件都是 sherpa-onnx 现成 API，端侧无需新模型。注释只标"为什么"，不标"做什么"。

```python
import numpy as np
import sherpa_onnx

ENROLL_THRESH_HIGH = 0.55
ENROLL_THRESH_LOW = 0.25
MIN_SEG_SEC = 1.5

def build_recognizer():
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens="tokens.txt",
        encoder="encoder.onnx",
        decoder="decoder.onnx",
        joiner="joiner.onnx",
        num_threads=2,
        provider="cpu",
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        enable_endpoint_detection=True,
    )

def build_speaker():
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model="3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
        num_threads=1,
        provider="cpu",
    )
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return extractor

def enroll(extractor, wavs):
    embs = []
    for samples, sr in wavs:
        s = extractor.create_stream()
        s.accept_waveform(sample_rate=sr, waveform=samples)
        s.input_finished()
        embs.append(np.asarray(extractor.compute(s)))
    e = np.mean(embs, axis=0)
    return e / (np.linalg.norm(e) + 1e-9)

def segment_score(extractor, target_emb, samples, sr,
                  win_sec=2.5, hop_sec=1.0):
    n_win = int(win_sec * sr)
    n_hop = int(hop_sec * sr)
    if len(samples) < int(MIN_SEG_SEC * sr):
        return None
    scores = []
    for st in range(0, max(1, len(samples) - n_win + 1), n_hop):
        seg = samples[st:st + n_win]
        s = extractor.create_stream()
        s.accept_waveform(sample_rate=sr, waveform=seg)
        s.input_finished()
        emb = np.asarray(extractor.compute(s))
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        scores.append(float(np.dot(emb, target_emb)))
    if not scores:
        s = extractor.create_stream()
        s.accept_waveform(sample_rate=sr, waveform=samples)
        s.input_finished()
        emb = np.asarray(extractor.compute(s))
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        return float(np.dot(emb, target_emb))
    return max(scores)

def asr_decode_full_segment(recognizer, samples, sr):
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate=sr, waveform=samples)
    tail = np.zeros(int(sr * 0.5), dtype=np.float32)
    stream.accept_waveform(sample_rate=sr, waveform=tail)
    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    return recognizer.get_result(stream).text
```

要点说明：

1. `asr_decode_full_segment` 用的是已有的流式 recognizer，对应推导链第 1 步的核心结论：流式 onnx 模型直接吃整段音频，**不需要再加一个非流式模型**
2. `segment_score` 用滑窗多次打分取最大值，缓解 overlap 段把整段 embedding 拉偏的问题
3. 阈值是双值（`HIGH/LOW`），中间区域如何处理留作业务决策（默认建议丢弃）
4. `enroll` 强制平均多段，并对 embedding 做单位化，对应阶段 1 加固点 1
5. 阈值数字要在你自己的设备 + 注册数据上做 ROC 标定，不要直接信默认值

---

## 已知未知（你接下来应该测）

1. 你的 zipformer 模型是不是用了"动态 right-context"训练？如果是，整段推理时调大 right-context frames 数能逼近非流式精度（ACL 2025 那篇的关键 trick）；如果不是，整段推理 WER 就锁定在流式上限
2. 真实业务里 VAD 切片的长度分布（中位数、< 2s 比例）——决定方案 A 短片段问题的严重性
3. 真实业务里重叠语音的占比和典型形态（连续重叠 / 交叠瞬时 / 远端扬声器漏音）——决定是否需要进入阶段 2
4. CAM++ 与 eres2net 在你设备上的 RTF 与最大可接受片段长度——决定滑窗策略的开销
5. 注册环境与使用环境的声学差距——决定多模板注册的必要性

---

## 关键引用

- sherpa-onnx 流式 zipformer 整段输入示例（`AcceptWaveform + InputFinished + while IsReady: Decode`）：[`cxx-api-examples/streaming-zipformer-cxx-api.cc`](https://github.com/k2-fsa/sherpa-onnx/blob/master/cxx-api-examples/streaming-zipformer-cxx-api.cc)
- sherpa-onnx Speaker ID Python 例子：[`python-api-examples/speaker-identification.py`](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/speaker-identification.py)
- sherpa-onnx Speaker Diarization：[`python-api-examples/offline-speaker-diarization.py`](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-speaker-diarization.py)
- sherpa-onnx 已发布 wespeaker_en_voxceleb_CAM++.onnx / 3D-Speaker eres2net 等：[releases/speaker-recongition-models](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)
- 流式/非流式 zipformer 精度差异：[Unifying Streaming and Non-streaming Zipformer-based ASR (ACL 2025 / arxiv 2506.14434)](https://arxiv.org/html/2506.14434v1)
- Google VoiceFilter-Lite 端侧实践：[Google Research Blog](https://research.google/blog/improving-on-device-speech-recognition-with-voicefilter-lite/)
- TS-RNNT 流式端到端 TS-ASR：[arxiv 2209.04175](https://arxiv.org/pdf/2209.04175)
- CONF-TSASR 端到端 TS-ASR：[arxiv 2308.05218](https://arxiv.org/pdf/2308.05218)
- Personal VAD / PVAD 2.0：[arxiv 1908.04284](https://arxiv.org/abs/1908.04284) / [arxiv 2204.03793](https://arxiv.org/abs/2204.03793)
- 短音频说话人验证 EER 退化基准：[arxiv 2005.03329](https://arxiv.org/pdf/2005.03329)、[VoxCeleb 论文 Table 3](https://www.robots.ox.ac.uk/~vgg/publications/2019/Xie19a/xie19a.pdf)
- CAM++ 中文 EER 与部署：[CSDN 模型对比](https://blog.csdn.net/gitblog_00785/article/details/152545393)、[Sophon 端侧 CAM++ 实测](https://github.com/sophgo/sophon-demo/blob/release/sample/CAM++/README.md)
- sherpa-onnx Diarization 速度反馈：[Discussion #3233](https://github.com/k2-fsa/sherpa-onnx/discussions/3233)

---

## TL;DR

1. 你的方案方向对，但理由错。**流式 zipformer 模型可以直接用于整段推理（用 sherpa-onnx 现成 API），不需要在内存里再放一个非流式模型**。代价只是精度上限锁定在流式模型上限
2. 端侧 TS-ASR **真实生产案例只有 Google VoiceFilter-Lite（Pixel）**，但其没有官方开源权重；端到端 TS-ASR（TS-RNNT / CONF-TSASR）端侧无公开落地
3. **你的"VAD 切段 + CAM++ 验证 + 整段流式 ASR"是当前唯一能用 sherpa-onnx 现成组件零自训实现的可落地方案**，sherpa-onnx 的 SpeakerEmbeddingExtractor / Manager / CAM++ / 3D-Speaker 模型都已发布
4. 这个方案的三大失败域是：短片段（< 2s EER 暴增 2-3 倍）、重叠语音（embedding 污染）、跨域（EER 翻倍）。用多模板注册 + 滑窗打分 + 双阈值 + 最短切片门限可以把这三个域都缓解（不能根治）
5. 后续如果数据反馈不够好，按 PVAD（帧级目标说话人 VAD）或 VoiceFilter-Lite（fbank 级 mask 前端）演进，且都不需要换 ASR 模型

## User

CONF-TSASR开源了吗，模型哪里能下

## Assistant

直接查 NeMo 仓库和模型库的现状。

### Tool Web Search

```
{"searchTerm":"NeMo CONF-TSASR open source code github target speaker ASR conformer","toolCallId":"toolu_bdrk_01Lqz8sW15nExGyWh2tgiVU5"}
```

### Tool Web Search

```
{"searchTerm":"\"ts_asr\" OR \"conf_tsasr\" OR \"target_speaker_asr\" NVIDIA NeMo recipe config","toolCallId":"toolu_bdrk_01WXK51Ue1Lya5cMEpNLhRTb"}
```

### Tool Web Search

```
{"searchTerm":"NeMo target speaker ASR pretrained model nvidia ngc huggingface checkpoint","toolCallId":"toolu_bdrk_01NwH7ysjKmADfHwDxHrPPWr"}
```

### Tool Web Search

```
{"searchTerm":"NeMo Sortformer TS-ASR target speaker conformer cache aware streaming 2025","toolCallId":"toolu_bdrk_01CTaGPxWNaHsXWovrDVvWLu"}
```

## Assistant

补一下相关项目的开源情况，给你一个完整的可对比清单。

### Tool Web Search

```
{"searchTerm":"BUTSpeechFIT TS-ASR-Whisper github pretrained checkpoint download","toolCallId":"toolu_bdrk_01MgBFKDPAHS6j7TV955BFr4"}
```

### Tool Web Search

```
{"searchTerm":"\"CONF-TSASR\" NeMo checkpoint release github commit pretrained model 2024","toolCallId":"toolu_bdrk_01EFQXVqExzPQvKsZmCCEnBM"}
```

## Assistant

直接回答：**没有找到 CONF-TSASR 的公开预训练权重**，论文承诺的开源到现在也没兑现。我上一条回答里说"NeMo 仓库有 conformer 时频域版（CONF-TSASR）"是表述不准——纠正一下，下面给证据和真正能下到的替代品。

## 1. CONF-TSASR 的实际开源状态

| 来源 | 实际查到的状态 |
|---|---|
| 论文 arxiv 2308.05218（2023-08） | 原文说 "Model will be open-sourced through NVIDIA NeMo toolkit"，链接指向 https://github.com/NVIDIA/NeMo |
| NeMo 仓库 ASR 模型列表 | 列出 Jasper / QuartzNet / Citrinet / ContextNet / Conformer-CTC / Conformer-Transducer / FastConformer-CTC/Transducer / Squeezeformer / LSTM-Transducer / LSTM-CTC，无 CONF-TSASR、无 TS-ASR 入口 |
| NeMo `examples/asr/conf` 目录 | 没有 ts_asr / target_speaker / conf_tsasr 相关 yaml |
| HuggingFace `nvidia/*` 命名空间 | 没有 CONF-TSASR 模型卡 |
| NGC NeMo ASR catalog | 没有 CONF-TSASR checkpoint |

结论：论文是 NVIDIA 内部研究，但**预训练权重和代码至今未公开**。这种"承诺 NeMo 开源但没落地"的工作不算个例（NVIDIA 内部研究代码常年滞后于论文）。

## 2. NVIDIA 现在的 TS-ASR 路线已经换代

CONF-TSASR 不出来的根本原因可能是：NVIDIA 2025 年改了路线，新的端到端多说话人 ASR 是 **基于 diarization 输出而非 enrollment**：

| 模型 | HuggingFace | 大小 | 路线 |
|---|---|---|---|
| Multitalker Parakeet Streaming | [`nvidia/multitalker-parakeet-streaming-0.6b-v1`](https://huggingface.co/nvidia/multitalker-parakeet-streaming-0.6b-v1) | 0.6B | Cache-aware FastConformer + speaker kernel injection，每个 speaker 一个 instance |
| Streaming Sortformer Diarizer | [`nvidia/diar_streaming_sortformer_4spk-v2`](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2) | 配套 diarizer | Arrival-Order Speaker Cache，端到端 diarization |

**关键差异**：这套新方案**不需要也不支持注册音频**——它的"目标说话人"是 diarization 自动分簇出来的"speaker 0/1/2"，而不是你预先注册的某个具体人。所以它不能直接满足你"先注册一段音频，只识别这个人"的需求，需要再加一层：用 speaker embedding 把 diarization 出的某个簇匹配到你的注册音频。

## 3. 当前真正可下载、可走 enrollment 路线的 TS-ASR

按"可下载且接近你需求"排：

| 项目 | 路线 | 预训练权重 | 端侧友好度 |
|---|---|---|---|
| BUT-FIT DiCoW 系列 | Whisper large-v3-turbo + diarization conditioning（FDDT 层） | `BUT-FIT/DiCoW_v2`、`BUT-FIT/DiCoW_v3_3`、`BUT-FIT/SE-DiCoW` 在 HuggingFace 有 | 差。Whisper large-v3-turbo 是 800M+ 参数，端侧不现实，但数据质量是公开 TS-ASR 里最好的 |
| TS-ASR-Whisper 训练代码 | 上面这套的训练 / 微调框架 | [BUTSpeechFIT/TS-ASR-Whisper](https://github.com/BUTSpeechFIT/TS-ASR-Whisper)，CTC Whisper large-v3-turbo encoder 单独提供 | 同上 |
| TS-RNNT (NTT, 2022) | RNNT encoder 中注入 speaker embedding | 论文级，无公开权重 | 端侧友好但没人做出来 |
| VoiceFilter-Lite (Google) | speaker-conditioned fbank mask 前端 | 论文级，TFLite 内部模型未公开 | 端侧最友好（2.2MB），但你下不到 |
| maum-ai/voicefilter | 旧版 VoiceFilter (不是 Lite) | [GitHub](https://github.com/maum-ai/voicefilter) PyTorch 实现 | 中。是研究级实现，需要自己 onnx 化 |

## 4. 对你的项目的实际意义

我上次给你的主结论不变，但要把第 4.2 节关于 CONF-TSASR 的措辞做两处修正：

1. **不要把 CONF-TSASR 当作"开箱即用的端到端候选"**——它没有公开权重，团队需要从 NeMo 配置自己复现，工作量等同于自训
2. 如果团队真要走端到端 TS-ASR 路线，**当前唯一有公开权重的选项是 BUT-FIT DiCoW 系列**（Whisper-based），但模型大到端侧基本跑不动；如果要做端侧，就只能基于其训练代码 + 自有数据从一个小 backbone（FastConformer 或 zipformer）重训

所以对你这个具体的"sherpa-onnx zipformer 端侧 + 注册说话人 ASR"的项目，**结论收敛回上次的方案 A（VAD + CAM++/3D-Speaker + 整段流式 ASR）+ 阶段 2 演进**。**端到端 TS-ASR 在端侧 + 现成开源权重 + 支持 enrollment 的交集是空集**。

## 修正与致歉

上一条回答里"NeMo 仓库有 conformer 时频域版（CONF-TSASR）"这个判断不严谨，实际是**论文承诺开源但截至现在未公开权重和完整训练代码**。这是我没在第一遍调研里直接核到 NeMo 仓库的疏漏。多谢你追问，否则这条会埋下坑。