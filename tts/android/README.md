# Lits TTS Android SDK

Lits TTS Android SDK 用于构建离线端侧语音合成 AAR。当前 Android v2 交付目标是 Transsion LITS 英中/中文混合模型，Vocos 24 kHz 流式声码器，模型随 AAR 内置，宿主 App 不需要联网下载模型。

## 当前版本

| 项 | 值 |
| --- | --- |
| SDK 版本 | `0.1.0` |
| 模型 ID | `transsion_lits_en_zh_vocos24k_streaming_proto` |
| 模型版本 | `0.1.0` |
| 声码器 | `vocos` |
| 支持语种 | `zh-en`, `en-US` |
| 输出格式 | `pcm`, 24000 Hz, 16-bit, mono |
| Android minSdk | 24 |
| ABI | `arm64-v8a` |

## 工程内容

- `sdk/`：Android Library 模块，产出最终 AAR。
- `sample/`：可安装验证 App，集成 `:sdk` 并提供合成、播放、保存 WAV 和流式首包指标展示。
- `docs/`：构建、接入、API、授权、伪代码说明。
- `gradle/`、`build.gradle.kts`、`settings.gradle.kts`：Gradle 构建配置。
- `LICENSE`、`NOTICE`：许可证和第三方声明。

真实模型文件不放在 Git 中。构建前需要单独取得模型包。

## 文档导航

- 从源码构建 SDK：[docs/DELIVERY.md](docs/DELIVERY.md)
- 宿主 App 接入 AAR：[docs/INTEGRATION.md](docs/INTEGRATION.md)
- 公开接口说明：[docs/API.md](docs/API.md)
- 授权机制说明：[docs/LICENSE.md](docs/LICENSE.md)
- 伪代码与调用顺序：[docs/PSEUDOCODE.md](docs/PSEUDOCODE.md)

## 对外交付打包

从仓库根目录执行：

```bash
bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.1.0
```

脚本会构建 release AAR 和 sample APK，并在 `../delivery/lits-tts-android-sdk-v0.1.0/` 生成交付目录。交付包内包含：

- `aar/lits-tts-sdk-0.1.0.aar`
- `demo/lits-tts-sample-debug.apk`
- `android-src/TTS/` Android 源码快照，含本次构建使用的模型包
- `docs/` 集成、API、License 和 NOTICE 文档
- `VERSION.txt` git commit、branch、dirty 状态、模型 ID 等构建溯源

正式交付时工作区必须干净；本地预览可设置 `LITS_TTS_ALLOW_DIRTY=1`。

## 源码构建快速开始

1. 从交接方获取完整模型包。
2. 放到仓库根目录下：

```text
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/
```

3. 让 Gradle 能找到本机 Android SDK：在 `tts/android/local.properties` 写 `sdk.dir=...`，或设置 `ANDROID_HOME` / `ANDROID_SDK_ROOT`。

4. 进入 Android 工程并构建：

```bash
cd tts/android
python ../../tts/tools/verify_transsion_vocos24k_package.py --model-dir ../../tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug
```

5. 构建输出位于：

```text
sdk/build/outputs/aar/sdk-release.aar
sample/build/outputs/apk/debug/sample-debug.apk
```

模型文件只需要放到 `tools/trial-export/...`，不要手动放到 `sdk/src/main/assets/...`；Gradle 会在 `preBuild` 阶段自动同步。

## 模型包说明

源码构建直接消费已经导出的 ONNX/ORT 运行时模型包，不要求 checkpoint，也不要求执行导出脚本。最少需要以下 17 个文件：

- `manifest.json`
- `export_report.json`
- `vocos_vocoder.export_report.json`
- `frontend_golden.json`
- `chinese_lexicon.txt`
- `chinese_lexicon.bin`
- `cmudict.txt`
- `cmudict.bin`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`
- `lits_hidden_encoder.onnx`
- `lits_stream_decoder_chunk.ort`
- `lits_stream_decoder_final.ort`
- `vocos_vocoder.onnx`

Gradle 会在 `preBuild` 阶段自动把运行时需要的文件同步到：

```text
sdk/src/main/assets/lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/
```

这个目录是构建时自动生成的目录，不是手工投放模型的地方。

## 运行时说明

- `TextToSpeechSdk.init(context, options)` 是可选显式授权初始化；未调用时，`createEngine` 会在 Android 环境下懒校验一次。
- `createEngine(params, callback)` 和 `listVoices(params, callback)` 是异步接口；Android 环境下 callback 回到主线程。
- 同步版 `createEngine(params)` 会加载模型，调用方应放到后台线程。
- `SpeakListener` 的 `onStart/onData/onComplete/onStop/onError` 为 SDK 内部异步派发；更新 UI 时需要切回主线程。

## 已验证范围

- `:sdk:testDebugUnitTest`
- `:sdk:assembleRelease`
- `:sample:assembleDebug`
- sample APK 真机安装
