# AmphionRuntime

基于 sherpa-onnx 的 AmphionRuntime 工程。

包含两个 Gradle 模块：

| 模块 | 类型 | 说明 |
| --- | --- | --- |
| `:sdk` | Android Library (AAR) | 对外发布的 SDK；包名 `com.amphion.asr` |
| `:sample` | Android Application (APK) | 单 Activity 示例：按住说话 → partial / final |

## 快速开始

零基础完整端到端走一遍，请看 `tools/asr/QUICKSTART.md`（含 NDK / brew / cmake / 无线调试 / 模型 push 全链路）。下面假设你已经装好工具链且已用 04/05 脚本编出了 .so：

```bash
# 0) 工具链与 .so 编译（首次必须）
#    - 安装：tools/asr/ANDROID_TOOLCHAIN.md
#    - 编 .so：bash tools/asr/04_build_android_so.sh arm64-v8a
#    - 拷 .so：bash tools/asr/05_package_aar_libs.sh

# 1) 第一次：初始化 Gradle wrapper（从官方 SherpaOnnxAar 复制 gradlew/gradle-wrapper.jar）
bash init_gradle_wrapper.sh

# 2) 让 AGP 找到 Android SDK，二选一即可（推荐 A）：
#    A. 在本目录创建 local.properties
cat > local.properties <<EOF
sdk.dir=$HOME/Library/Android/sdk
EOF
#    B. 或者 export 一个永久环境变量（写到 ~/.zprofile）：
#       export ANDROID_HOME="$HOME/Library/Android/sdk"
#       export ANDROID_SDK_ROOT="$ANDROID_HOME"
# 注：local.properties 不应提交到 git；本工程的 .gitignore 已经排除。

# 3) 构建 SDK（AAR 输出在 sdk/build/outputs/aar/sdk-release.aar）
./gradlew :sdk:assembleRelease

# 4) 发布到本地 Maven（产出 com.amphion:amphion-runtime:0.1.0）
./gradlew :sdk:publishReleasePublicationToLocalFileRepoRepository

# 5) 生成 API 文档
./gradlew :sdk:dokkaHtml
# 文档入口：sdk/build/dokka/html/index.html

# 6) 装 sample 验证
./gradlew :sample:installDebug

# 7) push demo 模型并启动 app
bash ../../tools/asr/00_fetch_demo_model.sh push
adb shell am force-stop com.amphion.asr.sample
adb shell am start -n com.amphion.asr.sample/.MainActivity
```

如果 step 6 报 `more than one device/emulator`：

```bash
adb devices                                     # 找到目标真机的 serial
export ANDROID_SERIAL=<真机 serial>             # 之后 gradle install / adb 都默认走这台
./gradlew :sample:installDebug
```

## 目录布局

```
AmphionRuntime/
├── README.md                   # 本文件
├── LICENSE                     # 自有 SDK 协议（Apache 2.0 模板）
├── NOTICE                      # 第三方依赖声明（sherpa-onnx / onnxruntime / silero-vad / ...）
├── settings.gradle.kts         # 根 settings：include sdk + sample
├── build.gradle.kts            # 根 build：仅声明 plugin 版本
├── gradle.properties           # 全局属性 + SDK 坐标（GROUP/ARTIFACT/VERSION）
├── gradle/
│   ├── libs.versions.toml      # 版本目录（AGP/Kotlin/Dokka/AndroidX 等）
│   └── wrapper/gradle-wrapper.properties
├── init_gradle_wrapper.sh      # 一次性脚本：从 SherpaOnnxAar 复制 gradlew + wrapper jar
│
├── sdk/                        # SDK 模块
│   ├── build.gradle.kts        # AAR + Dokka + maven-publish
│   ├── consumer-rules.pro      # 客户开混淆时自动应用的规则
│   ├── proguard-rules.pro      # 开发态混淆规则（include consumer-rules.pro）
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── jniLibs/<abi>/      # 由 tools/asr/05_package_aar_libs.sh 填充
│       └── java/
│           ├── com/k2fsa/sherpa/onnx/    # 来自 sherpa-onnx 上游（保留 license header）
│           │   ├── OnlineRecognizer.kt
│           │   ├── OnlineStream.kt
│           │   ├── Vad.kt
│           │   ├── FeatureConfig.kt
│           │   └── HomophoneReplacerConfig.kt
│           └── com/amphion/asr/          # AmphionRuntime ASR 的公开 API
│               ├── AsrSdk.kt
│               ├── AsrConfig.kt
│               ├── AsrEngine.kt
│               ├── AsrSession.kt
│               ├── AsrCallback.kt
│               ├── AsrError.kt
│               ├── ModelManager.kt
│               ├── ModelDescriptor.kt
│               └── internal/             # 内部实现（不暴露给客户、不进 Dokka）
│                   ├── Logger.kt
│                   ├── EngineImpl.kt
│                   ├── SessionImpl.kt
│                   ├── ModelDownloader.kt
│                   └── Sha256Verifier.kt
│
├── sample/                     # Sample App
│   ├── build.gradle.kts
│   ├── proguard-rules.pro
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/amphion/asr/sample/
│       │   ├── MainActivity.kt
│       │   └── AudioRecorder.kt
│       └── res/
│           ├── layout/activity_main.xml
│           └── values/strings.xml
│
└── docs/
    ├── INTEGRATION.md          # 集成文档（中文，给客户看）
    ├── PRIVACY.md              # 隐私合规说明
    ├── CHANGELOG.md
    └── API_DOC_BUILD.md        # 如何生成 Dokka HTML 文档
```

## 包名 / 坐标改名（下游 fork 用）

仓库默认坐标是 `com.amphion:amphion-runtime:0.1.0`，包名 `com.amphion.asr`。如果你的团队 fork 出去要换成自己的命名空间，用脚本一键替换：

```bash
# 在仓库根目录执行
bash tools/asr/06_rename_namespace.sh --group-id com.<your-org>
# 默认 pkg-prefix = <group-id>.asr，需要自定义则带 --pkg-prefix com.<your-org>.xxx
```

脚本会处理：

- `gradle.properties` 中 `AMPHION_RUNTIME_GROUP_ID`
- `sdk/` 与 `sample/` 下所有 `*.kt` / `AndroidManifest.xml` / `build.gradle.kts` / `*.pro` 中的 `com.amphion.asr` 字面量
- 物理目录 `sdk/src/main/java/com/amphion/asr/` → `<new-pkg-path>/`

它不会动 `NOTICE` / `LICENSE` / `docs/PRIVACY.md` 里的 `Amphion` 公司名——这些请手工替换为你公司的法定全称。

## 与上游 sherpa-onnx 的关系

本 SDK 锁定 sherpa-onnx tag `v1.13.1`，并在两个层面复用其代码：

1. native 层（运行时）：`libsherpa-onnx-jni.so` + `libonnxruntime.so`，由
   `tools/asr/04_build_android_so.sh` 在 `sherpa-onnx` 仓库根目录执行 NDK 交叉编译产生。
2. Kotlin 层（编译时）：`com.k2fsa.sherpa.onnx.*` 的 5 个 Kotlin 文件（OnlineRecognizer / OnlineStream / Vad / FeatureConfig / HomophoneReplacerConfig），保留上游 Apache-2.0 license header。

我们自己的 SDK 公开 API 全部位于 `com.amphion.asr.*`，把上游 API 完全隐藏，对外只暴露 8 个公开类型。

## 关键开发约束

- 公开 API 只允许 `class` / `interface` / `data class` / `enum class` / `object`，不使用 inline value class、context receivers、suspend fun 等 Kotlin-only 特性
- 所有公开方法 / 类必须有 KDoc
- 公开 API 修改需要同步：consumer-rules.pro / INTEGRATION.md / CHANGELOG.md
- native crash 必须被捕获并归一为错误码 9001，绝不让 Throwable 透传给业务方
- 一切 IO / 阻塞操作都不允许在主线程执行（SDK 不主动占用主线程）
