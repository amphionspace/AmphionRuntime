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
| `1002300012` | license 缺失（仅武装态） |
| `1002300013` | license 内容非法 |
| `1002300014` | license 验签未通过 |
| `1002300015` | license 的 applicationId 与宿主不一致 |
| `1002300016` | license 的签名证书与宿主不一致 |
| `1002300017` | license 已过期 |
| `1002300018` | license 绑定的设备与当前设备不一致 |

`1002300012` 起为离线授权失败码，仅当 SDK 被武装（构建期注入 license 公钥）时才可能出现。

## 12. 离线授权（License）

To B 交付的纯离线授权：ECDSA P-256 签名，绑定 applicationId / bundleName、签名证书、设备 SN 白名单、运行到期和维护期。
完整签发 / 校验流程见 `tts/tools/license/README.md`，机制细节见 `docs/LICENSE.md`。

判断 SDK 是否被武装：构建期 gradle 属性 `AMPHION_LICENSE_PUBLIC_KEY` 是否注入了公钥。

- 未武装（公钥为空，默认）：开发 / 内部构建，`init` 与 `createEngine` 不做任何校验，功能照常。
- 已武装（注入公钥）：业务方需把签发的 `.lic` 放进 app 的 `assets/`（默认文件名 `amphion-license.lic`）。ASR 与 TTS 共用同一份授权文件。

业务方可在启动时显式初始化（可选，便于尽早暴露授权问题；不调用也会在首次 `createEngine` 懒校验）：

```kotlin
TextToSpeechSdk.init(context) // 默认从 assets/amphion-license.lic 读取、ENFORCE 策略，并通过 Build.getSerial() 读取 SN
// 或显式传入自定义选项：
TextToSpeechSdk.init(
    context,
    TtsLicenseOptions(
        licenseAssetName = "amphion-license.lic",
        enforcement = LicenseEnforcement.ENFORCE,
        // 一般不需要传；仅当客户系统改用其他 SN API 时覆盖默认实现
        deviceIdProvider = TtsDeviceIdProvider { _ -> "DEVICE-SN-FROM-DINGQIAO" },
    ),
)
```

设备 SN 默认由系统应用通过 `Build.getSerial()` 读取，宿主 App 需要申请并获得 `android.permission.READ_PRIVILEGED_PHONE_STATE`。如果缺少权限或系统返回空/`UNKNOWN`，启用 SN 白名单的 license 会校验失败。

武装态下校验失败时，`init` 与 `createEngine` 抛 `TextToSpeechException`（errorCode 见上表 `1002300012`+）。
查询授权状态用于「关于」页展示：

```kotlin
val status = TextToSpeechSdk.licenseStatus() // state / customer / expiresAt / features ...
```

设备白名单绑定：鼎桥提供 SN 清单给签发方；本地自测时可用同一算法计算 SN 授权哈希：

```kotlin
val deviceHash = TextToSpeechSdk.deviceLicenseFingerprint(
    "DEVICE-SN-FROM-DINGQIAO",
    "DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71",
)
```

## 13. 混淆

SDK AAR 自带 `consumer-rules.pro`，只保留公开 API（`com.lits.tts.sdk.*`）。宿主 App 开启 R8/minify
时 Gradle 会自动合并这些规则。**SDK 库自身的 release 构建不做 minify/混淆**（本模块未配置
`isMinifyEnabled`），因此 AAR 内 `com.lits.tts.sdk.internal.*`（含离线 license 验签逻辑）以未混淆形式交付；
如需混淆这部分，由宿主 App 的 R8 在其 release 构建时完成（未被 `consumer-rules.pro` 保留的 internal
类会随宿主构建被混淆）。交付前应至少跑一次宿主 App release 构建和真机合成 smoke。
