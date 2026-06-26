# TTS Android / HarmonyOS SDK 交付与编译说明

本文面向接手 TTS SDK 的同事，说明需要交付哪些内容、模型文件放在哪里，以及如何从源码编译 Android AAR 和 HarmonyOS HAR。

下面统一用 `AmphionRuntime 根目录` 指代仓库根目录，例如：

```text
D:\work\AmphionRuntime
```

当前代码分支：

```text
tts-android-harmony-v2.4
```

## 1. 交付内容

需要交付三类内容：

1. 源码分支

```text
git@github.com:amphionspace/AmphionRuntime.git
branch: tts-android-harmony-v2.4
```

源码里包含：

```text
tts/android/    Android TTS SDK 工程
tts/harmony/    HarmonyOS TTS SDK 工程
tts/tools/      TTS 相关工具和说明
docs/           仓库级说明文档
```

2. 模型包

模型包不进 Git，需要单独交付。当前 Android 和 HarmonyOS 使用的模型目录不同，必须分别放到固定位置：

```text
AmphionRuntime 根目录/
└── tools/
    └── trial-export/
        ├── lits_delivery_16k_hifigan_streaming_proto/
        │   └── 0.1.1/        Android 使用
        └── lits_delivery_16k_hifigan/
            └── 1.0.0/        HarmonyOS 使用
```

如果仓库根目录下没有 `tools/`，手工创建即可。不要把模型放到 `tts/tools/trial-export/`，也不要直接放到 `tts/android/sdk/src/main/assets/` 或 `tts/harmony/sdk/src/main/resources/rawfile/`。

3. 可选编译产物

如果需要直接给宿主 App 集成，可以额外交付编译后的产物：

```text
tts/android/sdk/build/outputs/aar/sdk-release.aar
tts/harmony/sdk/build/default/outputs/default/sdk.har
```

如果需要给同事做本地验证，也可以额外交付 sample：

```text
tts/android/sample/build/outputs/apk/debug/sample-debug.apk
tts/harmony/sample/build/default/outputs/default/sample-default-unsigned.hap
```

其中 Android `sample-debug.apk` 可用于验证 Android AAR；HarmonyOS `sample-default-unsigned.hap` 只是未签名宿主 HAP，真机安装前需要同事用自己设备信任的签名重新签。

## 2. 不要交付或不要提交到 Git 的内容

以下内容不要提交到 Git：

- 模型文件：`.onnx`、`.ort`、`.pt`、`.ckpt`、`.safetensors` 等
- 构建产物：`build/`、`.gradle/`、`.hvigor/`、`.cxx/`
- HarmonyOS 依赖缓存：`oh_modules/`
- 本机配置：`local.properties`
- 签名材料：`.p12`、`.cer`、`.csr`、`.p7b`、`.signing-local/`
- 压缩包和安装包：`.zip`、`.tar`、`.apk`、`.hap`、`.har`
- 生成出来的模型资源副本：`lits-models/`

这些内容要么体积大，要么与本机环境绑定，要么属于签名/授权敏感材料。

## 3. Android 模型包放置

Android 当前使用：

```text
model_id: lits_delivery_16k_hifigan_streaming_proto
version: 0.1.1
```

请把完整 Android 模型包放到：

```text
AmphionRuntime 根目录\tools\trial-export\lits_delivery_16k_hifigan_streaming_proto\0.1.1\
```

macOS / Linux 写法：

```text
AmphionRuntime 根目录/tools/trial-export/lits_delivery_16k_hifigan_streaming_proto/0.1.1/
```

该目录至少应包含：

- `manifest.json`
- `export_report.json`
- `smoke_tokens.json`
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
- `lits_stream_decoder_chunk.onnx`
- `hifigan_vocoder_int8.onnx`

Android Gradle 构建时会自动把这些文件复制到：

```text
tts/android/sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan_streaming_proto/0.1.1/
```

这个目录是构建生成副本，不是手工投放目录。

## 4. Android 编译步骤

环境要求：

- JDK 17
- Android SDK
- Python 3
- Android 模型包已放到第 3 节指定目录

### 4.1 配置 Android SDK 路径

在：

```text
AmphionRuntime 根目录\tts\android\local.properties
```

写入本机 Android SDK 路径，例如 Windows：

```properties
sdk.dir=C\:\\Android
```

macOS 示例：

```properties
sdk.dir=/Users/yourname/Library/Android/sdk
```

也可以不写 `local.properties`，改用环境变量：

```bash
export ANDROID_HOME=/Users/yourname/Library/Android/sdk
export ANDROID_SDK_ROOT=/Users/yourname/Library/Android/sdk
```

### 4.2 构建 Android AAR

进入 Android 工程：

```bash
cd AmphionRuntime根目录/tts/android
```

macOS / Linux：

```bash
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease
```

Windows PowerShell：

```powershell
.\gradlew.bat :sdk:testDebugUnitTest :sdk:assembleRelease
```

成功后 AAR 在：

```text
tts/android/sdk/build/outputs/aar/sdk-release.aar
```

建议对外交付时重命名为：

```text
lits-tts-android-sdk-0.1.0.aar
```

### 4.3 构建 Android sample APK

如需给同事安装验证：

```bash
./gradlew :sample:assembleDebug
```

产物在：

```text
tts/android/sample/build/outputs/apk/debug/sample-debug.apk
```

## 5. HarmonyOS 模型包放置

HarmonyOS 当前使用：

```text
model_id: lits_delivery_16k_hifigan
version: 1.0.0
```

请把完整 HarmonyOS 模型包放到：

```text
AmphionRuntime 根目录\tools\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

macOS / Linux 写法：

```text
AmphionRuntime 根目录/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/
```

该目录至少应包含：

- `manifest.json`
- `export_report.json`
- `smoke_tokens.json`
- `frontend_golden.json`
- `chinese_lexicon.txt`
- `cmudict.txt`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`
- `lits_acoustic.onnx`
- `hifigan_vocoder.onnx`

HarmonyOS 构建时会自动把这些文件复制到：

```text
tts/harmony/sdk/src/main/resources/rawfile/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/
```

这个目录也是构建生成副本，不要手工维护。

## 6. HarmonyOS 编译步骤

环境要求：

- DevEco Studio 6.x 或配套 Command Line Tools
- HarmonyOS SDK `6.0.2.130`
- DevEco 自带 JBR / Java 17
- Node.js
- HarmonyOS 模型包已放到第 5 节指定目录

建议先设置环境变量，Windows PowerShell 示例：

```powershell
$env:DEVECO_SDK_HOME="C:\Program Files\Huawei\DevEco Studio\sdk"
$env:JAVA_HOME="C:\Program Files\Huawei\DevEco Studio\jbr"
```

进入 HarmonyOS 工程：

```bash
cd AmphionRuntime根目录/tts/harmony
```

### 6.1 构建 HAR

Windows PowerShell：

```powershell
& "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=sdk@default assembleHar --analyze=normal --parallel --incremental --no-daemon
```

macOS 示例：

```bash
/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sdk@default assembleHar --analyze=normal --parallel --incremental --no-daemon
```

成功后 HAR 在：

```text
tts/harmony/sdk/build/default/outputs/default/sdk.har
```

### 6.2 构建 sample HAP

Windows PowerShell：

```powershell
& "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=sample@default assembleHap --analyze=normal --parallel --incremental --no-daemon
```

macOS 示例：

```bash
/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sample@default assembleHap --analyze=normal --parallel --incremental --no-daemon
```

成功后 HAP 在：

```text
tts/harmony/sample/build/default/outputs/default/sample-default-unsigned.hap
```

注意：这个 HAP 默认未签名，不能直接安装到真机。真机验证时，让同事用 DevEco Studio 打开 `tts/harmony`，配置自己设备信任的 debug signing 后重新构建安装。

## 7. 同事拿到交付物后的推荐流程

1. 拉取源码分支：

```bash
git clone git@github.com:amphionspace/AmphionRuntime.git
cd AmphionRuntime
git checkout tts-android-harmony-v2.4
```

2. 创建模型目录：

```bash
mkdir -p tools/trial-export/lits_delivery_16k_hifigan_streaming_proto/0.1.1
mkdir -p tools/trial-export/lits_delivery_16k_hifigan/1.0.0
```

3. 复制模型包：

```text
Android 模型包 -> tools/trial-export/lits_delivery_16k_hifigan_streaming_proto/0.1.1/
Harmony 模型包 -> tools/trial-export/lits_delivery_16k_hifigan/1.0.0/
```

4. 按第 4 节构建 Android AAR。

5. 按第 6 节构建 HarmonyOS HAR。

6. 如果需要验证 demo，再分别构建 Android sample APK 和 HarmonyOS sample HAP。

## 8. 最终给业务方的文件建议

如果业务方只集成 SDK，建议给：

```text
android/
└── lits-tts-android-sdk-0.1.0.aar

harmony/
└── sdk.har

docs/
├── TTS_ANDROID_HARMONY_DELIVERY_CN.md
├── Android API / 集成说明
└── HarmonyOS API / 集成说明
```

如果业务方还要复现构建，额外给：

```text
source/
└── AmphionRuntime branch tts-android-harmony-v2.4

models/
├── lits_delivery_16k_hifigan_streaming_proto/0.1.1/
└── lits_delivery_16k_hifigan/1.0.0/
```

如果业务方要本地验证 demo，额外给：

```text
demo/
├── sample-debug.apk
└── sample-default-unsigned.hap
```

HarmonyOS 的 `sample-default-unsigned.hap` 需要重新签名后才能安装。

## 9. 常见问题

### Android 构建时提示找不到模型

检查模型是否放在：

```text
tools/trial-export/lits_delivery_16k_hifigan_streaming_proto/0.1.1/
```

不要放到 `tts/tools/trial-export/`。

### Android 构建时提示 SDK location not found

检查：

- `tts/android/local.properties` 是否存在
- `sdk.dir` 是否指向真实 Android SDK
- 或 `ANDROID_HOME` / `ANDROID_SDK_ROOT` 是否设置

### HarmonyOS 构建时提示缺模型文件

检查模型是否放在：

```text
tools/trial-export/lits_delivery_16k_hifigan/1.0.0/
```

不要放到 `tts/harmony/sdk/src/main/resources/rawfile/`。

### HarmonyOS HAP 无法安装

优先检查签名。`sample-default-unsigned.hap` 是未签名产物，真机安装需要用当前设备信任的 debug signing 重新签。

### 需要改专有名词读音

不要改生成目录。修改模型包源目录里的词典文件，然后重新构建 SDK：

```text
tools/trial-export/.../chinese_lexicon.txt
tools/trial-export/.../cmudict.txt
```

Android 和 HarmonyOS 使用不同模型包时，两边词典都要同步更新。
