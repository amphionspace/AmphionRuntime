# Android SDK 源码编译说明

本文说明如何从 AmphionRuntime 当前代码编译 Dingqiao v3 TTS Android SDK AAR。目标产物是：

```text
tts/android/sdk/build/outputs/aar/sdk-release.aar
```

当前 Android AAR 只包含 SDK 代码、`liblits_tn.so`、ONNX Runtime JNI 库和播放实现；ONNX 模型、前端资源和 TN 可执行文件会被整理到 `external-resources/`，不再打进 AAR。

## 1. 获取源码和 submodule

首次克隆建议直接带上 submodule：

```bash
git clone --recurse-submodules <AmphionRuntime-url>
cd AmphionRuntime
```

如果已经克隆过仓库，进入仓库根目录后执行：

```bash
git submodule update --init --recursive
```

必须存在以下 TN submodule：

```text
tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS/
```

Android JNI 会从这个 submodule 编译 `liblits_tn.so`，Gradle 也会从这里同步 `rules_v2` 和拼音映射文件。

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
tts/android/external-resources/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
```

该目录可随时由 `tts/tools/trial-export/...` 重建，已被 Git 忽略，不应作为源资产编辑或提交。

宿主集成时需要把这个 `external-resources/tts/...` 目录复制到 SDK 工作目录，使运行时能看到 `<workPath>/tts/...`。Android 当前使用 AAR 内的 native TN/JNI，外部资源目录不需要携带 `tn-bin/arm64-v8a/zh_tts` 或 `tn-bin/arm64-v8a/en_tts`。

## 4. 构建 Android ICU 和 native TN

Android 运行时通过 AAR 内的 `liblits_tn.so` 调用 native TN，不再要求外部资源携带 `zh_tts` / `en_tts` 可执行文件。若需要从源码重建 Android ICU 依赖和 native TN 构建输入，准备 ICU 源码压缩包后执行：

```bash
ANDROID_NDK=/path/to/android-sdk/ndk/27.2.12479018 \
ICU_SOURCE_ARCHIVE=/path/to/icu4c-78.1-sources.tgz \
tts/tools/tn/build_dingqiao_android_native.sh
```

脚本会使用当前仓库里的 TN submodule，不依赖任何兄弟目录或本机私有源码路径。默认输出：

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
find external-resources/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0 -maxdepth 3 -type f
```

## 6. 期望产物

- AAR：`tts/android/sdk/build/outputs/aar/sdk-release.aar`
- 外部资源：`tts/android/external-resources/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/`

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

- `submodule` 目录为空：执行 `git submodule update --init --recursive`。
- 找不到 Android SDK：设置 `ANDROID_HOME` / `ANDROID_SDK_ROOT`，或写 `tts/android/local.properties`。
- 找不到 ICU 头文件或静态库：先运行 `tts/tools/tn/build_dingqiao_android_native.sh`，或确认 `tts/training/dingqiao_lits/build/android-icu/` 已存在。
- 运行时报缺少外部资源：把 `tts/android/external-resources/tts/...` 复制到宿主 SDK 工作目录下的 `tts/...`。
- 不要提交 `external-resources/`、`build/`、签名文件、license 包或本地 `local.properties`。
