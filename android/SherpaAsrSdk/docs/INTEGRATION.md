# ASR SDK 集成指南

适用 SDK 版本：0.1.0
对应 sherpa-onnx：v1.13.1（third_party/sherpa-onnx submodule pinned tag）

## 1. 环境要求

| 项 | 最低版本 | 推荐版本 |
| --- | --- | --- |
| Android API Level (minSdk) | 24 (Android 7.0) | 24+ |
| Android API Level (targetSdk) | 33 | 34 |
| Android Gradle Plugin | 8.0 | 8.4 |
| Gradle | 8.0 | 8.6 |
| Kotlin | 1.8.0 | 1.9.x |
| ABI | arm64-v8a | arm64-v8a |
| 设备最小内存 | 1 GB 可用堆 | 2 GB |
| 模型大小 | 约 50 MB（INT8） | — |

注：本 SDK 不支持 x86 / x86_64 / armeabi-v7a 默认包；如需要 armeabi-v7a 请联系我们提供专门构建。

## 2. 引入依赖

### 方案 A：使用本地 Maven 仓库（推荐用于内部交付）

`asr-sdk-0.1.0` 同时提供 AAR 与 Maven POM。先把它发布到本地仓库：

```bash
cd android/SherpaAsrSdk
./gradlew :sdk:publishReleasePublicationToLocalFileRepoRepository
```

然后在你的 app 工程的 `settings.gradle.kts` 加入：

```kotlin
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        maven { url = uri("file:///path/to/SherpaAsrSdk/sdk/build/maven-repo") }
    }
}
```

并在 app `build.gradle.kts` 添加依赖：

```kotlin
dependencies {
    implementation("com.yourco:asr-sdk:0.1.0")
}
```

### 方案 B：直接用 .aar 文件

把 `sdk-release.aar`（在 `android/SherpaAsrSdk/sdk/build/outputs/aar/` 下）拷贝到 app 工程的 `libs/` 目录：

```kotlin
dependencies {
    implementation(files("libs/sdk-release.aar"))
    // SDK 内部使用 androidx.core，下面这行别忘
    implementation("androidx.core:core-ktx:1.13.1")
}
```

## 3. 权限

在你的 app `AndroidManifest.xml` 里声明：

```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />

<!-- 如果你用了 ModelManager.ensure() 在线下载模型，需要这两个 -->
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
```

`RECORD_AUDIO` 是运行时权限，需要在 Activity 里通过 `ActivityResultContracts.RequestPermission` 申请。SDK 自身 不会 调用 `AudioRecord`，业务方负责录音并把 PCM 喂进来。

## 4. 初始化

在你的 `Application.onCreate()` 里调用一次：

```kotlin
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        AsrSdk.init(this, AsrSdkOptions(logLevel = AsrLogLevel.WARN))
    }
}
```

## 5. 模型准备

模型不打进 APK，运行时下载到 `<filesDir>/asr-models/<model_id>/<version>/`。

```kotlin
val mm = ModelManager(context)

// 先看本地是否已经有
val localList = mm.listLocal()
if (localList.isNotEmpty()) {
    initEngine(localList.first().dir)
    return
}

// 下载（manifest.json 是你服务端发布的）
val cancellable = mm.ensure(
    manifestUrl = "https://your-cdn.example.com/asr/zh-en/1.0.0/manifest.json",
    callback = object : ModelDownloadCallback {
        override fun onProgress(modelId: String, downloadedBytes: Long, totalBytes: Long) {
            // 更新 UI
        }
        override fun onCompleted(modelId: String, modelDir: File) {
            initEngine(modelDir)
        }
        override fun onError(modelId: String, error: AsrError) {
            // 处理错误
        }
    }
)

// 想取消下载
// cancellable.cancel()
```

manifest.json 的结构与生成方法见 `tools/asr-sdk/MODEL_LAYOUT.md`。

## 6. 创建引擎与会话

```kotlin
fun initEngine(modelDir: File) {
    val config = AsrConfig.Builder(modelDir)
        .numThreads(2)
        .enableEndpoint(true)
        .hotwords(listOf("声学模型", "深度学习"), score = 1.5f)
        .build()

    engine = AsrEngine(config)
}

fun startTalking() {
    val session = engine.newSession(object : AsrCallback {
        override fun onPartial(text: String) {
            runOnUiThread { partialView.text = text }
        }
        override fun onFinal(text: String, confidence: Float) {
            runOnUiThread { finalView.append(text + "\n") }
        }
        override fun onEndpoint() {
            // 一段话结束的提示，可选
        }
        override fun onError(error: AsrError) {
            runOnUiThread { showError(error.code, error.message) }
        }
    })

    // 业务方启动 AudioRecord 喂数据：
    audioRecorder.start { samples: ShortArray ->
        session.acceptPcmShort(samples, 16000)
    }
}

fun stopTalking() {
    audioRecorder.stop()
    session.stop()
    session.close()
}

override fun onDestroy() {
    super.onDestroy()
    engine.close()
}
```

PCM 格式要求：

| 项 | 取值 |
| --- | --- |
| 采样率 | 16000 Hz（必须） |
| 声道 | 单声道（必须） |
| 位深 | 16-bit（int16）或 32-bit float |
| 缓冲区大小 | 任意，建议每次 100ms（@16kHz 即 1600 个 sample） |
| 调用线程 | 同一录音线程，不要从多线程并发调用 |

## 7. 解码方式选择

SDK 当前支持两种解码方式（transducer 模型）：

| DecodingMethod | manifest 取值 | 速度 | WER（相对 greedy） | 内存（相对 greedy） | 推荐场景 |
| --- | --- | --- | --- | --- | --- |
| GREEDY_SEARCH | greedy_search | 1x（基线） | 0（基线） | 1x | 实时输入法、命令词、移动端通用、电池/CPU 敏感场景 |
| MODIFIED_BEAM_SEARCH | modified_beam_search | 约 0.5x（慢 2x） | 通常下降 0.3 - 1.0 个百分点 | 约 1 + maxActivePaths × 单 state 大小 | 离线长音频转写、对 WER 敏感、CPU 富余、可接受首包稍慢 |

挑选建议：

- 流式实时识别（按住说话、IME、车载语音）：保持默认 greedy_search。在 mid-range 手机（Snapdragon 6xx/7xx）上 greedy 已足够低延迟，beam search 多出来的 ~50 ms 延迟容易被用户感知。
- 离线整段音频转写、客服质检：可以试 modified_beam_search，maxActivePaths 默认 4 一般够用，调到 8 收益边际、CPU 占用线性增长。
- 与热词联动：modified_beam_search 对热词分数更敏感，调高 hotwordsScore（如 2.0）配合 beam search 在领域词上效果更好。
- 不要超过 maxActivePaths = 8：再大几乎只增内存，WER 不再下降。

### 7.1 三种设置入口与优先级

效力按从高到低：

1. 调用方 Builder 显式设置（最高）
2. modelDir/manifest.json 的 decoding_method / max_active_paths
3. Builder 默认值（GREEDY_SEARCH / 4）

调用方在代码中显式调用 `.decodingMethod(...)`：

```kotlin
val config = AsrConfig.Builder(modelDir)
    .decodingMethod(DecodingMethod.MODIFIED_BEAM_SEARCH)
    .maxActivePaths(4)
    .build()
```

如果调用方没显式设置，SDK 会读 modelDir/manifest.json 的相应字段。这条路径的好处是：运营/算法同学只更新 CDN 上的 manifest.json，App 不发版即可切换解码方式。manifest.json 的字段示例：

```json
{
  "decoding_method": "modified_beam_search",
  "max_active_paths": 4
}
```

字段缺失或值不合法（不在 [greedy_search, modified_beam_search]、max_active_paths 不在 [1, 32]）会被忽略并打印一条 WARN 日志，回退到 Builder 默认。

加载完成后，可以从 logcat tag AsrSdk 看到 SDK 当前选择：

```
AsrSdk: manifest overrides: model_type=zipformer, decoding_method=GREEDY_SEARCH, max_active_paths=(none)
AsrSdk: effective decoding=GREEDY_SEARCH maxActivePaths=4 (decodingExplicit=false, maxActiveExplicit=false)
```

### 7.2 切换是否需要重启引擎

是。AsrConfig 不可变，切换解码方式需要：

```kotlin
engine.close()
val newConfig = AsrConfig.Builder(modelDir)
    .decodingMethod(DecodingMethod.MODIFIED_BEAM_SEARCH)
    .build()
engine = AsrEngine(newConfig)
```

但 模型不重新加载 ：sherpa-onnx 的 OnlineRecognizer 会复用已经驻留内存的 ONNX session，所以切换解码方式只额外消耗 < 100 ms 的 config 重建时间。

## 8. 完整公开 API 速查

| 类型 | 关键方法 | 备注 |
| --- | --- | --- |
| AsrSdk (object) | init / release / version | 全局入口；进程内一次 |
| AsrSdkOptions | logLevel / httpTimeoutMs | 全局配置 |
| AsrConfig.Builder | numThreads / enableEndpoint / hotwords / enableVad / decodingMethod / build | 链式构造 |
| AsrEngine | newSession / close | 一份模型，可创建多 session |
| AsrSession | acceptPcmFloat / acceptPcmShort / stop / close | 单次识别 |
| AsrCallback | onPartial / onFinal / onEndpoint / onError | 回调接口 |
| AsrError | code / message / cause | 错误体 |
| AsrErrorCode | 常量集合 | 见第 8 节 |
| ModelManager | listLocal / ensure / delete / localPath | 模型管理 |
| ModelDescriptor | fromJson | manifest 解析 |

更详细的 API 文档由 Dokka 生成；见 `docs/API_DOC_BUILD.md`。

## 9. 错误码表

| 区段 | 名称 | 触发条件 |
| --- | --- | --- |
| 0 | OK | 正常 |
| 1001 | INVALID_CONFIG | AsrConfig.Builder.build 时参数非法 |
| 1002 | INVALID_ARGUMENT | 公开 API 入参非法 |
| 2001 | MODEL_DIR_NOT_FOUND | 传给 AsrConfig 的 modelDir 不存在 |
| 2002 | MODEL_FILE_MISSING | modelDir 内缺少必备文件 |
| 2003 | MODEL_LOAD_FAILED | OnlineRecognizer 加载失败 |
| 2004 | MODEL_VERSION_MISMATCH | 模型版本不在 SDK 兼容范围内 |
| 2005 | MODEL_CHECKSUM_FAILED | 下载文件 SHA256 校验失败 |
| 2006 | MANIFEST_PARSE_FAILED | manifest.json 解析失败 |
| 3001 | SESSION_RELEASED | 在已关闭的 session 上调用方法 |
| 3002 | SESSION_NOT_STARTED | 在 stop 之后调用 acceptPcm 等 |
| 3003 | DECODE_FAILED | native 解码层抛错 |
| 3004 | SAMPLE_RATE_MISMATCH | 投递 PCM 的采样率与配置不一致 |
| 4001 | NETWORK_FAILED | HTTP 请求失败（5xx / 连接断 / DNS 失败） |
| 4002 | DOWNLOAD_TIMEOUT | 下载超时 |
| 4003 | DOWNLOAD_CANCELLED | 调用 Cancellable.cancel 后回调 |
| 5001 | PERMISSION_DENIED | 录音权限缺失 |
| 5002 | STORAGE_FULL | 写入 filesDir 失败 |
| 9001 | NATIVE_CRASH | JNI 层抛 Throwable，被 SDK 捕获 |
| 9999 | UNKNOWN | 兜底 |

## 10. ProGuard / R8 规则

SDK 已经把所有需要保留的规则写在 AAR 内的 `consumer-rules.pro`，你 不需要 在 app 工程额外配置任何 keep 规则。

如果你启用了 R8 full mode 并发现崩溃，请按下面的最小规则补充（一般不需要）：

```pro
-keep class com.k2fsa.sherpa.onnx.** { *; }
-keep class com.yourco.asr.** { *; }
-keepclassmembers class com.k2fsa.sherpa.onnx.** {
    private long ptr;
    public long ptr;
}
```

## 11. FAQ

Q1：Sample App 启动后 进度条转个不停，最后报错 模型下载失败 怎么办？
A1：把 `MainActivity#manifestUrl` 替换为你服务端真实的 manifest.json HTTPS 地址；或者把模型手工放到 `<filesDir>/asr-models/<id>/<v>/`。

Q2：识别完全没文字 / 永远是空字符串
A2：99% 是 tokens.txt 第一行不是 `<blk> 0`。回 `tools/asr-sdk/MODEL_LAYOUT.md` 第 2 节核对。

Q3：识别延迟很高（首包 > 1.5s）
A3：先看 numThreads，建议设为 2~3；其次检查机型，老旧 CPU（< Snapdragon 660）首包 1s 是正常水准；最后试 INT8 模型（默认就是）。

Q4：偶发 NATIVE_CRASH (9001)
A4：复现并把 `adb logcat -s sherpa-onnx AsrSdk` 的日志贴给我们；通常是 PCM 格式不对（采样率 / 位深）或者 stream 在 close 之后又被复用。

Q5：能否多个 Activity 共用一个 AsrEngine？
A5：可以。把 AsrEngine 放到 Application 单例里，业务方只在自己的 Activity / Service 里 newSession 即可。模型只加载一次。

Q6：录音权限被拒怎么办？
A6：SDK 不接管录音；你需要自己处理 RECORD_AUDIO 权限（Android 23+ 是运行时权限）。建议用 `ActivityResultContracts.RequestPermission()`。

Q7：能否在后台 Service 里跑识别？
A7：可以，但要遵守 Android Foreground Service 规则：targetSdk 34 起需要在 manifest 声明 `foregroundServiceType="microphone"`，并启动 `ServiceCompat.startForeground(... FOREGROUND_SERVICE_TYPE_MICROPHONE)`。

Q8：能否输出时间戳？
A8：1.0 不在公开 API 暴露 timestamps 字段；如果你需要，1.1 会加。

Q9：能否多语种切换？
A9：1.0 一个 SDK 实例对应一个模型；切换语言请重新 `engine.close()` + 用新的 modelDir 创建新 `AsrEngine`。

## 12. 高级特性

下面 5 项能力都是 1.1 开始稳定的可选开关；不调即按默认行为，与 1.0 完全兼容。

### 12.1 多 model_type 支持

SDK 不再硬编码 transducer，会按 [manifest.json](../../tools/asr-sdk/MODEL_LAYOUT.md) 的 `model_type` 字段自动选择网络分支。当前支持：

| model_type （manifest 取值） | 枚举 | 期望文件名（按优先级匹配第一个存在的） |
| --- | --- | --- |
| zipformer / zipformer2 / transducer | TRANSDUCER | encoder.int8.onnx → encoder.onnx → encoder.fp16.onnx；decoder.onnx → decoder.int8.onnx；joiner.int8.onnx → joiner.onnx |
| paraformer | PARAFORMER | encoder.int8.onnx → encoder.onnx；decoder.int8.onnx → decoder.onnx |
| zipformer2_ctc / ctc | ZIPFORMER2_CTC | model.int8.onnx → model.onnx → model.fp16.onnx |
| nemo_ctc / nemo-ctc / nemo | NEMO_CTC | 同上 |

不带 `model_type` 字段时按 `TRANSDUCER` 处理，保持向下兼容。文件名按优先级数组匹配：INT8 优先，回落到 FP32，最后到 fp16。

### 12.2 运行时更新热词

```kotlin
// 一段话开始前，按用户最新的偏好动态切热词
session.updateHotwords(
    words = listOf("张三", "李四", "今晚八点"),
    score = 1.5f,   // score 必须与 AsrEngine 配置一致；不一致仅日志 WARN
)
```

约束：

- 仅词列表能 session 级别动态调整；`hotwords_score` 是 Engine 级属性（OnlineRecognizerConfig），运行时不能改
- 切换会丢弃当前未 final 的部分识别（建议在两段话之间调用）
- 切换异步发生在 decoder 线程；调用 `updateHotwords` 后立刻调 `acceptPcmFloat` 已经走新热词

### 12.3 同音字纠错（HomophoneReplacer）

中文场景常见："在线" → "再线"、"工业" → "公益" 这种同音错误，可以通过 sherpa-onnx 的 HomophoneReplacer 在 ASR 输出后自动改回。

```kotlin
val config = AsrConfig.Builder(modelDir)
    .enableHomophoneReplacer(
        lexicon = File(modelDir, "homophone-lexicon.txt"),
        ruleFsts = File(modelDir, "homophone.fst"),
    )
    .build()
```

文件来源：sherpa-onnx 官方提供 [中文同音字典 + FST](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/text-replacer-zh.zip)；公司可在此基础上加业务领域词扩展。建议把这两个文件随模型一起分发（放在同 modelDir 下）。

### 12.4 文本归一化（ITN）

把"二零二六年三月一号"自动转写成 "2026 年 3 月 1 号"等规则化文本：

```kotlin
val config = AsrConfig.Builder(modelDir)
    .enableInverseTextNormalization(File(modelDir, "itn-zh.fst"))
    .build()

// 多个 FST 串行应用：
.enableInverseTextNormalization(listOf(
    File(modelDir, "itn-number.fst"),
    File(modelDir, "itn-date.fst"),
))
```

构建 ITN FST 需要 sherpa-onnx Python 工具链；公司分发时建议预编译并随模型下发。

### 12.5 LM 重打分（RNN-LM rescoring）

```kotlin
val config = AsrConfig.Builder(modelDir)
    .enableLmRescoring(
        modelPath = File(modelDir, "lm.int8.onnx"),
        scale = 0.5f,   // [0.1, 1.0]
    )
    .build()
```

约束：

- 仅在 `MODIFIED_BEAM_SEARCH` 下生效；如果当前是 GREEDY_SEARCH，SDK 会自动切换（与 hotwords 协商一致）
- LM 加载会增加 ~30 ~ 80 MB 内存；首包延迟增加 ~50 ms
- LM 与训练 ASR 模型必须共用 tokens.txt（同一份 BPE）

### 12.6 优先级总表（多重设置共存时）

| 配置项 | 1) Builder 显式 | 2) manifest.json | 3) Builder 默认 |
| --- | --- | --- | --- |
| decodingMethod | .decodingMethod() | decoding_method | GREEDY_SEARCH |
| maxActivePaths | .maxActivePaths() | max_active_paths | 4 |
| model_type | （不可显式设置） | model_type | TRANSDUCER |
| hotwords | .hotwords() | （未来：hotwords_url） | 空 |
| HomophoneReplacer | .enableHomophoneReplacer() | （不在 manifest） | 关闭 |
| ITN | .enableInverseTextNormalization() | （不在 manifest） | 关闭 |
| LM rescoring | .enableLmRescoring() | （不在 manifest） | 关闭 |

如果调用方在 Builder 里传了 hotwords / LM，SDK 会自动把 decodingMethod 升级到 MODIFIED_BEAM_SEARCH，无需手动加 `.decodingMethod(MODIFIED_BEAM_SEARCH)`。但如果调用方显式选了 GREEDY_SEARCH 又同时传 hotwords / LM，build() 会立刻抛 IllegalArgumentException，避免 native 加载阶段才报错。
