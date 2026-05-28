调研-端侧目标说话人识别
1. 问题复述
你真正要解决的问题：在端侧（已部署 sherpa-onnx 流式 zipformer-transducer 的设备）上，让 ASR 只输出"已注册目标说话人"的文字，而忽略其他说话人。
但你提出的两个表面陈述里，至少有一个是被工程包袱误导的，需要先纠偏：
暂时无法在飞书文档外展示此内容

---
2. 关键假设（含风险）
暂时无法在飞书文档外展示此内容

---
3. 推导链
第 1 步：纠正 onnx 形状的误解
- 流式 zipformer 的 onnx 接口定义：encoder 输入是固定 chunk_size（如 32 帧 ≈ 0.32s，外加 left context cache）+ 一组 cache 张量；输出是新的 cache。这是 chunk-级别的固定形状，不是整段级别。
- 所以"用流式模型推全段音频"在实现上等同于"循环把全段切成连续 chunk 投喂同一个模型 + 一直保留 cache"——sherpa-onnx 的 OnlineRecognizer 本来就是这个工作方式。不需要再装第二个模型。
- 但精度上限就锁死在流式模型的上限：根据 ACL 2025 industry track 论文（arxiv 2506.14434），流式和非流式 zipformer 在同等数据上仍有固有的 WER gap，靠"训练时加 dynamic right-context"才能逐步逼近，不靠这个 trick 的纯流式模型整段推理 WER 不会变成离线水平。
- 结论：你已经有的流式 sherpa-onnx 模型可以直接处理 VAD 切出的整段音频，无需追加非流式模型。但如果业务上能接受多 100MB+ 内存，并行加一个非流式 zipformer 仍是值得评估的精度选项。
第 2 步：把"目标说话人 ASR"拆成原子组件
任何一种 TS-ASR 都必然由以下功能子集构成：
- F1：判断"这一段/这一帧"是不是目标说话人（speaker gating）
- F2：把目标说话人的音频/特征送进 ASR
- F3：抑制非目标说话人对 ASR 的输出污染（尤其在重叠区域）
不同方案在 F1/F2/F3 的实现位置不同：
暂时无法在飞书文档外展示此内容
第 3 步：按真实可落地性筛选
暂时无法在飞书文档外展示此内容
真实生产已验证的端侧 TS-ASR 路径只有 C（Google Pixel VoiceFilter-Lite），其它 D 类端到端方案在端侧没有公开上线证据。 但 C 没有现成可下载的预训练权重。
第 4 步：你的方案 A 的真实风险点（用调研到的数字定量）
暂时无法在飞书文档外展示此内容
第 5 步：失败域定位
把方案 A 的失败模式按"什么时候会出错"归类：
1. 切片太短（< 2s）→ embedding 不稳定 → 阈值越界 → 误判（漏识别 / 误识别）
2. 切片含重叠（overlap）→ embedding 被污染 → 同上
3. 跨域（远场、方言、信道）→ 注册音频和实时音频分布不一致 → 阈值漂移
4. 注册音频本身偏短或不干净 → 整个系统退化
这些都是工程上可观测、可缓解但不可消除的问题。

---
4. 推荐方案 + 主要 trade-off
4.1 推荐分阶段策略（务实路径）
阶段 1（MVP，1-2 周可上线）：方案 A 的工程化加固版
[mic stream]
  → silero-vad (frame-level)                           # 已内置
  → endpoint 切段
  → CAM++ / 3D-Speaker eres2net 提 embedding           # sherpa-onnx 已内置
  → 与注册 embedding 余弦相似度 (≥3 段平均，多注册增强)
  → 决策（接受 / 拒绝 / 边界态丢给 ASR 但低置信度返回）
  → sherpa-onnx 流式 zipformer 直接 AcceptWaveform 整段
关键加固点（解决推导链第 4 步的 5 类风险）：
1. 多模板注册：注册不少于 3 段、每段 5-10s、不同语速/距离的音频，取均值或 multi-prototype，直接抵消"短音频不稳"和"跨域退化"
2. 片段最短长度门限：< 1.5s 的切片不进入说话人判别，要么直接丢弃，要么累积到下一段（这个数字按 EER 表来定）
3. 滑窗内多次打分：长片段不要只做一次 embedding；按 2-3s 窗口 + 0.5-1s 步长打多个分，取多数票或最高分，对 overlap 场景有缓解（但不能根治）
4. 双阈值：高阈值（如 0.5-0.6）直接接受，低阈值（如 0.2-0.25）直接拒绝，中间区域可走"先识别再标注低置信"或"丢弃"。先用真实数据采 100-300 对样本标定 ROC，不要直接用默认 0.31
5. 流式 zipformer 做整段推理（无需再加非流式模型）：用 sherpa-onnx 现成的 AcceptWaveform(整段) + InputFinished + Decode 流程；如果发现精度差距明显再考虑加非流式模型
主要 trade-off：
暂时无法在飞书文档外展示此内容
阶段 2（如果 MVP 暴露 overlap / 短切片问题严重）：升级 F1 到帧级
候选 a：自训一个轻量 Personal VAD（130K 参数，可以塞进端侧），把"目标说话人"的判别从段级降到帧级，把 overlap 段的"非目标帧"剥离掉再喂 ASR。
候选 b：把 sherpa-onnx 的 OfflineSpeakerDiarization（pyannote-segmentation 3.0 + 3D-Speaker + 聚类）当作一种"段级 + overlap aware"的 F1，再做"哪个簇是目标"的余弦匹配。代价是离线、RTF≈0.24（3D-Speaker int8）-0.11（NeMo TitaNet int8）。
阶段 3（如果 MVP+2 仍不够，且业务可投入算法资源）：考虑前端 TSE
VoiceFilter-Lite 思路自训：speaker embedding + ASR 同特征域的 mask 网络，前端过滤 fbank。端侧已有真实生产案例（Google Pixel）。代价：需要数据、训练能力，且需要让 mask 网络的输入 fbank 与 sherpa-onnx zipformer 的特征对齐（log Mel-fbank 80-dim，比较容易对齐）。
4.2 另一种值得评估的端到端候选（如果团队有训练能力）
NVIDIA NeMo 的 CONF-TSASR 已开源，是 conformer + speaker embedding + mask + ASR 的端到端模型，但端侧落地几乎没有公开案例，工作量主要在 onnx 导出和量化。如果你已经在 sherpa-onnx 体系里，方案 A + 阶段 2 的渐进路径性价比明显更高。

---
5. 代码（落地骨架）
下面给出阶段 1 的最小骨架，所有组件都是 sherpa-onnx 现成 API，端侧无需新模型。注释只标"为什么"，不标"做什么"。
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

要点说明：
1. asr_decode_full_segment 用的是已有的流式 recognizer，对应推导链第 1 步的核心结论：流式 onnx 模型直接吃整段音频，不需要再加一个非流式模型
2. segment_score 用滑窗多次打分取最大值，缓解 overlap 段把整段 embedding 拉偏的问题
3. 阈值是双值（HIGH/LOW），中间区域如何处理留作业务决策（默认建议丢弃）
4. enroll 强制平均多段，并对 embedding 做单位化，对应阶段 1 加固点 1
5. 阈值数字要在你自己的设备 + 注册数据上做 ROC 标定，不要直接信默认值

---
已知未知（你接下来应该测）
1. 你的 zipformer 模型是不是用了"动态 right-context"训练？如果是，整段推理时调大 right-context frames 数能逼近非流式精度（ACL 2025 那篇的关键 trick）；如果不是，整段推理 WER 就锁定在流式上限
2. 真实业务里 VAD 切片的长度分布（中位数、< 2s 比例）——决定方案 A 短片段问题的严重性
3. 真实业务里重叠语音的占比和典型形态（连续重叠 / 交叠瞬时 / 远端扬声器漏音）——决定是否需要进入阶段 2
4. CAM++ 与 eres2net 在你设备上的 RTF 与最大可接受片段长度——决定滑窗策略的开销
5. 注册环境与使用环境的声学差距——决定多模板注册的必要性

---
关键引用
- sherpa-onnx 流式 zipformer 整段输入示例（AcceptWaveform + InputFinished + while IsReady: Decode）：cxx-api-examples/streaming-zipformer-cxx-api.cc
- sherpa-onnx Speaker ID Python 例子：python-api-examples/speaker-identification.py
- sherpa-onnx Speaker Diarization：python-api-examples/offline-speaker-diarization.py
- sherpa-onnx 已发布 wespeaker_en_voxceleb_CAM++.onnx / 3D-Speaker eres2net 等：releases/speaker-recongition-models
- 流式/非流式 zipformer 精度差异：Unifying Streaming and Non-streaming Zipformer-based ASR (ACL 2025 / arxiv 2506.14434)
- Google VoiceFilter-Lite 端侧实践：Google Research Blog
- TS-RNNT 流式端到端 TS-ASR：arxiv 2209.04175
- CONF-TSASR 端到端 TS-ASR：arxiv 2308.05218
- Personal VAD / PVAD 2.0：arxiv 1908.04284 / arxiv 2204.03793
- 短音频说话人验证 EER 退化基准：arxiv 2005.03329、VoxCeleb 论文 Table 3
- CAM++ 中文 EER 与部署：CSDN 模型对比、Sophon 端侧 CAM++ 实测
- sherpa-onnx Diarization 速度反馈：Discussion #3233

---
TL;DR
1. 你的方案方向对，但理由错。流式 zipformer 模型可以直接用于整段推理（用 sherpa-onnx 现成 API），不需要在内存里再放一个非流式模型。代价只是精度上限锁定在流式模型上限
2. 端侧 TS-ASR 真实生产案例只有 Google VoiceFilter-Lite（Pixel），但其没有官方开源权重；端到端 TS-ASR（TS-RNNT / CONF-TSASR）端侧无公开落地
3. 你的"VAD 切段 + CAM++ 验证 + 整段流式 ASR"是当前唯一能用 sherpa-onnx 现成组件零自训实现的可落地方案，sherpa-onnx 的 SpeakerEmbeddingExtractor / Manager / CAM++ / 3D-Speaker 模型都已发布
4. 这个方案的三大失败域是：短片段（< 2s EER 暴增 2-3 倍）、重叠语音（embedding 污染）、跨域（EER 翻倍）。用多模板注册 + 滑窗打分 + 双阈值 + 最短切片门限可以把这三个域都缓解（不能根治）
5. 后续如果数据反馈不够好，按 PVAD（帧级目标说话人 VAD）或 VoiceFilter-Lite（fbank 级 mask 前端）演进，且都不需要换 ASR 模型