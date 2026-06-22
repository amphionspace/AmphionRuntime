# Amphion Runtime HarmonyOS 集成指南

适用范围：HarmonyOS NEXT / OpenHarmony 原生应用，不适用于 Android APK 兼容层。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| DevEco Studio | 5.x |
| HarmonyOS SDK | 5.x，Stage 模型 |
| Native | OHOS NDK arm64-v8a |
| 设备 | 纯血鸿蒙真机，arm64 |
| 权限 | `ohos.permission.MICROPHONE` |

## 模块

| 模块 | 作用 |
| --- | --- |
| `amphion_asr` | 核心 ASR HAR |
| `amphion_police` | 警务增强 HAR |
| `amphion_dingqiao` | 鼎桥接口 HAR |

验收 HAP（`dingqiao_demo`，同时演示 ASR + TTS）位于仓库顶层 `harmony/samples/dingqiao-demo`。

## 准备 native 与模型

```bash
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
bash asr/tools/08_pack_harmony_assets.sh
```

## 通用 ASR API

```ts
import { AmphionRuntime, AsrConfig, AsrLanguage } from 'amphion_asr';

AmphionRuntime.init(context);
const engine = AmphionRuntime.create(context, AsrLanguage.ZH_EN, new AsrConfig());
const session = engine.newSession({
  onPartial: (text: string) => {},
  onFinal: (text: string, confidence: number) => {},
  onError: (error) => {}
});
session.acceptPcmShort(pcm16kMono);
session.stop();
```

SDK 不接管录音，业务方需自行使用 `AudioCapturer` 获取 16 kHz、16-bit、mono PCM。

## 指标与日志

指标 schema 与 Android 版一致，通过 `AsrCallback.onMetrics` 和控制台日志输出，tag 文本为 `AmphionMetrics`。

## 已知差异

| 能力 | 状态 |
| --- | --- |
| ASR / VAD / 标点 | 走上游 `sherpa_onnx` HAR |
| ITN | 已保留接口，需 Amphion Wetext NAPI 完成后启用 |
| 声纹 | 已保留注册/删除接口，native embedding 接入后替换占位实现 |
| license | 已保留鸿蒙 bundleName 绑定结构，正式验签需交付期注入公钥 |

## TTS

离线 TTS 已拆分为独立 SDK，见 `tts/harmony/`（模块名 `amphion_tts`）与 `tts/harmony/docs/INTEGRATION.md`。
