# ASR SDK 角色分离能力：业界方案与 AmphionRuntime 落地建议

调研日期：2026-07-27

> 状态：研究提案，不代表已承诺的产品范围或交付计划。实施前仍需冻结业务语义、
> 评测集和跨端公共 API，并先通过最终 native 产物能力探针。

本文回答两个问题：

1. ASR SDK 能否支持“角色分离”；
2. 在 AmphionRuntime 当前端侧架构和生命周期契约下，应该先支持哪一种能力。

资料只采用厂商官方 API 文档、项目官方仓库和原始论文。产品能力会变化，文中云服务状态以调研日期为准。

## TL;DR

可以支持，但必须先把“角色分离”拆成四个不同问题：

| 能力 | 回答的问题 | 典型输出 | 是否需要注册 | 能否直接得到业务角色 |
| --- | --- | --- | --- | --- |
| 说话人日志 / diarization | 谁在什么时候说话 | `speaker_0, 1.2s-3.8s` | 否 | 否，通常只是 session 内匿名标签 |
| 说话人识别 / identification | 这个声音是已注册库中的谁 | `person_123` | 是 | 只有注册身份与角色已有映射时才可以 |
| 说话人验证 / verification | 这段是不是指定的人 | 相似度或布尔值 | 是 | 只能确认指定身份，不会自动发现其他角色 |
| 目标说话人 ASR / TS-ASR | 只识别指定人的话 | 目标人的文本 | 是 | 是，但仅限预先指定的目标人 |

另有“通道分离”和“语音源分离”：前者依赖不同麦克风/电话通道，后者实际重建不同人的音频；二者都不是 diarization。

对 AmphionRuntime 的判断：

- **离线匿名说话人分离：可行，风险中等。** 当前 pinned `sherpa-onnx` 已有 Android/Kotlin、C、Harmony 可复用的 `OfflineSpeakerDiarization`，组合 pyannote segmentation、speaker embedding 和 clustering，不需要新增推理框架。
- **已知身份或业务角色映射：可行，但必须建在 diarization 之上。** 用每个 cluster 的有效语音计算 embedding，再与注册库匹配；`speakerId`、`identityId`、`role` 必须分字段表达。
- **稳定的低延迟流式 diarization：不建议作为第一版。** 实时系统需要重写历史标签、处理短片段、重叠和 session 内聚类状态；这不是把一个 `speakerId` 塞进现有 final 回调就能正确完成的功能。
- **推荐 MVP：独立的 session 后处理 API。** 先对完整录音返回匿名 `SpeakerSegment[]`，再按 token 时间戳对齐文本；不改变 `isFinal/isLast/onComplete` 契约。随后再增加注册身份映射，最后才评估流式预览。

## 1. 真实问题与边界

业务口语中的“角色分离”至少可能指三种结果：

1. “把甲乙两个人的话分开显示”——匿名 diarization；
2. “知道谁是民警、谁是群众”——身份/角色赋值；
3. “只保留民警的话”——目标说话人检测、分离或 TS-ASR。

第一种是无监督聚类，系统只保证同一录音中相同标签尽量属于同一声音。标签 `speaker_0` 不具备跨 session 稳定性，更不等于业务角色。

第二种需要额外证据，业界常见做法只有三类：

- 物理通道已知：例如客服永远在 channel 0，客户在 channel 1；
- 身份已注册：声纹库中的 `identityId` 已与业务角色关联；
- 文本/流程推断：根据“您好，我是……”等内容猜角色。这是概率性语义分类，不能冒充生物身份认证。

AWS Call Analytics 是很典型的边界证据：它能输出 `AGENT` / `CUSTOMER`，但 API 要求调用方通过 `ChannelDefinitions` 指定哪个 channel 是哪个角色，并且 Call Analytics 只支持两通道、每通道一方；这不是从单通道混合音频中自动推断角色。[AWS Call Analytics](https://docs.aws.amazon.com/transcribe/latest/dg/call-analytics.html) [StartCallAnalyticsJob API](https://docs.aws.amazon.com/transcribe/latest/APIReference/API_StartCallAnalyticsJob.html)

## 2. 主流云 ASR API 怎么做

### 2.1 横向比较

| 产品 | batch / streaming | 配置方式 | 输出语义 | 实时约束 |
| --- | --- | --- | --- | --- |
| Azure Speech | 两者都有 | real-time SDK diarization；batch `diarization` + min/max speaker count | phrase 级 `speaker`；实时为 `Guest-1` 等匿名 ID | 早期 intermediate 可能为 `Unknown`；batch 单声道，最多小于 36 人，启用 diarization 时单文件不超过 240 分钟 |
| Google Cloud STT | recognize 与 Streaming | `diarizationConfig`，可给 `minSpeakerCount/maxSpeakerCount` | 每个 word 有数字 speaker label | streaming 每次会重发从音频开头累计的 words，以便模型随上下文修正 speaker tag |
| Amazon Transcribe | batch 与 streaming | `ShowSpeakerLabels` / `show-speaker-label` | batch 有 `speaker_labels`、segment、item 和时间戳，标签为 `spk_0...` | 最多区分 30 个匿名说话人；streaming 仅在完整 segment 上给可靠 speaker label |
| Deepgram | pre-recorded 与 live | `diarize_model=latest/v1/v2` | word 级 `speaker`；batch 另有 `speaker_confidence` | batch 当前可用 v2；streaming 只有 v1，且 live 不返回 speaker confidence |
| 腾讯云实时说话人分离 | streaming | 使用说话人分离专用模型 `16k_zh_en_speaker` | 句级 `speaker_id`、文本和起止时间 | 中间态可返回 `speaker_id=-1`；`speaker_context_id` 可在后续请求中保持 ID 连续性，但官方文档标注其有效期为 24 小时 |

来源：

- Azure real-time 的 `Guest-N`、早期 `Unknown` 与 intermediate 开关见 [Real-time diarization quickstart](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-stt-diarization)。batch 的单声道、人数范围和 240 分钟限制见 [Create a batch transcription](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/batch-transcription-create)。
- Google 的 word 级标签、min/max 配置、recognize/Streaming 支持与累计结果语义见 [Detect different speakers in an audio recording](https://cloud.google.com/speech-to-text/docs/multiple-voices)；流式响应重发历史 words 的原因也记录在 [RecognitionConfig API](https://cloud.google.com/speech-to-text/docs/reference/rest/v1/RecognitionConfig)。
- AWS 的 30 人上限、`spk_0` 标签和 batch/streaming 示例见 [Partitioning speakers (diarization)](https://docs.aws.amazon.com/transcribe/latest/dg/diarization.html)。
- Deepgram 的模型版本、batch/streaming 支持范围及返回字段见 [Speaker Diarization](https://developers.deepgram.com/docs/diarization)。
- 腾讯云的 Harmony SDK 接入、句级返回字段见 [实时说话人分离](https://cloud.tencent.com/document/product/1093/133360)；`speaker_id=-1` 和 `speaker_context_id` 语义见 [话者分离 JSON 响应格式](https://cloud.tencent.com/document/product/1093/133355)。

### 2.2 这些 API 共同揭示的接口原则

1. **speaker label 是附着在时间区间或 word 上的，不是整场 session 的单一属性。**
2. **speaker count 是提示或范围，不是永远正确的事实。** 人数未知时仍要聚类；人数先验准确会降低过分裂/欠分裂风险。
3. **实时标签是暂态。** Azure 会先返回 `Unknown`；Google 为修正标签而重复返回历史 words。SDK 若承诺每条 partial 的 speaker ID 永不变化，会被迫牺牲质量或等待更长上下文。
4. **云厂商返回的通常是匿名标签。** `Guest-1`、`spk_0` 和数字 label 都不代表真实身份或业务角色。
5. **通道已分开的音频应优先按通道处理。** AWS 明确区分 single-channel diarization 与 dual-channel channel identification；已知通道比从混音中聚类更确定。[AWS audio channels](https://docs.aws.amazon.com/transcribe/latest/dg/how-input.html)

## 3. 开源与研究方案

### 3.1 离线 diarization：当前最成熟的端侧路径

经典级联 pipeline 是：

```text
PCM -> speech/overlap segmentation -> speaker embedding -> clustering
    -> [start, end, anonymous speaker label]
```

代表实现：

| 方案 | 运行方式 | 特点 | 与 ASR 的关系 |
| --- | --- | --- | --- |
| pyannote.audio `community-1` | 本地离线，PyTorch | 直接返回 speaker turns；可指定人数；支持重叠；另提供 exclusive diarization | diarization 独立运行，之后与 ASR 时间戳对齐 |
| WhisperX | 本地离线 | Whisper 批量转写 + forced alignment + pyannote diarization | 通过 word-level timestamps 把文本归到 speaker |
| NVIDIA NeMo | 离线和 streaming 模型均有 | Sortformer 端到端模型；另有 VAD + embedding + clustering 级联方案 | 可独立 diarize，也可组成带 speaker attribution 的 ASR pipeline |
| sherpa-onnx | 本地离线，多语言绑定 | pyannote/reverb segmentation + 3D-Speaker/NeMo embedding + fast clustering，已有 ONNX 与移动端 API | 输出时间段和匿名整数 speaker，需另行与 ASR 对齐 |

来源：

- pyannote 官方仓库展示 `speaker-diarization-community-1` 本地推理及 `(start, stop, speaker)` 输出：[pyannote.audio](https://github.com/pyannote/pyannote-audio)。其 exclusive 模式强制任一时刻只有一位 speaker，便于和单路 STT 时间戳对齐，但因此不再完整表达重叠语音。
- WhisperX 官方仓库说明其提供 word-level timestamps 和 diarization；原始 Interspeech 论文解释了 VAD、批处理 Whisper 与 forced phoneme alignment 的流水线：[WhisperX repository](https://github.com/m-bain/whisperX) [WhisperX paper](https://arxiv.org/abs/2303.00747)。
- NeMo 官方文档区分 Sortformer end-to-end diarization 和传统级联 diarization，并列出 offline 与 streaming pretrained model：[NeMo Speaker Diarization](https://docs.nvidia.com/nemo/speech/nightly/asr/speaker_diarization/intro.html)。
- sherpa-onnx 官方 C API 明确将该能力命名为 `OfflineSpeakerDiarization`，组合 segmentation、embedding、clustering，返回 `speaker/start/end`：[sherpa-onnx Offline Speaker Diarization](https://k2-fsa.github.io/sherpa/onnx/c-api/html/speaker_diarization.html)。

### 3.2 diarization 之后做身份识别

匿名 cluster 变成已知身份的常见做法是：

1. 对每个 cluster 收集足够长且尽量无重叠的有效语音；
2. 生成 cluster embedding；
3. 与 enrollment embedding 库做相似度检索；
4. 高于经业务数据标定的阈值才填 `identityId`，否则保持 unknown；
5. 再由业务表将 `identityId` 映射为 `role`。

sherpa-onnx 已提供 embedding extraction，以及 enrollment、search、verify、best matches 等 manager API，证明这条链路不需要引入新的向量运行时：[Speaker Embedding Extraction and Management](https://k2-fsa.github.io/sherpa/onnx/c-api/html/speaker_embedding.html)。

不能把“cluster 内平均声纹最像某人”当作强认证。短片段、跨设备、远场、噪声和重叠都会污染 embedding；unknown 阈值必须保留，不能强迫每个 cluster 归到注册库中的某个人。

### 3.3 目标说话人：与“多人都转写”不同

目标说话人方案的目标不是给所有人编号，而是抑制或跳过非目标人的音频：

- Personal VAD 在每帧输出 non-speech、target speech、non-target speech 三类概率，可作为流式端侧 ASR 的输入门控。Google 原始论文的模型仅 130K 参数，但需要带目标 speaker embedding/score 的专门训练。[Personal VAD](https://google.github.io/speaker-id/publications/PersonalVAD/)
- VoiceFilter-Lite 是单通道、流式、端侧的 target speaker separation；它在特征层压制重叠的非目标说话人，可 INT8 实时运行，但需要目标人 enrollment 和专门的混合语音训练。[VoiceFilter-Lite](https://google.github.io/speaker-id/publications/VoiceFilter-Lite/)
- DiCoW 把 diarization 结果作为 Whisper 条件做 target-speaker ASR，能处理重叠且不依赖固定 speaker embedding，但属于需要专门模型权重的离线大模型路线。[DiCoW paper](https://arxiv.org/abs/2501.00114)

AmphionRuntime 已有目标说话人验证/Speaker VAD，因此该能力可以与 diarization 共存，但不能替代 diarization：它回答“是不是目标人”，不回答“现场一共有谁、每个人何时说话”。

## 4. 质量、延迟、隐私与训练约束

### 4.1 质量失败域

| 失败域 | 表现 | 设计影响 |
| --- | --- | --- |
| 短句/附和词 | cluster 漂移或 identity 无法可靠评分 | segment 要允许 `speakerId=unknown`，身份字段可空 |
| 两人音色接近 | speaker confusion | 不能用 speaker 数量正确代替归属正确 |
| 噪声、远场、跨设备 | embedding 域偏移 | 阈值要用目标设备和场景标定 |
| 重叠语音 | 一个时间点可能有两个 active speakers；单路 ASR 可能只转出其中一人 | 数据模型必须允许重叠；若输出 exclusive 版本要明确它是对齐视图，不是完整事实 |
| speaker 数量未知 | 过分裂：一人多个 label；欠分裂：多人同 label | 接口接受人数先验，但不能假设调用方总能提供 |
| ASR 时间戳误差 | 文本落到相邻 speaker | 以 word/token 中点或重叠比例对齐，并保留不可归属状态 |

验收不能只看识别文本。Diarization Error Rate（DER）由 false alarm、missed detection 和 speaker confusion 组成；评测协议还必须说明 boundary collar 和是否跳过 overlap，否则不同报告不可比较。[pyannote.metrics principles](https://pyannote.github.io/pyannote-metrics/basics.html) [DER API](https://pyannote.github.io/pyannote-metrics/reference.html)

建议至少报告：

- DER 及其 false alarm / miss / confusion 分量；
- speaker count accuracy、过分裂率、欠分裂率；
- overlap 区与非 overlap 区分桶；
- speaker-attributed CER/WER，而不只是普通 CER/WER；
- 若做已知身份：按片段时长、设备、距离、噪声分桶的 identification precision/recall 和 unknown rejection；
- batch RTF、峰值 RSS；若做 streaming，另报首次稳定 speaker label 延迟、turn latency 和历史 revision 次数。

### 4.2 延迟与状态边界

batch 看得到完整上下文，能在全局聚类后再统一编号，通常更容易提供稳定标签；代价是必须等待完整录音并缓存 PCM。streaming 必须在“尽快出标签”和“等待足够语音形成可靠 embedding”之间取舍。

云 API 已经展示两种合理语义：

- interim speaker 可为 `Unknown`，稍后稳定；
- 重发或 revision 先前词的 speaker label。

因此流式接口至少要有 `provisional/final` 或 revision 语义。让早期 `speakerId` 永不修改，只会把算法不确定性藏成错误标签。

### 4.3 隐私与部署

声音 embedding 具有身份关联性；录音、转写、声纹和角色映射应分别定义用途、留存期和删除机制。云方案意味着音频离开设备，本地 ONNX 方案则可以避免上传，但应用仍须获得录音和生物特征处理所需授权。

官方云服务的具体边界并不相同：

- Azure 声明 real-time 音频只在服务端内存处理、不落盘；batch 输入位于客户指定存储，结果可通过 TTL 删除。[Azure Speech data privacy](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security)
- Google 声明未加入 data logging opt-in 时，不会把内容用于提供服务之外的目的；streaming/sync 在内存处理，async transcript 约保留 5 天供拉取。[Google STT data usage FAQ](https://cloud.google.com/speech-to-text/docs/data-usage-faq)
- AWS 说明 diarization 提取的 voice characteristic signals 只用于标注 transcript，处理后不保留；客户内容用于改进服务可通过 Organizations 等机制退出。[Amazon Transcribe AI Service Card](https://docs.aws.amazon.com/ai/responsible-ai/transcribe-speech-recognition/overview.html)

上述是服务声明，不替代业务所在地的录音、通信和生物识别合规评估。

### 4.4 训练与模型约束

- 云 diarization 是托管能力，通常不要求客户训练，但依赖网络、区域、语言支持和服务端版本。
- pyannote/NeMo/sherpa-onnx 可直接用预训练模型做 baseline；真实业务域精度不够时，需要带 speaker turn、overlap 和身份标注的域内数据微调或标定。
- clustering threshold 不是通用常数。当前 sherpa-onnx Kotlin 示例也明确要求调用方自行调阈值，并说明阈值变大会产生更少 cluster。
- Personal VAD、VoiceFilter-Lite 和 end-to-end TS-ASR 不是把现有 speaker embedding 接上即可；它们需要目标/干扰混合、重叠、噪声和 enrollment 条件覆盖的专门训练数据。

## 5. AmphionRuntime 现状映射

### 5.1 已具备的基础

- 当前公开 `AsrResult` 已有 token 和 token 起始时间，可作为内部 speaker/text 对齐基础：Android 见 `asr/android/sdk/src/main/java/com/amphion/asr/AsrResult.kt`，Harmony 见 `asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets`。
- 鼎桥包装层当前只公开整段 `beginTime/endTime` 和 `speakerSimilarity`，没有逐 token 时间戳；若需要精确到词的“谁说了什么”，必须扩展公共数据或在 SDK 内完成对齐。
- 当前 `speakerSimilarity` 是“该 final 与目标声纹的相似度”，不是匿名 speaker cluster，也不是 role。
- pinned `third_party/sherpa-onnx` 已有：
  - `sherpa-onnx/kotlin-api/OfflineSpeakerDiarization.kt`；
  - `kotlin-api-examples/test_offline_speaker_diarization.kt`；
  - C API 与 Harmony 构建/示例资产；
  - speaker embedding manager。

但这里必须区分“源码树具备能力”和“当前 SDK 交付二进制已包含能力”。本次对
`asr/android/sdk/src/main/jniLibs/arm64-v8a/libsherpa-onnx-jni.so` 以及本地 Android build
产物做符号/类字符串检查，未发现 `OfflineSpeakerDiarization`；因此 Android 阶段 1 的第一个
工程门禁是实例化探针和 JNI 符号核验，若失败则需要用当前 pinned 源码重编 native 库。Harmony
也应对最终 HAR 做同样的产物级探针，不能用源码目录中存在示例代替交付验证。

这意味着模型与推理框架无需从零研发，但第一版仍包含 native 产物重建风险；主要工作还包括
产品语义、录音缓存、跨端封装、文本对齐和评测。

### 5.2 不应直接复用的字段

不要将以下概念合并：

```text
speakerId        = 本 session 的匿名 cluster，例如 "spk_0"
identityId       = 注册库中的稳定身份，可空
role             = 业务角色，可空，例如 "officer" / "citizen"
speakerSimilarity = 对某个明确 enrollment 目标的匹配分数，可空
```

同一个 `speakerId` 可以因身份证据不足而没有 `identityId`；同一个 `identityId` 的 `role` 可以由业务配置变化；纯语义角色推断也可能有 role 但没有 identity。合并字段会让下游无法区分算法聚类、身份认证和业务规则。

## 6. 推荐落地路线

### 阶段 0：先冻结需求词汇和验收集

要改变的行为：为一段多人录音返回匿名 speaker turns，并能将 ASR 文本按时间归属。

必须保持不变：

- 普通连续识别在 `finish(sessionId)` 前不产生 `isLast=true`；
- 每个正常 session 恰好一次 `isLast=true`，之后恰好一次 `onComplete`；
- cancel 不产生 final/complete；
- 当前 `speakerSimilarity` 的可选性和语义不变。

第一版明确不处理：跨 session 自动认人、从单通道文本自动判业务角色、重建每个人的独立音轨、流式 stable speaker ID。

准备有人工标注的中文业务集，必须包含：单人、两人轮流、短附和、相似音色、前景/远场、噪声、抢话和长重叠。

### 阶段 1：独立 batch diarization MVP

建议新增独立 API，而不是改变现有 ASR callback：

```kotlin
data class SpeakerSegment(
    val startTimeSec: Float,
    val endTimeSec: Float,
    val speakerId: String,       // session-scoped anonymous ID
    val text: String? = null,
    val identityId: String? = null,
    val role: String? = null,
    val isOverlap: Boolean = false,
)

data class DiarizationResult(
    val segments: List<SpeakerSegment>,
    val speakerCount: Int,
)

suspend fun diarize(audio: PcmAudio, expectedSpeakerCount: Int? = null): DiarizationResult
```

实现链路：先验证/重建包含 diarization JNI 的最终产物；完整 PCM -> sherpa-onnx
`OfflineSpeakerDiarization` -> speaker segments -> 用现有 token timestamps 对齐文本。若上层只拿到
鼎桥 phrase 时间，则第一版先 phrase 级归属，不能宣称 word-level attribution。

独立 API 的主要 trade-off：调用方要保存或传入完整 PCM，并等待后处理；换来的是不改变流式 ASR 生命周期、label 可以一次性稳定、失败域可独立测试。

### 阶段 2：注册身份和业务角色映射

对 cluster 的长且干净片段提 embedding，与注册库做阈值检索；输出可空 `identityId`，再由调用方映射 `role`。复用已有 speaker embedding 模型和 manager，但阈值必须重新按 diarization cluster 音频标定，不能沿用单句 `speakerSimilarity` 阈值。

对固定双通道场景，优先允许调用方直接传 `channel -> role`，跳过不必要的声纹推断。

### 阶段 3：可修订的 streaming preview

只有业务证明 batch 延迟不可接受时再进入。接口必须支持：

- `Unknown` / provisional speaker；
- 历史 segment revision 或 stable-after 时间；
- session-scoped ID；
- overlap；
- finish 后一次最终归一化结果。

建议把 streaming speaker turns 放在独立 callback/事件流中，不用全局 `finishRequested` 或现有 `isFinal/isLast` 推断 speaker 状态。ASR final 仍只表达 endpoint 的文本最终性，不等于 speaker cluster 已全局稳定。

## 7. 建议的决策门

| 决策 | 通过条件 | 不通过时 |
| --- | --- | --- |
| 是否做阶段 1 | 业务需要“多人都保留并标号”，且允许 session 后处理 | 若只需目标人，继续强化现有 Speaker VAD/verification |
| 预训练模型能否直接交付 | 域内 DER、speaker-attributed CER/WER、RTF/RSS 均达标 | 先标定人数/聚类阈值；仍不达标再做域内微调 |
| 是否做身份映射 | 有合法 enrollment、unknown rejection 和跨设备评测集 | 只输出匿名 `speakerId` |
| 是否做 streaming | batch 端到端延迟被真实调用方场景证明确实不可接受 | 保持 batch，避免引入 revision 状态机 |
| 是否做真正语音分离 | 重叠区域的 speaker-attributed WER 是主要失败源，且单纯 diarization 无法满足 | 单独立项 VoiceFilter/TS-ASR，不把它伪装成 diarization 参数 |

## 8. 最终建议

AmphionRuntime **可以支持角色分离**，但建议对外命名为“说话人分离/说话人日志（speaker diarization）”，第一版只承诺 session 内匿名 speaker label。基于现有 sherpa-onnx 资产，最小 coherent change 是新增独立的离线 diarization API，并在内部把 speaker 时间段与 ASR token 时间戳对齐。

主要 trade-off 是增加整段 PCM 缓存和 session 后处理延迟；收益是模型资产可复用、跨端可落地、标签稳定，而且不污染已经严格约束的 ASR `final/last/complete` 生命周期。

“民警/群众”等角色应作为后续映射层：优先使用已知通道，其次使用注册声纹，最后才是可选的文本语义推断。流式 diarization 和真正的重叠语音分离应作为两个独立项目验收，不能靠给现有 `AsrResult` 增加一个永不修订的 `speakerId` 字段来宣称完成。
