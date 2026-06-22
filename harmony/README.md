# Amphion HarmonyOS 统一交付聚合层

本目录是面向客户的纯血鸿蒙交付聚合层，本身不包含 SDK 源码，只整合：

- `samples/dingqiao-demo/`：验收 HAP，同时演示 ASR（鼎桥接口）与 TTS。
- `docs/`：集成、授权、隐私、NOTICE 与交付 SOP。
- `delivery/`：客户交付包打包脚本。

SDK 源码分别在：

- `asr/harmony/`：ASR HAR（`amphion_asr` / `amphion_police` / `amphion_dingqiao`）。
- `tts/harmony/`：TTS HAR（`amphion_tts`）。

demo 通过 `oh-package.json5` 的 `file:` 相对路径跨工程引用上述四个 HAR，与仓库内引用上游 `sherpa_onnx` HAR 的方式一致。

## 构建顺序

```bash
# 1) 共享 native（ASR + TTS 共用同一套 sherpa_onnx .so）
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh

# 2) 模型资源
bash asr/tools/08_pack_harmony_assets.sh          # ASR 模型 -> asr/harmony
bash tts/tools/harmony/pack_harmony_tts_assets.sh # TTS 模型 -> tts/harmony（可选）

# 3) 用 DevEco Studio 打开本目录 harmony/，构建 dingqiao_demo HAP
#    （会自动按 file: 依赖构建 asr/harmony 与 tts/harmony 的 HAR）
```

## 交付打包

```bash
bash harmony/delivery/pack_dingqiao_harmony_customer_delivery.sh
```

脚本只收集已构建产物（HAR/HAP/模型/文档），不负责启动 DevEco 构建。
