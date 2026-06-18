# Android ASR Session Dump 使用说明

本文说明 Android sample 中的调试落盘工具：把一次「开始识别 -> 停止识别」期间的音频和 ASR 事件保存下来，用于复现和分析线上问题。

## 目标

README 只说明如何接入和运行 sample；dump 工具用于回答更细的问题：

- 麦克风是否真的录到了开头？
- 识别为空时，wav 中有没有人声？
- 英文不出字是模型问题、解码问题、endpoint 问题，还是电平问题？
- STOP 时最后一段 partial 是否被 final 收住？

## 产物

每次 startListening 到 stopListening 生成一个目录：

```text
/sdcard/Android/data/com.amphion.asr.sample/files/asr-debug/<yyyy-MM-dd_HHmmss>/
├── audio.wav
└── transcript.txt
```

说明：

| 文件 | 内容 |
| --- | --- |
| audio.wav | mono / 16kHz / 16-bit PCM，RIFF WAV header 正常 |
| transcript.txt | ASR 事件流，带毫秒时间戳 |

transcript 示例：

```text
2026-05-13 14:48:18.348  SESSION_START
2026-05-13 14:48:20.476  PARTIAL  SUMMER HAS
2026-05-13 14:48:25.576  ENDPOINT
2026-05-13 14:48:25.576  FINAL  conf=0.23705132  SUMMER HAS COME AND PASSED
2026-05-13 14:49:43.066  SESSION_STOP
```

## 代码位置

| 文件 | 职责 |
| --- | --- |
| asr/android/sample/src/main/java/com/amphion/asr/sample/SessionRecorder.kt | 写 WAV + transcript |
| asr/android/sample/src/main/java/com/amphion/asr/sample/MainActivity.kt | PCM tee、callback 事件记录、STOP 时关闭 dump |
| asr/tools/decode_offline.py | PC 端一次性离线 decode dump wav |
| asr/tools/decode_streaming.py | PC 端模拟 Android streaming 行为 |

## 拉取 dump

```bash
adb devices -l

adb -s <SERIAL> pull \
  /sdcard/Android/data/com.amphion.asr.sample/files/asr-debug \
  /tmp/asr-dump
```

如果有多个无线调试通道，也可以用 transport id：

```bash
adb devices -l
adb -t <TRANSPORT_ID> pull \
  /sdcard/Android/data/com.amphion.asr.sample/files/asr-debug \
  /tmp/asr-dump
```

## 快速检查音频

用 Python 看 wav 格式和简单 RMS：

```bash
python3 - <<'PY'
import wave, struct, math, sys
path = sys.argv[1]
with wave.open(path, "rb") as w:
    n = w.getnframes()
    sr = w.getframerate()
    raw = w.readframes(n)
samples = struct.unpack("<" + "h" * n, raw)
print("duration_sec", n / sr)
step = sr // 2
for i in range(0, n, step):
    seg = samples[i:i+step]
    sq = sum(s*s for s in seg) / max(1, len(seg))
    db = -120 if sq <= 1 else 10 * math.log10(sq / (32768 * 32768))
    print(f"{i/sr:7.2f}s {db:8.2f} dBFS")
PY /tmp/asr-dump/asr-debug/2026-05-13_144818/audio.wav
```

经验值：

| RMS | 判断 |
| --- | --- |
| -70 dBFS 以下 | 基本是静音或底噪 |
| -55 到 -45 dBFS | Android VOICE_RECOGNITION 常见偏低人声 |
| -35 到 -25 dBFS | 更接近常见训练 / 测试音频电平 |

## 离线对照

安装依赖：

```bash
python3 -m pip install --user sherpa-onnx
```

一次性离线 decode：

```bash
python3 asr/tools/decode_offline.py \
  --model-dir asr/tools/demo-model/zipformer_L_zh_en \
  --wav /tmp/asr-dump/asr-debug/2026-05-13_144818/audio.wav \
  --segments 0:8:en1 8:16:en2 \
  --gains 0 10 \
  --decoders greedy mbs8
```

模拟 streaming：

```bash
python3 asr/tools/decode_streaming.py \
  --model-dir asr/tools/demo-model/zipformer_L_zh_en \
  --wav /tmp/asr-dump/asr-debug/2026-05-13_144818/audio.wav \
  --segments 0:8:en1 8:16:en2 \
  --gain 10 \
  --decoders greedy mbs8
```

## 判断方法

| 现象 | 判断 |
| --- | --- |
| audio.wav 开头有人声，transcript 前几秒 FINAL="" | streaming cold start 或 decoder blank |
| PC 离线能识别，Android streaming 不能 | endpoint / streaming / 增益 / decoding 配置问题 |
| PC 离线 +10dB 明显改善 | 录音电平偏低 |
| greedy 差，modified_beam_search 好 | BPE 链路对 greedy 过脆 |
| wav 中完全没人声 | 录音权限、AudioRecord、AudioSource 或设备问题 |
| STOP 前最后一条是 PARTIAL，没有 FINAL | STOP race；应等 onSessionStopped 后再关闭 dump |

## STOP race 的修复约定

SessionImpl.stop 是异步 drain。sample 不应在 stopListening 中立刻 close dump，否则最后一段 final 可能还没派发就被丢掉。

正确顺序：

1. stopListening 停止 AudioRecorder。
2. 调用 session.stop() 触发 decoder drain。
3. AsrCallback.onFinal 收到尾段 final 并写 transcript。
4. AsrCallback.onSessionStopped 写 SESSION_STOP 并 close dump。
5. close session。

这保证 transcript 中每个主动 STOP 的会话也有 FINAL 收尾。

