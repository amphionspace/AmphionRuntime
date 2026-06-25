# Amphion HarmonyOS 鼎桥交付聚合层

本目录是面向鼎桥客户的纯血鸿蒙交付聚合层，本身不包含 SDK 源码，只整合：

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

# 3) 用 DevEco Studio 打开本目录 delivery/harmony-dingqiao/，构建 dingqiao_demo HAP
#    （会自动按 file: 依赖构建 asr/harmony 与 tts/harmony 的 HAR）
```

## 交付打包

```bash
bash delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh
```

脚本只收集已构建产物（HAR/HAP/模型/文档），不负责启动 DevEco 构建。

## main 分支复现边界

PR 合入后，`main` 分支包含完整源码、交付工程和 sherpa-onnx patch 序列，可以在同样工具链下编译出功能等价的鸿蒙应用。但仓库不会提交模型、签名证书、license、HAP/HAR 或 native 构建产物，因此干净检出后不能只运行 DevEco 构建就得到已签名的 279 MB HAP。

从干净 `main` 复现时需要先准备这些本地输入：

- 执行 `git submodule update --init third_party/sherpa-onnx`。
- 执行 `bash asr/tools/04_build_harmony_so.sh`；该脚本会调用 `asr/tools/apply_sherpa_patches.sh`，把 `third_party/patches/sherpa-amphion/` 下的 patch 应用到 sherpa-onnx，本分支不提交 submodule 本体改动。
- 执行 `bash asr/tools/08_pack_harmony_assets.sh`；前提是 `asr/android/sdk/src/main/assets/amphion-models/` 下已有 ASR 模型源文件。
- 配置 DevEco 签名后构建 `dingqiao_demo`；无签名配置时只能得到未签名或调试产物。
- 声纹模型 `eres2net.onnx` 不内置进 HAP，由 demo 通过导入流程放入工作目录。

在相同模型、签名和 SDK 环境下，`main` 可以编译出功能一致的应用；但 HAP 二进制不承诺字节级一致，签名、时间戳和构建元数据都会影响 hash。
