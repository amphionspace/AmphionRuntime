# Amphion TTS HarmonyOS 集成指南

适用范围：HarmonyOS NEXT / OpenHarmony 原生应用，离线合成。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| DevEco Studio | 5.x |
| HarmonyOS SDK | 5.x，Stage 模型 |
| Native | OHOS NDK arm64-v8a（与 ASR 共用 sherpa_onnx native） |
| 模块 | `amphion_tts` HAR |

## 准备 native 与模型

```bash
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
bash tts/tools/harmony/pack_harmony_tts_assets.sh
```

## API

```ts
import {
  PlayType,
  RunMode,
  SpeakParams,
  TextToSpeechEngine,
  TextToSpeechSdk,
  TtsCreateEngineParams
} from 'amphion_tts';

TextToSpeechSdk.init(context);

const params = new TtsCreateEngineParams();
params.language = 'zh-en';
params.mode = RunMode.OFFLINE;
params.voiceId = 'kokoro-zh-en';

const engine: TextToSpeechEngine = TextToSpeechSdk.createEngine(params);
engine.setListener({
  onStart: (requestId: string) => {},
  onData: (requestId: string, audio: ArrayBuffer) => {},
  onComplete: (requestId: string) => {},
  onError: (requestId: string, code: number, message: string) => {}
});

const speak = new SpeakParams();
speak.requestId = 'req-1';
speak.playType = PlayType.SYNTHESIZE_ONLY;
engine.speak('请核查接警数据。', speak);
```

## 音频输出

| 项目 | 值 |
| --- | --- |
| 格式 | PCM S16LE |
| 采样率 | 模型采样率（Kokoro 为 24000 Hz） |
| 声道 | 1 |
| 回调 | `onData` 逐块返回 PCM；合成结束回调 `onComplete` |

`onData` 始终逐块回调合成 PCM，业务方可自行落盘或转发。`PlayType` 控制是否同时内置播放：

| playType | 行为 |
| --- | --- |
| SYNTHESIZE_ONLY | 仅通过 `onData` 输出 PCM，不播放 |
| SYNTHESIZE_AND_PLAY | `onData` 输出 PCM，同时用 `AudioRenderer` 内置播放 |

内置播放使用 `STREAM_USAGE_MUSIC` 的 `AudioRenderer`，采样率取模型输出采样率（Kokoro 为 24000 Hz），通过 `writeData` 拉模型从 `CircularBuffer` 取样，合成结束且缓冲放完后自动停止。

## 已知差异

| 能力 | 状态 |
| --- | --- |
| 离线合成 | 走上游 `sherpa_onnx.OfflineTts`（Kokoro / VITS / Matcha） |
| 内置播放 | `SYNTHESIZE_AND_PLAY` 已用 `AudioRenderer`（writeData 拉模型 + `CircularBuffer`） |
| license | 已保留 `init` 入口，正式包注入鸿蒙公钥验签 |
