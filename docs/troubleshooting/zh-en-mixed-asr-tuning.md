# 中英混合 ASR 实机调优经验

本文记录一次 Android 实机上「测试集正常，但纯英文几乎不可用」的排查过程和最终结论。它不替代 README，也不介绍 SDK 基本接入；这里专门沉淀工程细节、现象解释和可复用排查方法。

## 结论

纯英文不可用不是单一问题，而是三个因素叠加：

| 因素 | 现象 | 处理 |
| --- | --- | --- |
| greedy_search 对英文 BPE 链路过脆 | 英文短句只出 1-2 个词，或长期 blank | 改为 modified_beam_search，max_active_paths 建议 8 |
| Android 录音电平偏低 | dump 实测 RMS 约 -50 dBFS，比常见训练音频低 25-30 dB | sample 层加 +10 dB 软增益并 clip |
| endpoint 切分过频 | 英文短停顿后被切成多段，decoder context 反复重置 | 后续可把 rule2 从 1.4s 调到 2.0-2.5s |

本轮验证后，英文从「几乎不可用」恢复到可以连续识别：

| 修复前 | 修复后 |
| --- | --- |
| SAY SOMETHING 或 TODAY MY 这种 1-2 词碎片 | SUMMER HAS COME AND PASSED THE INNOCENT CAN NEVER NEST |
| 英文 conf 约 0.03-0.14 | 英文 conf 约 0.17-0.50 |
| 中英混合常吞英文 | THAT IS SO RARE 反正就是很奇怪 / 今天我想去吃一顿 KFC 你觉得呢 |

## 推荐默认配置

模型 manifest 建议显式指定 beam search：

```json
{
  "decoding_method": "modified_beam_search",
  "max_active_paths": 8
}
```

Android sample 当前使用 +10 dB 软增益：

```kotlin
AudioRecorder(
    sampleRate = 16000,
    onPcm = { samples -> session.acceptPcmShort(samples, 16000) },
    onError = { msg -> /* handle */ },
    gainDb = 10f,
)
```

软增益应在 PCM short 上做饱和裁剪：

```kotlin
val v = (sample * factor).toInt()
sample = v.coerceIn(-32768, 32767).toShort()
```

## 为什么测试集正常，实机纯英文不行

测试集一般满足这些条件：

- 音频电平接近训练分布，常见在 -20 到 -25 dBFS。
- 文件离线解码或脚本 benchmark 常一次性喂整段音频，不受实时 endpoint 切分影响。
- 评测脚本常用 beam search 或更适合评测的解码配置。
- 测试集英文句子边界清晰，少受手机麦克风、厂商 DSP、环境噪声影响。

Android 实时使用则不同：

- vivo / OPPO 等机型的 VOICE_RECOGNITION 通道可能输出很低，实测约 -50 dBFS。
- streaming 每 100ms 喂一次，英文 BPE token 需要连续 emit，greedy 一旦选 blank 就不可逆。
- endpoint 在静音 1.4s 后触发，短停顿会把英文句子切碎。
- 用户真实说话含停顿、重复、口误，中英切换更频繁。

因此「模型本身支持中英混合」不等于「默认 Android 实时配置能稳定吃下纯英文」。

## 关键证据

同一段 Android dump 的 wav，用 PC 端同模型对照：

| 条件 | 结果 |
| --- | --- |
| streaming + greedy + 0dB | TODAY MY / LIKE YOU，英文经常短碎 |
| streaming + modified_beam_search + 0dB | I LIKE YOU 等前缀恢复 |
| streaming + greedy + 10dB | I LOVE YOU DOES ANYBODY HEAR ME 等句子恢复 |
| streaming + modified_beam_search + 10dB | 英文和中英混合恢复明显 |

这说明问题不是 ONNX Runtime、int8 量化、tokens 反解或 Android JNI 不一致，而是实时解码策略和输入电平。

## 已排除的嫌疑

| 嫌疑 | 排除依据 |
| --- | --- |
| VAD | sample 默认未启用 VAD，EngineImpl 中 vad 为 null |
| ONNX Runtime / int8 不一致 | 同一 wav 在 PC 模拟 streaming greedy 下能复现实机输出模式 |
| tokens / BBPE 反解错误 | 中文识别正常，英文 BPE token 也可在 beam + gain 下正确输出 |
| LID token 干扰 | 8003 个 token 中只有 #0/#1/#2 三个 LID token，dump 中未观察到 LID 文本 |
| 模型完全不会英文 | modified_beam_search + 10dB 后能识别完整英文句 |

## 排查流程

1. 先用 Android sample 打开 debug dump，拿到 audio.wav 和 transcript.txt。
2. 看 transcript 中英文 partial 是否增长，FINAL 置信度是否显著低于中文。
3. 用 `tools/asr/decode_offline.py` 跑同一段 wav，判断模型上限。
4. 用 `tools/asr/decode_streaming.py` 模拟 100ms chunk + endpoint，判断实时配置问题。
5. 对比 greedy / modified_beam_search / +10dB / 不同 endpoint 参数。

示例：

```bash
python3 tools/asr/decode_streaming.py \
  --model-dir tools/asr/demo-model/zipformer_L_zh_en \
  --wav /tmp/asr-dump/2026-05-13_144818/audio.wav \
  --segments 0:8:en1 8:16:en2 \
  --gain 10 \
  --decoders greedy mbs8
```

## 后续优化建议

| 优先级 | 建议 | 说明 |
| --- | --- | --- |
| P0 | manifest 默认 modified_beam_search + max_active_paths=8 | 英文改善最明显 |
| P0 | sample / 业务录音层加可配置软增益 | +10dB 是当前设备实测合适值 |
| P1 | endpoint rule2 调到 2.0-2.5s | 减少英文短停顿切分 |
| P1 | 录音层输出 RMS 指标 | 线上问题可快速判断是否低电平 |
| P2 | 对比 VOICE_RECOGNITION 和 MIC | MIC 可能保留更多高频，但噪声也会更多 |
| P2 | SDK 内置可选 AGC | 量产前要验证 clipping 和噪声放大 |

