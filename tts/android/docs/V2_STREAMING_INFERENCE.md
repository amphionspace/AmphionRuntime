# V2 流式推理方案与优化方向

本文只说明当前 v2 TTS 流式推理的大致处理方式，以及后续为了降低手机端首包时延和 RTF 可以优先优化的方向。不展开 SDK 内部代码细节。

## 1. 当前 v2 使用的模型

当前 v2 使用的是 streaming proto 模型包：

```text
lits_delivery_16k_hifigan_streaming_proto / 0.1.1
```

核心组件：

```text
lits_hidden_encoder.onnx
lits_stream_decoder_chunk.onnx
hifigan_vocoder_int8.onnx
```

关键参数：

```text
sample_rate = 16000
hop_length = 256
chunk_size = 100
lookahead = 3
mel_cache = 8
vocoder = int8 HiFi-GAN
decoder = FP32 chunk decoder
```

如果要全程使用 100 帧 chunk，需要确保运行参数里：

```text
streamingFirstChunkSize = 100
streamingChunkSize = 100
```

否则 sample 里可能仍使用首块 50、后续 100 的配置。

## 2. 当前流式处理方式

当前流式方案可以理解成三段：

```text
文本 -> hidden encoder -> chunk decoder -> vocoder -> PCM
```

### 2.1 文本前端

输入文本先经过前端，转成 token ids。

这一步仍是首包路径的一部分，也就是说首包要等文本前端完成后才能继续往下跑。

### 2.2 Hidden Encoder

hidden encoder 一次性处理完整 token 序列，输出整句的 hidden/mel 条件：

```text
token ids -> mu_y / y_mask / mel_length / speaker_embedding
```

注意：当前 v2 不是从第一个字开始就逐字进入 decoder。它仍然需要先对完整文本跑一次 hidden encoder。

因此，首包时延里一定包含：

```text
文本前端耗时 + hidden encoder 耗时
```

### 2.3 Chunk Decoder

hidden encoder 输出后，decoder 按 mel 帧切 chunk。

全程 `chunk=100` 时，chunk 起点大致是：

```text
0, 100, 200, 300, ...
```

每个 chunk 推理时会带一点上下文：

```text
上一段上下文 + 当前 chunk + lookahead
```

当前 `lookahead=3`，表示非最终 chunk 会多看 3 帧未来信息，用来减轻边界问题。

最终 chunk 不再使用单独的 final decoder，而是给 chunk decoder 追加 3 帧 zero lookahead：

```text
final chunk + zero lookahead -> chunk decoder
```

这减少了一个 ONNX session，也简化了包体。

### 2.4 Vocoder 与边界平滑

decoder 输出 mel 后，进入 HiFi-GAN vocoder 生成 waveform。

为了减少 chunk 边界断裂，vocoder 输入会拼接上一 chunk 末尾的 mel cache：

```text
上一 chunk 末尾 8 帧 mel + 当前 mel chunk -> vocoder
```

waveform 侧也会在边界做 crossfade：

```text
mel_cache = 8
hop_length = 256
overlap = 8 * 256 = 2048 samples
```

也就是说，当前方案已经做了基础的边界平滑，但它不是严格的 stateful vocoder/decoder cache，所以边界仍可能有接缝。

## 3. 当前方案的性能含义

### 3.1 首包时延由什么决定

首包时延大致由这些部分组成：

```text
文本前端
+ hidden encoder
+ 第一个 chunk decoder
+ 第一个 chunk vocoder
+ PCM 转换和回调/入队开销
```

所以要降低首包，重点不是只看 vocoder。前端和 hidden encoder 也很关键。

### 3.2 RTF 由什么决定

RTF 主要由整句合成耗时和音频时长决定：

```text
RTF = synthesis_time / audio_duration
```

当前主要耗时来自：

```text
hidden encoder
多次 chunk decoder
多次 vocoder
```

对长句来说，decoder/vocoder chunk 次数越多，总耗时越高。

### 3.3 RTF 小于 1 不代表没有断点

如果手机上：

```text
RTF ~= 0.7
首包 ~= 1s
```

通常说明平均合成速度是赶得上播放的，不太像是 PCM 播放队列 underrun。

如果这时仍听到断点，更可能是：

```text
chunk 边界音频不连续
vocoder cache/crossfade 不够平滑
Android AudioTrack 写入/播放链路有顿挫
```

## 4. Python 版本怎么对应当前方案

本机 Python 脚本用于复现 v2 ONNX 流式链路：

```text
LitsTtsSdk/tools/run_v2_streaming_onnx_breakpoints.py
```

它做的事情和 Android v2 推理逻辑对齐：

```text
hidden encoder
chunk decoder
zero-lookahead final
mel cache
vocoder
waveform crossfade
PCM queue/drain 模拟
```

常用命令：

```bash
/Users/amphion/Documents/Lits_delivery/.venv/bin/python \
  LitsTtsSdk/tools/run_v2_streaming_onnx_breakpoints.py \
  --case-index 2 \
  --repeat-case 4 \
  --chunk-size 100 \
  --pcm-queue-capacity 128 \
  --producer-time-scale 4.2 \
  --trace
```

输出：

```text
*_continuous.wav
*_underrun_playback.wav
*_metrics.json
```

含义：

- `continuous.wav`：直接拼接流式 chunk，用来看模型边界本身是否平滑。
- `underrun_playback.wav`：只有模拟发现播放 underrun 时才插入真实缺口静音。
- `metrics.json`：记录每个 chunk 的 decoder/vocoder/ready/playback 时间。

目前按手机 `RTF ~= 0.7` 估算，`producer-time-scale=4.2` 时没有 underrun，因此手机断点更可能不是“合成赶不上输出”造成的。

## 5. 可以优先优化的方向

目标是降低：

```text
首包时延
RTF
chunk 边界断点感
```

### 5.1 降低首包时延

优先级 1：减少首包必须等待的前端和 hidden encoder 时间。

可尝试：

```text
1. 文本切分后分段跑前端和 hidden encoder
2. 首段先出音，后续段异步继续处理
3. 缓存常用前端资源，减少每次 encode 的额外开销
4. 对短句和长句使用不同切分策略
```

当前 v2 仍然对完整文本先跑 hidden encoder。长文本时，这会拖高首包。

### 5.2 减小第一块计算量

如果只看首包，可以考虑：

```text
首块 chunk = 50
后续 chunk = 100
```

优点：

- 首包 decoder/vocoder 工作量更小。
- 首包可能更快。

缺点：

- 边界数量可能增加。
- 后续 chunk 计划更复杂。
- 第一块太短可能影响开头稳定性。

如果当前目标是极限降低首包，可以重新测试首块 50；如果目标是边界更稳定，全程 100 更简单。

### 5.3 优化 hidden encoder

hidden encoder 是首包必经路径。

可尝试：

```text
1. ONNX graph 优化或重新导出
2. FP16 / int8 / weight-only 量化实验
3. Android NNAPI / XNNPACK / 其他 EP 尝试
4. 控制线程数，避免手机上 CPU 抢占和发热
5. 对长文本做分段 hidden encoder，避免首包等完整文本
```

注意：之前 decoder int8 实验有质量漂移风险；hidden encoder 量化也必须做音质回归。

### 5.4 优化 chunk decoder

当前 decoder 仍是 FP32。

可尝试：

```text
1. 导出真正 stateful decoder cache
2. 避免每个 chunk 重算 previous chunk 上下文
3. 尝试更轻量的 decoder
4. 做有约束的量化，例如只量化部分 MatMul/Conv
5. 调整 chunk/window 策略，减少重复计算
```

当前方案每个 chunk 使用局部窗口：

```text
previous + current + lookahead
```

这比全前缀重算好，但仍有重复计算。真正的 stateful cache 是更根本的优化方向。

### 5.5 优化 vocoder

v2 已经使用 int8 vocoder，这是降低 RTF 和包体的主要优化之一。

还可以尝试：

```text
1. 更轻量 vocoder
2. 更适合移动端的量化方案
3. XNNPACK / NNAPI 加速
4. 调整 mel_cache 和 crossfade 长度
5. 检查 int8 vocoder 是否放大 chunk 边界 artifact
```

如果断点主要在边界，可能不是 vocoder 平均速度问题，而是 vocoder 的边界连续性问题。

### 5.6 优化 chunk 边界

如果 `continuous.wav` 本身在边界有接缝，应优先查：

```text
1. mel 边界是否突变
2. waveform 边界 sample jump 是否过大
3. crossfade 2048 samples 是否足够
4. mel_cache=8 是否太短
5. lookahead=3 是否太小
6. int8 vocoder 是否让边界更明显
```

可实验：

```text
mel_cache: 8 -> 12 / 16
lookahead: 3 -> 5 / 8
crossfade window: Hamming -> Hann / equal-power
vocoder: int8 -> FP32 对比边界
```

代价：

- 更大的 mel cache/lookahead 会增加 vocoder 或 decoder 工作量。
- 可能降低断点感，但提高 RTF。

### 5.7 优化 Android 播放链路

如果：

```text
SYNTHESIZE_ONLY 保存的 wav 是平滑的
SYNTHESIZE_AND_PLAY 听起来有顿挫
```

则优先查播放链路。

可尝试：

```text
1. 增大 AudioTrack buffer size，而不是只用 minBufferSize
2. 调整 PCM queue capacity
3. 让播放线程优先级更高
4. 减少 UI log 刷新频率
5. 避免在播放时做大量主线程更新
6. 打印每次 AudioTrack.write 的耗时和 written bytes
```

当前 `pcmQueueCapacity=128` 理论上足够大。如果 RTF 0.7 仍断，优先怀疑边界或 AudioTrack 行为，而不是 queue 容量。

## 6. 推荐下一步实验顺序

建议按下面顺序排查和优化：

```text
1. 在 Python 上听 continuous.wav
   如果已有断点，先优化模型 chunk 边界。

2. 在 Android 上用 SYNTHESIZE_ONLY 保存 WAV
   如果保存 WAV 有断点，说明 Android 推理输出本身有问题。

3. 对比 vocoder int8 和 FP32
   看断点是否由 int8 vocoder 放大。

4. 调 mel_cache/lookahead
   先试 mel_cache=12 或 16，再试 lookahead=5。

5. 如果 WAV 平滑但直接播放断
   再查 AudioTrack buffer、write 耗时、线程调度。

6. 为首包优化单独做 firstChunk=50 实验
   对比首包、RTF、边界听感。

7. 中长期做 stateful decoder cache
   减少重复计算，是降低 RTF 的更根本方向。
```

## 7. 重点结论

当前 v2 已经是流式，但不是完全 stateful streaming。

它的核心策略是：

```text
完整文本先跑 hidden encoder
decoder 按 chunk 局部窗口推理
vocoder 用 mel cache + waveform crossfade 平滑边界
Android 播放时用 PCM queue + AudioTrack drain
```

降低手机首包时延，优先看：

```text
文本前端
hidden encoder
第一块 decoder/vocoder 工作量
```

降低 RTF，优先看：

```text
decoder 重复计算
vocoder 性能
移动端执行后端
线程和发热
```

减少听感断点，优先看：

```text
chunk 边界 mel/waveform 连续性
mel_cache/lookahead/crossfade
int8 vocoder 对边界的影响
Android AudioTrack 播放链路
```
