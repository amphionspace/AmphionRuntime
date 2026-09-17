# Android SDK 源码编译说明

本文说明如何从 AmphionRuntime 当前代码编译 Dingqiao v3 TTS Android SDK AAR。目标产物是：

```text
tts/android/sdk/build/outputs/aar/sdk-release.aar
```

当前 Android AAR 包含 SDK 代码、`liblits_tn.so`、ONNX Runtime JNI 库、播放实现，以及模型和前端资源。Gradle 从模型目录生成 `build/generated/tts-assets/` 后打入 AAR，APK 自动继承资源；不需要单独 TN 可执行文件。

## 1. 获取源码

TN（文本归一化）源码、规则和测试已直接纳入本仓库，普通克隆即可获取：

```bash
git clone <AmphionRuntime-url>
cd AmphionRuntime
```

协作者无需原 TN 私有仓库权限；来源版本见
[TN_SOURCE.md](../../training/TN_SOURCE.md)。源码目录为：

```text
tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS/
```

Android JNI 会从这个目录编译 `liblits_tn.so`，Gradle 也会从这里同步 `rules_v2` 和拼音映射文件。

## 2. 准备本机环境

需要本机已有：

- JDK 17
- Android SDK
- Android NDK，推荐 `27.2.12479018`
- Python 3
- 仓库自带的 Gradle Wrapper：`tts/android/gradlew`

不要在构建脚本里临时下载 JDK、Gradle 或 Android 构建工具。CI 或交付机应显式设置：

```bash
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk
export ANDROID_SDK_ROOT=/path/to/android-sdk
export ANDROID_NDK=$ANDROID_HOME/ndk/27.2.12479018
```

也可以在 `tts/android/local.properties` 写入 Android SDK 路径：

```properties
sdk.dir=/path/to/android-sdk
```

## 3. 准备模型包

构建消费的是已经导出的模型包，不需要 checkpoint，也不需要重新导出 ONNX。把模型包放在仓库根目录下：

```text
tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
```

当前 Dingqiao v3 分支使用单 decoder / final-zero 导出包。至少应包含：

- `manifest.json`
- `lits_hidden_encoder.onnx`
- `lits_stream_condition_chunk.onnx`
- `lits_stream_decoder_step.onnx`
- `vocos_vocoder.onnx`
- `frontend_golden.json`
- `frontend_rules.json`
- `chinese_lexicon.txt`
- `cmudict.txt`
- `supplement_lexicon.json`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`
- `rules_v2/zh.full.json`
- `rules_v2/en.full.json`
- `rules_v2/zh_pinyin.json`

不再需要 `lits_stream_condition_final.onnx`。`manifest.json` 应包含：

```json
"stream_final_zero_pad_with_chunk_condition": true
```

OBS 模型包已经包含校验过的前端 `.bin`。Gradle 会以只读方式同步这些资源，并把运行时需要的外部资源整理到：

```text
tts/android/build/generated/tts-assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
```

该目录可随时由 `tts/tools/trial-export/...` 重建，已被 Git 忽略，不应作为源资产编辑或提交。

宿主集成时无需手动复制资源，SDK 首次创建引擎时自动解包到 `<workPath>/tts/...`。Android 当前使用 AAR 内的 native TN/JNI，外部资源目录不需要携带 `tn-bin/arm64-v8a/zh_tts` 或 `tn-bin/arm64-v8a/en_tts`。

## 4. 构建 Android ICU 和 native TN

Android 运行时通过 AAR 内的 `liblits_tn.so` 调用 native TN，不再要求外部资源携带 `zh_tts` / `en_tts` 可执行文件。若需要从源码重建 Android ICU 依赖和 native TN 构建输入，准备 ICU 源码压缩包后执行：

```bash
ANDROID_NDK=/path/to/android-sdk/ndk/27.2.12479018 \
ICU_SOURCE_ARCHIVE=/path/to/icu4c-78.1-sources.tgz \
tts/tools/tn/build_dingqiao_android_native.sh
```

脚本会使用当前仓库里的 TN 源码目录，不依赖任何兄弟目录或本机私有源码路径。默认输出：

```text
tts/training/dingqiao_lits/build/android-icu/
```

Android CMake 会从 `tts/training/dingqiao_lits/build/android-icu/` 读取 ICU 头文件和静态库来编译 `liblits_tn.so`。

## 5. 编译 AAR

进入 Android 工程目录：

```bash
cd tts/android
```

执行：

```bash
JAVA_HOME=/path/to/jdk-17 \
ANDROID_HOME=/path/to/android-sdk \
ANDROID_SDK_ROOT=/path/to/android-sdk \
./gradlew --no-daemon :sdk:assembleRelease
```

成功后检查：

```bash
ls -lh sdk/build/outputs/aar/sdk-release.aar
find build/generated/tts-assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0 -maxdepth 3 -type f
```

## 6. 期望产物

- AAR：`tts/android/sdk/build/outputs/aar/sdk-release.aar`
- AAR 内置资源的构建暂存目录：`tts/android/build/generated/tts-assets/lits-models/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/`

AAR 应包含：

- `classes.jar`
- `jni/arm64-v8a/liblits_tn.so`
- ONNX Runtime JNI 动态库

AAR 不应包含：

- `.onnx`
- `assets/lits-models`
- `chinese_lexicon.txt` / `cmudict.txt`
- `.lic`

## 7. 常见问题

- TN 源码目录为空：确认已检出包含 TN 源码迁入的版本；该目录由本仓库直接跟踪。
- 找不到 Android SDK：设置 `ANDROID_HOME` / `ANDROID_SDK_ROOT`，或写 `tts/android/local.properties`。
- 找不到 ICU 头文件或静态库：先运行 `tts/tools/tn/build_dingqiao_android_native.sh`，或确认 `tts/training/dingqiao_lits/build/android-icu/` 已存在。
- 运行时报缺少资源：检查 AAR/APK 中 `assets/lits-models/tts/` 是否完整，确认模型构建目录及 manifest。已有外置模型仍优先使用。
- 不要提交 `external-resources/`、`build/`、签名文件、license 包或本地 `local.properties`。
