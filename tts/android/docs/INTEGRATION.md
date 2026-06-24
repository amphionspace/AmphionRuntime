# Lits TTS Android SDK 集成说明

## 1. 环境要求

| 项 | 要求 |
| --- | --- |
| Android minSdk | 24 |
| 推荐 compileSdk | 34 |
| ABI | `arm64-v8a` |
| 模式 | 离线 `RunMode.OFFLINE` |
| 网络权限 | 不需要 |

SDK AAR 已包含模型资源、ONNX Runtime Java 类和 arm64 native 库。宿主 App 不需要额外下载模型。

## 2. Gradle 接入

源码工程默认产物文件名是 `sdk-release.aar`。如果你在对外交付前把它重命名成 `lits-tts-sdk-0.1.0.aar`，下面的接入示例可以直接照抄；如果没重命名，就把依赖里的文件名改成 `sdk-release.aar`。

把 `lits-tts-sdk-0.1.0.aar` 放到宿主 App 的 `app/libs/` 后添加依赖：

```kotlin
dependencies {
    implementation(files("libs/lits-tts-sdk-0.1.0.aar"))
    implementation("org.jetbrains.kotlin:kotlin-stdlib:1.9.22")
}
```

说明：AAR 使用 Kotlin 编译，本地 `files(...)` 方式接入时不会自动携带 Maven 传递依赖。宿主 App 如果已经通过 Kotlin Android 插件引入 `kotlin-stdlib`，可使用项目内已有版本。

推荐宿主 App 避免压缩 ONNX 模型资源，降低首次安装/解包成本：

```kotlin
android {
    androidResources {
        noCompress += listOf("onnx")
    }
}
```

## 3. 工作目录

SDK 首次创建引擎时会把 AAR 内置模型资源安装到可读写目录，再从文件路径创建 ONNX Runtime session。

```kotlin
TextToSpeechSdk.setWorkPath(File(filesDir, "lits-tts").absolutePath)
```

要求：

- `setWorkPath` 应在 `createEngine` 之前调用。
- 不调用时，SDK 使用宿主 App 默认内部目录：`filesDir/lits-tts-runtime`。
- 已经存在 active engine 后再调用 `setWorkPath` 会抛 `TextToSpeechException(INTERNAL_SERVICE_ERROR)`。

## 4. 创建与预加载

`createEngine` 会同时加载模型。建议 App 打开后立即调用 callback 版接口做预加载，不要等用户点击合成时才加载。

```kotlin
TextToSpeechSdk.createEngine(
    CreateEngineParams(
        language = "zh-en",
        mode = RunMode.OFFLINE,
        voiceId = "lits-female-01",
        modelLoadOnCreate = true,
    ),
    object : Callback<TextToSpeechEngine> {
        override fun onSuccess(result: TextToSpeechEngine) {
            engine = result
            engine.setListener(listener)
        }

        override fun onError(errorCode: Int, errorMessage: String) {
            // 初始化失败
        }
    },
)
```

同步版 `createEngine(params)` 保留给调用方自行控制线程；不要在 Android 主线程调用同步版。

## 5. 查询音色

```kotlin
val voices = TextToSpeechSdk.listVoices(
    VoiceQuery(
        requestId = "voices-001",
        mode = RunMode.OFFLINE,
        language = null,
    ),
)
```

当前内置音色：

| language | voiceId | gender |
| --- | --- | --- |
| `zh-en` | `lits-female-01` | `Female` |
| `zh-en` | `lits-female-02` | `Female` |
| `en-US` | `lits-female-01` | `Female` |
| `en-US` | `lits-female-02` | `Female` |

同一个 `voiceId` 会在不同 `language` 下重复出现，表示同一 speaker 支持多套前端语言规则；创建引擎时切换 `language` 不要求切换 `voiceId`。

## 6. 注册监听器

必须在 `speak` 前设置监听器，否则无法接收合成/播放事件。

```kotlin
engine.setListener(object : SpeakListener {
    override fun onStart(requestId: String, response: StartResponse) {
    }

    override fun onData(requestId: String, audio: ByteArray, response: SynthesisResponse) {
    }

    override fun onComplete(requestId: String, response: CompleteResponse) {
    }

    override fun onStop(requestId: String, response: StopResponse) {
    }

    override fun onError(requestId: String, errorCode: Int, errorMessage: String) {
    }
})
```

`SpeakListener` 回调由 SDK 内部异步派发，不保证在 Android 主线程。更新 UI 时请切回主线程。

`onStart` 的 `StartResponse.loadProfileInfo` 会返回引擎加载阶段的调试耗时，例如模型资源安装/发现、前端词典预加载、ORT session 创建总耗时和各 ONNX session 创建耗时。该字段用于定位首次加载慢的问题，格式可能随调试需求调整。

调试流式首包和 RTF 时，`SpeakParams.extraParams["streamingChunkSize"]` 可覆盖本次请求的 manifest 默认 chunk size。该参数主要用于 Sample 和性能实验，传入非法值时 SDK 会回退到 manifest 默认值。

## 7. 合成模式

### 7.1 SDK 内部播放

```kotlin
engine.speak(
    "您好，有什么可以帮您？",
    SpeakParams(
        requestId = "play-001",
        playType = PlayType.SYNTHESIZE_AND_PLAY,
    ),
)
```

回调时序：

```text
onStart
onComplete(SYNTHESIS_COMPLETE)
onComplete(PLAYBACK_COMPLETE)
```

`SYNTHESIZE_AND_PLAY` 默认不通过 `onData` 返回 PCM。

### 7.2 仅合成

```kotlin
engine.speak(
    "hello world",
    SpeakParams(
        requestId = "pcm-001",
        playType = PlayType.SYNTHESIZE_ONLY,
    ),
)
```

回调时序：

```text
onStart
onData(sequence=0..n)
onComplete(SYNTHESIS_COMPLETE)
```

`onData` 返回 16 kHz、16-bit、mono PCM 分片，`sequence` 从 0 递增。

### 7.3 性能指标

`onComplete(SYNTHESIS_COMPLETE)` 的 `CompleteResponse` 会携带合成性能指标：

- `firstPacketMs`：从开始处理请求到首个 PCM chunk 生成的耗时；SDK 内部播放模式也会返回该值。
- `synthesisMs`：本次合成总耗时，不包含后续完整播放等待。
- `audioDurationMs`：生成音频时长，按 PCM 字节数和采样率计算。
- `rtf`：`synthesisMs / audioDurationMs`，小于 1 表示合成快于实时播放。
- `profilingInfo`：调试用分段耗时文本，流式模型下包含 frontend、hidden encoder、decoder、vocoder、chunk 数和模型 chunk size。

## 8. 播放通道

`SpeakParams.soundChannel` 仅在 `playType = SYNTHESIZE_AND_PLAY` 时生效。Android 版将该字段解释为 `AudioManager.STREAM_*` legacy stream type。

```kotlin
engine.speak(
    "闹钟提醒",
    SpeakParams(
        requestId = "alarm-001",
        playType = PlayType.SYNTHESIZE_AND_PLAY,
        soundChannel = AudioManager.STREAM_ALARM,
    ),
)
```

不传 `soundChannel` 时，SDK 使用平台默认媒体播放通道。

## 9. 停止与释放

```kotlin
engine.stop()
engine.shutdown()
```

- `stop()` 停止当前合成/播报并清空队列，不销毁引擎。
- `shutdown()` 释放模型、线程和播放资源；调用后该 engine 不可再使用。

## 10. 专有名词输入建议

当前前端对普通中英文句子可直接处理，但对品牌名、产品名、人名、地名等专有名词不保证总能得到最自然读音。接入方如果对发音稳定性有要求，建议按下面规则约束输入写法：

- 英文专有名词优先写成词典更容易覆盖的形式，避免把多个单词直接黏连成一个新词，例如优先用 `Harmony OS`，不要默认依赖 `HarmonyOS`。
- 如果业务允许，优先使用已经约定好的中文写法或更稳定的可读写法，避免只依赖模型自行猜测品牌词读音。
- 新增高频专有名词前，建议在目标机型上做一次真实试听；同一个词在 `zh-en` 和 `en-US` 两种语言上下文里的效果可能不同。
- 如果某个高频词必须固定读法，应在交付模型包的前端词典中补充，而不是只在业务层假设模型一定能读对。

已知原因：

- 中文专有名词主要依赖 `chinese_lexicon.txt`。
- 英文单词和缩写主要依赖 `cmudict.txt`。
- 词典未覆盖时，英文词可能退化成逐字母拼读，中文词可能退化成按字读。

## 11. 常见错误码

| 错误码 | 含义 |
| --- | --- |
| `1002300001` | 文本为空或长度超出 1..10000 |
| `1002300002` | 语种不支持 |
| `1002300003` | 音色不支持 |
| `1002300005` | 创建引擎失败 |
| `1002300006` | 单进程引擎实例数达到上限 |
| `1002300007` | 引擎未初始化 |
| `1002300008` | 引擎已销毁 |
| `1002300009` | 内部服务错误 |
| `1002300010` | 队列已满，当前实现未启用该限制 |
| `1002300011` | 合成/播报运行时异常 |

## 12. 混淆

SDK AAR 自带 `consumer-rules.pro`。宿主 App 开启 R8/minify 时，Gradle 会自动合并这些规则。交付前应至少跑一次宿主 App release 构建和真机合成 smoke。
