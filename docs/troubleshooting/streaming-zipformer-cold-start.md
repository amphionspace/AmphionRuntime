# Streaming Zipformer 第一句被吞问题

本文记录 Android 实时识别中「总是漏掉第一句或前几个字」的根因和修复方式。

## 现象

用户点击「开始识别」后立刻说话：

- wav 中可以看到清晰人声，振幅正常。
- transcript 前几秒反复出现 ENDPOINT + FINAL=""。
- 第二句开始识别恢复正常。
- 这容易被误判为 VAD 截断、AudioRecord 启动延迟或厂商降噪问题。

本次实测中，第一段人声约 2.4s，RMS/peak 都明显高于底噪，但最终输出为空；第二段较短中文却能正常输出。

## 不是 VAD

Android sample 默认未启用 VAD：

- AsrConfig.Builder 默认 `enableVad=false`。
- sample 构造 AsrConfig 时只启用了 endpoint，没有调用 `enableVad(...)`。
- EngineImpl 中只有 `enableVad && vadModelPath != null` 才会构造 Vad。

因此「第一句被吞」不是 VAD 剪掉了开头。

## 根因

当前模型导出信息：

```json
{
  "chunk_size": 32,
  "left_context_frames": 256,
  "causal": true
}
```

streaming zipformer 刚创建 OnlineStream 时，encoder left-context cache 是空的。第一段真实语音进入时，前几个 chunk 缺少足够左侧上下文，输出容易坍缩到 blank。等 cache 被真实音频填满后，第二句开始恢复。

## 修复

在 SessionImpl 创建 stream 后，先在 decoder 线程投递一段静音 PCM 预热 encoder：

```kotlin
decoderHandler.post { warmUpEncoder(WARMUP_DURATION_MS) }
```

warmup 逻辑：

```kotlin
private fun warmUpEncoder(durationMs: Int) {
    val n = (sampleRate.toLong() * durationMs / 1000L).toInt()
    val silence = FloatArray(n)
    stream.acceptWaveform(silence, sampleRate)
    while (recognizer.isReady(stream)) {
        recognizer.decode(stream)
    }
    recognizer.reset(stream)
}
```

当前默认：

```kotlin
private const val WARMUP_DURATION_MS = 800
```

## 为什么 reset 后 warmup 仍然有效

sherpa-onnx transducer recognizer 默认 `reset_encoder=false`。当当前 result 为空时，`recognizer.reset(stream)` 会清 decoder hypotheses，但不重置 encoder state buffers。

也就是说：

1. 静音 PCM 先让 encoder cache 被推进。
2. reset 清掉静音导致的 decoder 中间状态。
3. encoder cache 保留。
4. 真实音频进入时不再从全 0 left-context 开始。

这使业务方无感，不需要在 app 层延迟录音或要求用户先等几秒。

## 验证结果

修复前：

| 指标 | 结果 |
| --- | --- |
| START 到首条 PARTIAL | 约 12s |
| 第一段 2.4s 清晰人声 | FINAL="" |
| 第二段中文 | 正常识别 |

修复后：

| session | START 到首条 PARTIAL | 结果 |
| --- | --- | --- |
| 184609 | 2.1s | 喂喂哈喽 |
| 184705 | 2.7s | TODAY MY |
| 184829 | 0.8s | 但是 |
| 184839 | 2.1s | 在跟房 |

第一句不再被吞。

## 注意事项

- warmup 时长不是越长越好。过短可能不够填 cache，过长会增加开始识别后的可见延迟。
- 800ms 是当前 Android sample 与 chunk_size=32 模型上的折中值。
- 如果未来换模型导出参数，应重新验证 warmup 时长。
- 如果上游 recognizer 改为 reset encoder state，则该策略需要重新评估。
- 这个修复解决 cold start，不解决英文低置信度；英文问题请看 `docs/troubleshooting/zh-en-mixed-asr-tuning.md`。

