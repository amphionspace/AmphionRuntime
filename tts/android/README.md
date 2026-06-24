# Lits TTS Android SDK

Lits TTS Android SDK 是一套最小 Android 源码构建入口，用来从源码构建离线端侧语音合成 AAR。对协作者来说，如果目标只是重建 `:sdk`，只需要关心这里的 `sdk/`、Gradle 配置、`tools/` 下的模型包目录和文档；仓库中其他历史目录可以忽略。

下面统一用 `LitsTtsSdk 根目录` 指代你把这份源码放到本机后的那个目录，例如：

```text
D:\work\LitsTtsSdk
```

下文的路径和命令默认按 Windows 写；如果你在 macOS 或 Linux 上构建，请把路径分隔符和 `gradlew.bat` 替换成各自平台的等价形式。

## 当前版本

| 项 | 值 |
| --- | --- |
| SDK 版本 | `0.1.0` |
| 模型 ID | `lits_delivery_16k_hifigan` |
| 模型版本 | `1.0.0` |
| 支持语种 | `zh-en`, `en-US` |
| 输出格式 | `pcm`, 16000 Hz, 16-bit, mono |
| Android minSdk | 24 |
| ABI | `arm64-v8a` |

## 文档导航

- 从源码构建 SDK：[docs/DELIVERY.md](docs/DELIVERY.md)
- 宿主 App 接入 AAR：[docs/INTEGRATION.md](docs/INTEGRATION.md)
- 公开接口说明：[docs/API.md](docs/API.md)
- 伪代码与调用顺序：[docs/PSEUDOCODE.md](docs/PSEUDOCODE.md)

## 源码构建快速开始

1. 从源码交接方单独获取完整模型包
2. 放到下面这个固定目录：

```text
LitsTtsSdk\tools\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

如果你的 `LitsTtsSdk 根目录` 是 `D:\work\LitsTtsSdk`，那么真实放置位置就是：

```text
D:\work\LitsTtsSdk\tools\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

3. 让 Gradle 能找到本机 Android SDK：

- 在 `local.properties` 写 `sdk.dir=...`
- 或设置 `ANDROID_HOME` / `ANDROID_SDK_ROOT`

4. 打开终端进入 `LitsTtsSdk 根目录\android\AmphionRuntime\`，然后在当前目录执行：

```powershell
python ..\..\tools\verify_lits_delivery_16k_package.py --model-dir ..\..\tools\trial-export\lits_delivery_16k_hifigan\1.0.0
.\gradlew.bat :sdk:testDebugUnitTest
.\gradlew.bat :sdk:assembleRelease
```

5. 构建输出位于：

```text
sdk/build/outputs/aar/sdk-release.aar
```

注意：模型文件只需要放到 `tools/trial-export/...`，不要手动放到 `sdk/src/main/assets/...`；Gradle 会在 `preBuild` 阶段自动同步。

完整步骤、输入文件清单、自检方式与常见报错见 [docs/DELIVERY.md](docs/DELIVERY.md)。

## 模型包说明

源码构建直接消费已经导出的 ONNX 模型包，不要求 checkpoint，也不要求执行任何导出脚本。最少需要以下文件：

- `manifest.json`
- `lits_acoustic.onnx`
- `hifigan_vocoder.onnx`
- `smoke_tokens.json`
- `frontend_golden.json`
- `chinese_lexicon.txt`
- `cmudict.txt`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`

Gradle 会在 `preBuild` 阶段自动把它们同步到：

```text
sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/
```

这个目录是构建时自动生成/同步的目录，不是你手工投放模型的地方。

## 运行时说明

- `createEngine(params, callback)` 和 `listVoices(params, callback)` 是异步接口；Android 环境下 callback 回到主线程
- 同步版 `createEngine(params)` 会在当前线程完成模型加载，调用方应自行放到后台线程
- `SpeakListener` 的 `onStart/onData/onComplete/onStop/onError` 为 SDK 内部异步派发；更新 UI 时需要切回主线程

## 已验证范围

当前工程已验证以下源码构建链路：

- `:sdk:testDebugUnitTest`
- `:sdk:assembleRelease`

