# AmphionRuntime

基于 sherpa-onnx 的 AmphionRuntime 工程。

包含三个 Gradle 模块：

| 模块 | 类型 | 说明 |
| --- | --- | --- |
| `:sdk` | Android Library (AAR) | 对外发布的 SDK；包名 `com.amphion.asr` |
| `:sample` | Android Application (APK) | 对外 demo：30 行最小 Activity，零网络权限，applicationId `com.amphion.asr.sample` |
| `:sample-eval` | Android Application (APK) | 对内评测版：评测数据采集 + WER 估算 + 上传，applicationId `com.amphion.asr.sample.eval` |

> 0.2.0 起所有模型（中英 ASR / 粤英 ASR / 标点 / 中文 ITN / VAD）一并打进 AAR，业务方不再需要任何外部模型分发。
>
> 对外交付边界：业务方只拿 `:sdk` AAR 与 `:sample` 产物；`:sample-eval` 含 INTERNET 权限 + FileProvider + OkHttp 上传链路，仅用于内部评测，不在交付范围内。详见 [docs/INTEGRATION.md](docs/INTEGRATION.md) 与 [docs/DELIVERY.md](docs/DELIVERY.md)。

## 快速开始

零基础完整端到端走一遍，请看 `tools/asr/QUICKSTART.md`。下面假设你已经装好工具链：

```bash
# 0) 工具链与 .so 编译（首次必须）
#    - 安装：tools/asr/ANDROID_TOOLCHAIN.md
#    - 编 .so：bash tools/asr/04_build_android_so.sh arm64-v8a
#    - 拷 .so：bash tools/asr/05_package_aar_libs.sh

# 1) 第一次：初始化 Gradle wrapper
bash init_gradle_wrapper.sh

# 2) 让 AGP 找到 Android SDK，二选一即可（推荐 A）：
#    A. 在本目录创建 local.properties
cat > local.properties <<EOF
sdk.dir=$HOME/Library/Android/sdk
EOF
#    B. 或者 export 一个永久环境变量（写到 ~/.zprofile）：
#       export ANDROID_HOME="$HOME/Library/Android/sdk"
#       export ANDROID_SDK_ROOT="$ANDROID_HOME"

# 3) 把 5 类模型打进 SDK assets（中英 / 粤英 ASR + 标点 + ITN + VAD）
#    详见 docs/DELIVERY.md §3.3
bash ../../tools/asr/08_pack_sdk_assets.sh

# 4) 构建 SDK（AAR 输出在 sdk/build/outputs/aar/sdk-release.aar）
./gradlew :sdk:assembleRelease

# 5) 发布到本地 Maven（产出 com.amphion:amphion-runtime:0.2.0）
./gradlew :sdk:publishReleasePublicationToLocalFileRepoRepository

# 6) 生成 API 文档
./gradlew :sdk:dokkaHtml
# 文档入口：sdk/build/dokka/html/index.html

# 7) 装 sample 自验
./gradlew :sample:installDebug
adb shell am start -n com.amphion.asr.sample/.MainActivity
```

如果第 7 步报 `more than one device/emulator`：

```bash
adb devices                                     # 找到目标真机的 serial
export ANDROID_SERIAL=<真机 serial>             # 之后 gradle install / adb 都默认走这台
./gradlew :sample:installDebug
```

## SDK 公开 API（0.2.0）

仅 4 个公开类 + 几个 data class：

```
com.amphion.asr.AmphionRuntime    # 顶层入口（init / preload / preInstall / create / version / release）
com.amphion.asr.AsrEngine          # 引擎实例（包含 ASR + 标点 + ITN + VAD）
com.amphion.asr.AsrSession         # 单次识别会话
com.amphion.asr.AsrCallback        # 识别结果回调（含 onMetrics 默认空实现）
                                   #
com.amphion.asr.AsrLanguage        # ZH_EN | YUE_EN
com.amphion.asr.AsrConfig          # numThreads / punctuation / itn / vad / endpoint / hotwords
com.amphion.asr.AsrResult          # text + 置信度 + token + 时间戳
com.amphion.asr.AsrError           # 错误信息
com.amphion.asr.AmphionMetrics     # 端侧标准指标（与未来鸿蒙端共用 schema）
com.amphion.asr.AmphionMetricsKind # UTTERANCE | SESSION
com.amphion.asr.AmphionOptions     # init 选项
com.amphion.asr.AmphionLogLevel    # 日志级别
com.amphion.asr.Cancellable        # preInstall / preload 的取消句柄
```

最小集成示例（推荐 preload，~30 行）：

```kotlin
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        AmphionRuntime.init(this)
        // 把要用到的语言一次性加载好；之后切换 0 延迟
        Thread {
            AmphionRuntime.preload(
                this,
                listOf(AsrLanguage.ZH_EN, AsrLanguage.YUE_EN),
            )
        }.start()
    }
}

class MyActivity : AppCompatActivity() {
    private var engine: AsrEngine? = null
    private var session: AsrSession? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Thread {
            engine = AmphionRuntime.create(this, AsrLanguage.ZH_EN) // preload 后 O(ms)
            session = engine!!.newSession(object : AsrCallback {
                override fun onPartial(text: String) { runOnUiThread { /* UI */ } }
                override fun onFinal(text: String, confidence: Float) {
                    runOnUiThread { /* text 已含 ITN + 标点 */ }
                }
                override fun onMetrics(metrics: AmphionMetrics) {
                    // metrics.utteranceE2eLatencyMs / .rtf / .nativeRssMb 等
                }
            })
            // session!!.acceptPcmShort(samples)
        }.start()
    }

    override fun onDestroy() {
        super.onDestroy()
        session?.close()
        engine?.close()
        // 注意：AmphionRuntime.release() 会清空 ASR 池，下次进入需要重新 preload；
        // 短期切换 Activity 不需要调
    }
}
```

更详细的接入指南见 [docs/INTEGRATION.md](docs/INTEGRATION.md)；多语言预加载与运行时指标分别见 §11、§12。

## 目录布局

```
AmphionRuntime/
├── README.md                   # 本文件
├── LICENSE                     # 自有 SDK 协议（Apache 2.0 模板）
├── NOTICE                      # 第三方依赖声明（sherpa-onnx / onnxruntime / silero-vad / WeTextProcessing / ...）
├── settings.gradle.kts         # 根 settings：include sdk + sample
├── build.gradle.kts            # 根 build：仅声明 plugin 版本
├── gradle.properties           # 全局属性 + SDK 坐标（GROUP/ARTIFACT/VERSION）
├── gradle/
│   ├── libs.versions.toml      # 版本目录（AGP/Kotlin/Dokka/AndroidX 等）
│   └── wrapper/gradle-wrapper.properties
├── init_gradle_wrapper.sh      # 一次性脚本：从 SherpaOnnxAar 复制 gradlew + wrapper jar
│
├── sdk/                        # SDK 模块
│   ├── build.gradle.kts        # AAR + Dokka + maven-publish；assets noCompress=onnx,fst
│   ├── consumer-rules.pro      # 客户开混淆时自动应用的规则
│   ├── proguard-rules.pro      # 开发态混淆规则（include consumer-rules.pro）
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── jniLibs/<abi>/      # 由 tools/asr/05_package_aar_libs.sh 填充
│       ├── assets/amphion-models/    # 由 tools/asr/08_pack_sdk_assets.sh 填充
│       │   ├── zh-en/v1/             # 中英 ASR
│       │   ├── yue-en/v1/            # 粤英 ASR
│       │   ├── punct-zhen/v1/        # 标点 (CT-Transformer)
│       │   ├── itn-zh/v1/            # WeText 中文 ITN
│       │   └── vad/v1/               # silero VAD
│       └── java/
│           ├── com/k2fsa/sherpa/onnx/    # 来自 sherpa-onnx 上游（保留 license header）
│           └── com/amphion/asr/          # SDK 公开 API
│               ├── AmphionRuntime.kt
│               ├── AsrLanguage.kt
│               ├── AsrConfig.kt
│               ├── AsrEngine.kt
│               ├── AsrSession.kt
│               ├── AsrCallback.kt
│               ├── AsrResult.kt
│               ├── AsrError.kt
│               ├── AmphionMetrics.kt
│               └── internal/             # 内部实现（不暴露给客户、不进 Dokka）
│                   ├── AssetRegistry.kt
│                   ├── AssetInstaller.kt
│                   ├── EngineImpl.kt
│                   ├── SessionImpl.kt
│                   ├── PostProcessor.kt
│                   ├── SharedPostProcessor.kt
│                   ├── MetricsCollector.kt
│                   ├── ProcessRssReader.kt
│                   ├── InternalPunctuationEngine.kt
│                   ├── InternalWeitnEngine.kt
│                   ├── NativeGuard.kt
│                   └── Logger.kt
│
├── sample/                     # 对外 demo App（applicationId com.amphion.asr.sample）
│   ├── build.gradle.kts        # 仅 RECORD_AUDIO 权限；零网络依赖
│   ├── proguard-rules.pro
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/amphion/asr/sample/
│       │   ├── AmphionApp.kt
│       │   ├── MainActivity.kt
│       │   ├── AudioRecorder.kt
│       │   └── WaveformView.kt
│       └── res/
│           ├── layout/activity_main.xml
│           └── values/strings.xml
│
├── sample-eval/                # 对内评测 App（applicationId com.amphion.asr.sample.eval）
│   ├── build.gradle.kts        # 含 OkHttp / RecyclerView / lifecycle；INTERNET + FileProvider
│   ├── proguard-rules.pro
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/amphion/asr/sample/
│       │   ├── AmphionApp.kt          # AmphionRuntime.init + preload(ZH_EN, YUE_EN)
│       │   ├── AudioRecorder.kt       # 与 :sample 共用思路（独立副本）
│       │   ├── WaveformView.kt
│       │   └── eval/                  # 评测框架主体
│       │       ├── LandingActivity.kt # 评测入口（已删 demo 跳板）
│       │       ├── EvalActivity.kt    # 评测主页：句子列表 + 测试员 + 上传状态
│       │       ├── RecordSentenceActivity.kt
│       │       ├── SentenceDetailActivity.kt
│       │       ├── OnDeviceTranscriber.kt   # 含 onMetrics 接入
│       │       ├── EvalRecorder.kt / WavWriter.kt
│       │       ├── DeviceWerEstimator.kt / DiffRenderer.kt
│       │       ├── data/              # LanguagePrefs / TesterPrefs / RecordingStore / ...
│       │       ├── model/             # RecordingMeta / SentenceManifest / ...
│       │       ├── upload/            # HttpUploader / UploadScanner / UploadStatusBar
│       │       └── export/            # ZipExporter / RecordingExporter
│       ├── res/                # eval 专用 layout / menu / xml
│       └── assets/eval-set/    # 内置参考句子集
│
└── docs/
    ├── INTEGRATION.md          # 集成文档（中文，给客户看）
    ├── DELIVERY.md             # 交付指南（内部 SOP）
    ├── PRIVACY.md              # 隐私合规说明
    ├── CHANGELOG.md
    └── API_DOC_BUILD.md        # 如何生成 Dokka HTML 文档
```

## 包名 / 坐标改名（下游 fork 用）

仓库默认坐标是 `com.amphion:amphion-runtime:0.2.0`，包名 `com.amphion.asr`。如果你的团队 fork 出去要换成自己的命名空间，用脚本一键替换：

```bash
bash tools/asr/06_rename_namespace.sh --group-id com.<your-org>
```

## 与上游 sherpa-onnx 的关系

本 SDK 锁定 sherpa-onnx tag `v1.13.1`，并在两个层面复用其代码：

1. native 层（运行时）：`libsherpa-onnx-jni.so` + `libonnxruntime.so`，由
   `tools/asr/04_build_android_so.sh` 在 `sherpa-onnx` 仓库根目录执行 NDK 交叉编译产生。
2. Kotlin 层（编译时）：`com.k2fsa.sherpa.onnx.*` 的 Kotlin 文件，保留上游 Apache-2.0 license header。

我们自己的 SDK 公开 API 全部位于 `com.amphion.asr.*`，把上游 API 完全隐藏，对外只暴露 11 个公开类型。

## 关键开发约束

- 公开 API 只允许 `class` / `interface` / `data class` / `enum class` / `object`，不使用 inline value class、context receivers、suspend fun 等 Kotlin-only 特性
- 所有公开方法 / 类必须有 KDoc
- 公开 API 修改需要同步：consumer-rules.pro / INTEGRATION.md / CHANGELOG.md
- native crash 必须被捕获并归一为错误码 9001，绝不让 Throwable 透传给业务方
- 一切 IO / 阻塞操作都不允许在主线程执行（SDK 不主动占用主线程）
