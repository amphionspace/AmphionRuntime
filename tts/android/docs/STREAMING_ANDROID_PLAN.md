# Lits Android 真流式改造计划

## 目标

让 Android SDK 支持真正的流式推理，而不是“整句合成后再切 PCM 分片”。

当前仓库里已经具备两部分前提：

1. PyTorch 模型存在流式推理路径：
   - `LITS.get_hidden_mel(...)`
   - `LITS.get_mel(..., streaming=True)`
   - `CFM_Causal.forward(..., finalize, streaming=True)`
2. 本地已经可以测训练侧流式指标：
   - [infer/benchmark_streaming_local.py](dingqiao_lits/infer/benchmark_streaming_local.py:1)

但 Android 交付包目前仍是非流式资产，因此 SDK 侧暂时无法实现真实首包提前。

## 当前阻塞点

### 1. SDK Runtime 是整句式调用

[LitsTtsOrtRuntime.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsOrtRuntime.kt:24)

- acoustic ONNX 输入：`token_ids`, `token_lengths`, `speaker_id`
- acoustic ONNX 输出：`mel`
- vocoder ONNX 输入：`mel`
- vocoder ONNX 输出：`waveform`

这里没有 chunk 输入，也没有 cache/state 输出。

### 2. SDK 的 `onData` 不是模型流式

[TextToSpeechEngineImpl.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/TextToSpeechEngineImpl.kt:206)

先执行：

- `synthesizer.synthesize(...)`

再执行：

- `emitAudioChunks(...)`

因此 `onData` 只是“后切片”，不影响首包。

### 3. 导出的 manifest 明确关闭了流式

[export_lits_delivery_16k_hifigan_onnx.py](tools/dingqiao-onnx-export/export_lits_delivery_16k_hifigan_onnx.py:1011)

当前导出结果写死：

- `"supports_streaming": false`

### 4. ONNX 导出协议仍然是整句 mel

[export_lits_delivery_16k_hifigan_onnx.py](tools/dingqiao-onnx-export/export_lits_delivery_16k_hifigan_onnx.py:306)

虽然导出 wrapper 内部调用了流式路径，但最终还是把整个过程包成：

- `token_ids/token_lengths/speaker_id -> mel`

这对于 Android 运行时来说仍然是“整句声学模型”。

## 训练侧已经具备的流式语义

### 1. 隐变量阶段和解码阶段已经拆开

[train/lits/models/lits.py](dingqiao_lits/lits/models/lits.py:135)

- `get_hidden_mel(...)` 产出 `mu_y`, `y_mask`, `y_max_length`, `spks`
- `get_mel(...)` 接收 `mu_y`, `y_mask`, `finalize`, `streaming`

这正好适合拆成 Android 可消费的两段或三段协议。

### 2. `CFM_Causal` 已有 lookahead/finalize 语义

[flow_matching.py](dingqiao_lits/lits/models/components/flow_matching.py:177)

关键点：

- `pre_lookahead_len`
- `finalize`
- `streaming=True`

非最后 chunk 会保留 `pre_lookahead_len` 未来帧作为上下文。

### 3. Conformer/Attention 已考虑 ONNX 流式缓存形态

[transformer.py](dingqiao_lits/lits/models/components/transformer.py:398)

注释里已经明确提到：

- ONNX 1st chunk 可以喂 real cache / empty cache
- attention cache 可通过张量拼接方式导出

这说明“带 cache 的 ONNX chunk 模型”是可行方向。

## 推荐的 ONNX 协议拆分

不建议继续导出单个 `lits_acoustic.onnx`。

建议拆成下面三段：

1. `lits_hidden_encoder.onnx`
2. `lits_stream_decoder.onnx`
3. `hifigan_stream_vocoder.onnx` 或保留 `hifigan_vocoder.onnx`

### 方案 A：最稳妥的两阶段声学 + 整段 vocoder

第一阶段：

- 输入：`token_ids`, `token_lengths`, `speaker_id`
- 输出：`mu_y`, `y_mask`, `y_max_length`, `spk_embed(optional)`

第二阶段：

- 输入：`mu_y_chunk`, `y_mask_chunk`, `speaker_embed`, `finalize`
- 输出：`mel_chunk`

第三阶段：

- 输入：`mel_chunk`
- 输出：`waveform_chunk`

优点：

- 与现有 PyTorch benchmark 路径最接近
- 先把首包降下来，改造风险相对最低

缺点：

- 第二阶段如果每个 chunk 都重新跑整段左上下文，RTF 可能比理想值高

### 方案 B：真正带 cache 的 streaming decoder

第二阶段升级为：

- 输入：`mu_y_chunk`, `y_mask_chunk`, `speaker_embed`, `finalize`, `attn_cache_in`, `conv_cache_in`, `offset`
- 输出：`mel_chunk`, `attn_cache_out`, `conv_cache_out`

优点：

- 更接近生产级真流式
- Android 端 RTF 和首包都更容易做优

缺点：

- 导出脚本和 runtime 都更复杂
- 需要先明确每层 cache 的张量布局

## Android SDK 侧需要的改动

### 1. manifest 增加流式模型描述

当前 `ManifestInfo` 只校验：

- sample rate
- speaker count
- acoustic/vocoder file

[LitsTtsAssetInstaller.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsAssetInstaller.kt:37)

建议新增字段：

- `supports_streaming: true`
- `streaming_chunk_size`
- `streaming_pre_lookahead_len`
- `streaming_mel_cache_len`
- `hidden_encoder_model.file`
- `stream_decoder_model.file`
- `stream_vocoder_model.file` 或复用现有 vocoder

### 2. Asset Registry 允许新模型文件

[LitsTtsAssetRegistry.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsAssetRegistry.kt:3)

至少要新增：

- `HIDDEN_ENCODER_MODEL`
- `STREAM_DECODER_MODEL`
- 可选 `STREAM_VOCODER_MODEL`

### 3. Runtime 从 `synthesize()` 改为 session 化流式接口

建议新建接口，而不是硬改当前整句 API：

- `prepare(text, speakerId): StreamState`
- `nextMel(state): MelChunkResult`
- `nextAudio(state): AudioChunkResult`

或者在 Kotlin 内部实现成：

- `synthesizeStreaming(...) : Sequence<FloatArray>`

### 4. PcmSynthesizer 增加 chunk 回调能力

当前接口：

- `synthesize(...) -> SynthesizedAudio`

[PcmSynthesizer.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/PcmSynthesizer.kt:13)

建议扩成两类：

- `synthesize(...) -> SynthesizedAudio` 保留旧模式
- `stream(...) -> Iterator<SynthesizedChunk>` 新增真流式

### 5. Engine 在推理过程中实时触发 `onData`

当前逻辑是：

- 先全合成
- 再 `emitAudioChunks`

应改为：

- 每出一段 waveform chunk 就立刻 `notifyData(...)`
- 最后再发 `SYNTHESIS_COMPLETE`

## 推荐实施顺序

### 第 1 步：先做“可运行但不带 cache”的流式 ONNX

目标：

- 先拿到 Android 真首包
- 先证明协议走通

做法：

1. 导出 `hidden_encoder.onnx`
2. 导出 `stream_decoder.onnx`
3. 复用现有 vocoder，逐 chunk 喂 mel
4. Android 侧按 chunk 调 decoder + vocoder

这是最适合当前仓库状态的起点。

### 第 2 步：对齐本地 benchmark

以 [infer/benchmark_streaming_local.py](dingqiao_lits/infer/benchmark_streaming_local.py:1) 为基线，至少对比：

- `first_mel_ms`
- `first_audio_ms`
- `acoustic_rtf`
- `vocoder_rtf`
- `total_rtf`

### 第 3 步：再做 cache 化导出

如果第 1 步 Android 端 RTF 偏高，再推进真正的 cache ONNX。

## 已有本地基线

2026-06-16，本机 MPS 测得：

- warm `first_mel_ms`: 72.27 - 81.68 ms
- warm `first_audio_ms`: 106.19 - 106.44 ms
- warm `total_rtf`: 0.1203 - 0.1252
- cold `first_audio_ms`: 341.39 ms

这些数字只代表 PyTorch 本地流式链路，不代表 Android ONNX 结果。

## 下一步最值得直接动手的文件

1. [LitsTtsSdk/tools/export_lits_delivery_16k_hifigan_onnx.py](tools/dingqiao-onnx-export/export_lits_delivery_16k_hifigan_onnx.py:1)
2. [LitsTtsSdk/android/AmphionRuntime/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsOrtRuntime.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsOrtRuntime.kt:1)
3. [LitsTtsSdk/android/AmphionRuntime/sdk/src/main/java/com/lits/tts/sdk/internal/PcmSynthesizer.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/PcmSynthesizer.kt:1)
4. [LitsTtsSdk/android/AmphionRuntime/sdk/src/main/java/com/lits/tts/sdk/internal/TextToSpeechEngineImpl.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/TextToSpeechEngineImpl.kt:1)
5. [LitsTtsSdk/android/AmphionRuntime/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsAssetInstaller.kt](tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsAssetInstaller.kt:1)

## 建议的下一次改造目标

下一轮优先做下面这一件：

- 在导出脚本里新增 `hidden_encoder.onnx` 和 `stream_decoder.onnx` 的原型导出

做到这一步，就可以开始让 Android SDK 真正按 chunk 跑起来。
