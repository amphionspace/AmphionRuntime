# Amphion Runtime HarmonyOS ASR SDK

本目录承载纯血鸿蒙（HarmonyOS NEXT / OpenHarmony）原生 ASR SDK，不依赖 Android 兼容层。

对齐 Android 鼎桥交付包的识别能力：

- `sdk/`：核心 ASR HAR（模块名 `amphion_asr`），映射 `AmphionRuntime`、`AsrEngine`、`AsrSession` 等语义。
- `sdk-police/`：警务增强 HAR（`amphion_police`），映射术语、车牌、派出所 final 后处理。
- `sdk-dingqiao/`：鼎桥接口 HAR（`amphion_dingqiao`），映射 `SpeechRecognizeSdk` 契约。

当前工程使用上游 `sherpa_onnx` HarmonyOS HAR 作为 ASR/VAD/标点 NAPI 绑定基础；`WetextItn`、license 与声纹会在 Amphion 专用 NAPI 层补齐。

## Native 产物

纯血鸿蒙不能复用 Android `.so`。请先执行：

```bash
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
```

模型资源按 Android bundle 布局放入：

```text
asr/harmony/sdk/src/main/resources/rawfile/amphion-models/
```

可通过脚本同步：

```bash
bash asr/tools/08_pack_harmony_assets.sh
```

## 相关目录

- TTS 鸿蒙 SDK：`tts/harmony/`（模块名 `amphion_tts`）。
- 统一客户交付聚合层（同时演示 ASR + TTS 的 HAP demo、交付文档与打包脚本）：`delivery/harmony-dingqiao/`。
