# 从源码构建 SDK

本文面向第一次拿到这份源码工程的协作者，目标是只靠文档就能从 0 构建出 Android SDK AAR。

最终产物：

```text
sdk/build/outputs/aar/sdk-release.aar
sample/build/outputs/apk/debug/sample-debug.apk
```

下面统一用 `仓库根目录` 指代 amphion-runtime 仓库根目录，例如：

```text
D:\work\amphion-runtime
```

下文的路径和命令默认按 Windows 写；如果你在 macOS 或 Linux 上构建，请把路径分隔符和 `gradlew.bat` 替换成各自平台的等价形式，例如把 `.\gradlew.bat` 换成 `./gradlew`。

## 0. 从 0 开始的最短路径

如果你完全不知道文件该往哪里放，可以直接按下面 5 步做：

1. 把源码放到任意本机目录，例如：

```text
D:\work\amphion-runtime
```

2. 把完整模型包复制到：

```text
D:\work\amphion-runtime\tools\tts\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

3. 在下面这个文件写 Android SDK 路径：

```text
D:\work\amphion-runtime\android\TtsRuntime\local.properties
```

内容示例：

```properties
sdk.dir=C\:\\Android
```

4. 打开终端进入：

```text
D:\work\amphion-runtime\android\TtsRuntime
```

5. 依次执行：

```powershell
python ..\..\tools\tts\verify_lits_delivery_16k_package.py --model-dir ..\..\tools\tts\trial-export\lits_delivery_16k_hifigan\1.0.0
.\gradlew.bat :sdk:testDebugUnitTest
.\gradlew.bat :sdk:assembleRelease
.\gradlew.bat :sample:assembleDebug
```

如果这 5 步你能顺着做完，就已经能从 0 构建出 SDK 和可安装验证 App。

## 1. 源码仓库里有什么，没什么

源码仓库中保留：

- `tts/android/`
- `tts/tools/verify_lits_delivery_16k_package.py`
- `tts/tools/README.md`
- `tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/.gitkeep`

源码仓库中不保留：

- `tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/` 里的真实 `.onnx/.json/.txt/.wav`
- `local.properties`
- `.gradle/`
- `build/`

所以在真正构建前，你必须先拿到完整模型包，并自己放到约定目录。

## 2. 环境前提

构建 `:sdk` 至少需要：

- JDK 17
- Android SDK
- Python 3
- Windows PowerShell、macOS Terminal 或 Linux Shell 任一种
- 完整模型包 `lits_delivery_16k_hifigan/1.0.0`

当前工程内已经自带：

- Gradle Wrapper
- ONNX Runtime Java classes jar
- `arm64-v8a` JNI 动态库
- SDK 源码和单元测试
- `:sample` 可安装验证 App 源码

因此，你不需要再手动下载 ONNX Runtime 依赖，也不需要自己导出 `.so`。

## 3. 准备 Android SDK 路径

Gradle 必须能找到本机 Android SDK。常用做法有两种，二选一即可。

### 方法 A：在工程目录写 `local.properties`

在：

```text
仓库根目录\android\TtsRuntime\local.properties
```

写入：

```properties
sdk.dir=C\:\\Android
```

如果 Android SDK 在别的位置，替换成实际路径即可。

### 方法 B：设置环境变量

Windows PowerShell 临时设置：

```powershell
$env:ANDROID_HOME="C:\Android"
$env:ANDROID_SDK_ROOT="C:\Android"
```

如果你本机 Android SDK 不在 `C:\Android`，替换成真实路径。

## 4. 准备模型包

把完整模型包放到下面这个目录：

```text
仓库根目录\tools\tts\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

例如：

```text
D:\work\amphion-runtime\tools\tts\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

该目录在源码仓库里只有一个 `.gitkeep` 占位文件；真实模型文件需要你在构建前单独放入。

放好以后，目录结构应该长这样：

```text
仓库根目录/
├── android/
│   └── AmphionRuntime/
│       ├── gradlew.bat
│       ├── local.properties
│       └── sdk/
└── tools/
    └── trial-export/
        └── lits_delivery_16k_hifigan/
            └── 1.0.0/
                ├── manifest.json
                ├── lits_acoustic.onnx
                ├── hifigan_vocoder.onnx
                ├── smoke_tokens.json
                ├── frontend_golden.json
                ├── chinese_lexicon.txt
                └── ...
```

最少需要以下文件：

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
- `export_report.json`

如果你还拿到了下面这个文件，也建议一并保留：

- `onnx_smoke_hello_world.wav`

注意：

- 不需要 checkpoint
- 不需要执行 `export_lits_delivery_16k_hifigan_onnx.py`
- 不要把模型手动放到 `sdk/src/main/assets/...`
- `onnx_smoke_hello_world.wav` 只是导出时附带的参考音频，不参与 SDK 构建，也不是 Android 预检的必需输入
- 如果需要补充专有名词固定读音，统一按 [../../../tts/tools/README.md](../../../tts/tools/README.md) 里的“专有名词怎么改”处理

下面这个目录是 Gradle 构建时自动同步生成的，不是你手工投放模型的位置：

```text
sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/
```

## 5. 校验模型包完整性

打开终端进入：

```text
仓库根目录\android\TtsRuntime
```

然后执行：

```powershell
python ..\..\tools\tts\verify_lits_delivery_16k_package.py --model-dir ..\..\tools\tts\trial-export\lits_delivery_16k_hifigan\1.0.0
```

正常情况下会输出一条：

```text
[OK] verified 16k package: ...
```

如果失败，优先检查：

- 文件名是否完整
- 目录层级是否正确
- 是否把模型放到了 `tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/`

## 6. 构建过程

### 第一步：运行单元测试

终端当前目录仍然是：

```text
仓库根目录\android\TtsRuntime
```

执行：

```powershell
.\gradlew.bat :sdk:testDebugUnitTest
```

这一步主要验证：

- 文本前端资源是否能被读取
- 基本 TTS SDK 逻辑是否通过当前测试

### 第二步：构建 release AAR

执行：

```powershell
.\gradlew.bat :sdk:assembleRelease
```

构建时，根 `build.gradle.kts` 会自动做一件事：

- 在 `preBuild` 阶段把 `tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/` 中的模型文件同步到 `sdk/src/main/assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/`

因此，你不需要手动复制模型到 `sdk/src/main/assets/...`。

### 第三步：构建 sample APK

执行：

```powershell
.\gradlew.bat :sample:assembleDebug
```

sample APK 位于：

```text
仓库根目录\android\TtsRuntime\sample\build\outputs\apk\debug\sample-debug.apk
```

这个 APK 依赖本工程 `:sdk` 模块，启动后会加载模型并提供合成、SDK 直接播报、播放结果和保存 WAV 的验证流程。

## 7. 构建产物和自检

构建成功后，AAR 位于：

```text
仓库根目录\android\TtsRuntime\sdk\build\outputs\aar\sdk-release.aar
```

例如：

```text
D:\work\amphion-runtime\android\TtsRuntime\sdk\build\outputs\aar\sdk-release.aar
```

如果后续需要把 AAR 交付给宿主 App 或外部协作者，建议在发出前重命名为：

```text
lits-tts-sdk-0.1.0.aar
```

## 8. 正式交付包（含 Android 源码）

裸 AAR 只适合本地验证。正式对外交付 Android SDK 时，应从 `仓库根目录` 使用打包脚本：

```bash
bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.1.0
```

脚本会执行：

1. 校验模型包目录是否包含构建 AAR 必需文件
2. 运行 `:sdk:testDebugUnitTest`
3. 运行 `:sdk:assembleRelease`
4. 运行 `:sample:assembleDebug`
5. 复制并重命名 AAR 为 `lits-tts-sdk-0.1.0.aar`
6. 复制 sample APK 为 `demo/lits-tts-sample-debug.apk`
7. 生成 `android-src/TTS/` Android 源码快照
8. 写入 `VERSION.txt` 并生成 zip

默认模型目录仍是：

```text
tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/
```

如果模型包在外部目录，可用环境变量覆盖：

```bash
LITS_TTS_MODEL_DIR=/path/to/lits_delivery_16k_hifigan/1.0.0 \
  bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.1.0
```

交付包结构：

```text
delivery/lits-tts-android-sdk-v0.1.0/
├── aar/lits-tts-sdk-0.1.0.aar
├── demo/lits-tts-sample-debug.apk
├── android-src/TTS/
├── docs/
├── README.txt
└── VERSION.txt
```

`android-src/TTS/` 是从 git-tracked Android 源码生成的快照，并叠加本次构建使用的模型包，便于收包方从源码重建 AAR。它不会包含：

- `local.properties`
- Gradle `.gradle/` 或 `build/` 产物
- 私钥 / `.pem`
- 生成的 `tts/android/sdk/src/main/assets/`

可用下面命令校验交付目录或 zip：

```bash
bash tts/tools/android/verify_lits_tts_android_delivery.sh ../delivery/lits-tts-android-sdk-v0.1.0/
bash tts/tools/android/verify_lits_tts_android_delivery.sh ../delivery/lits-tts-android-sdk-v0.1.0-YYYYMMDD.zip
```

建议至少做以下自检：

1. 确认 AAR 文件已生成
2. 确认 AAR 体积明显大于纯代码库，说明模型资源和 JNI 库已打进去
3. 解压 AAR 后至少应看到以下内容：

- `classes.jar`
- `proguard.txt`
- `libs/onnxruntime-android-1.24.3-classes.jar`
- `jni/arm64-v8a/libonnxruntime.so`
- `jni/arm64-v8a/libonnxruntime4j_jni.so`
- `assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/manifest.json`
- `assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/lits_acoustic.onnx`
- `assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/hifigan_vocoder.onnx`

## 9. 常见问题

### 9.1 `SDK location not found`

说明 Gradle 找不到 Android SDK。

检查：

- `仓库根目录\android\TtsRuntime\local.properties` 是否存在
- `sdk.dir` 是否写成真实路径
- 或 `ANDROID_HOME` / `ANDROID_SDK_ROOT` 是否已设置

### 9.2 模型包校验失败

说明模型目录不完整或路径不对。

检查：

- 文件是否放到了 `仓库根目录\tools\tts\trial-export\lits_delivery_16k_hifigan\1.0.0\`
- `manifest.json`、两个 ONNX、词典和映射文件是否都在

### 9.3 `:sdk:testDebugUnitTest` 失败但模型文件明明存在

通常是以下原因之一：

- 运行命令的当前目录不对
- `preBuild` 执行前，测试还没拿到预期资源
- 之前残留的 `build/` 目录导致旧状态干扰

可以先清理后重试：

```powershell
.\gradlew.bat clean
.\gradlew.bat :sdk:testDebugUnitTest
```

### 9.4 AAR 里缺模型或缺 JNI 库

优先检查：

- `sdk/src/main/jniLibs/arm64-v8a/` 是否仍在源码里
- 构建前模型包是否已放到 `tts/tools/trial-export/...`
- `.gitignore` 是否只是忽略生成物，而不是把源码依赖误删了

## 10. 当前限制

- 当前只提供 `arm64-v8a` native 库
- 当前只支持 `RunMode.OFFLINE`
- `modelLoadOnCreate=false` 当前不支持
- 普通 AAR 只能限制单进程内最多 3 个 engine 实例，不能可靠限制全设备跨 App 实例数
