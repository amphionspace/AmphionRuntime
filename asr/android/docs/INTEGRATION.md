# AmphionRuntime 集成指南

适用 SDK 版本：0.2.0

> 0.2.0 是一次破坏性升级：所有模型已经打进 AAR、API 收敛到 4 个公开类。如果你之前接的是 0.1.x，请先看 [CHANGELOG](CHANGELOG.md) 的 Breaking 段。

## 1. 环境要求

| 项 | 最低 | 推荐 |
| --- | --- | --- |
| Android API Level (minSdk) | 24 (Android 7.0) | 24+ |
| Android API Level (targetSdk) | 33 | 34 |
| Android Gradle Plugin | 8.0 | 8.4 |
| Gradle | 8.0 | 8.6 |
| Kotlin | 1.8 | 1.9 |
| ABI | arm64-v8a | arm64-v8a |
| 设备最小可用堆 | 1 GB | 2 GB |
| 安装空间 | 320 MB | 512 MB |

不支持 x86 / x86_64 / armeabi-v7a。如需 armeabi-v7a 请联系我们提供专门构建。

## 2. 引入依赖

### 方案 A：AAR 直接放 libs/

把 `amphion-runtime-0.2.0.aar` 拷到你 app 工程的 `libs/`：

```kotlin
dependencies {
    implementation(files("libs/amphion-runtime-0.2.0.aar"))
    implementation("androidx.core:core-ktx:1.13.1")
}
```

### 方案 B：本地 Maven 仓库

发布到本地 Maven：

```bash
cd asr/android
./gradlew :sdk:publishReleasePublicationToLocalFileRepoRepository
# 输出：sdk/build/maven-repo/com/amphion/amphion-runtime/0.2.0/
```

在你 app 的 `settings.gradle.kts`：

```kotlin
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        maven { url = uri("file:///path/to/sdk/build/maven-repo") }
    }
}
```

`build.gradle.kts`：

```kotlin
dependencies {
    implementation("com.amphion:amphion-runtime:0.2.0")
}
```

## 3. 权限

```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
```

`RECORD_AUDIO` 是运行时权限，需要在 Activity 里申请。SDK 自身不接管 `AudioRecord`，业务方负责录音并把 PCM 喂进来。

> 0.2.0 起 SDK 不再做任何网络请求，因此 `INTERNET` / `ACCESS_NETWORK_STATE` 权限**不再需要**。

## 4. 初始化 + 预热（推荐 preload）

在 `Application.onCreate` 调一次：

```kotlin
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        AmphionRuntime.init(this)

        // 推荐：splash / onboarding 阶段预加载所有要用到的语言；后续 create 命中池 0 延迟
        Thread {
            AmphionRuntime.preload(
                this,
                listOf(AsrLanguage.ZH_EN, AsrLanguage.YUE_EN),
            ) { stage, percent ->
                // stage ∈ {"install", "shared", "asr-ZH_EN", "asr-YUE_EN"}
            }
        }.start()
    }
}
```

`init` 是必须的；`preload` / `preInstall` 是可选的。三种路径区别：

| 路径 | 触发后做的事 | 占内存 | 切语言耗时 |
| --- | --- | --- | --- |
| 仅 init | 什么都不做 | ~0 | 第一次 create 1~3s + 解包 5~30s |
| init + preInstall | 把模型解包到磁盘 | ~0（不加载 native） | 第一次 create 1~3s |
| init + preload（推荐） | 解包 + 加载 N 个语言到 ASR 池 | ~180 MB native | 切语言 ~100 ms（VAD 重建） |

详见 §11。

## 5. 创建引擎 + 识别一段话

```kotlin
// 已经 preload 时这一步是 O(ms)；未 preload 时同步走解包 + 加载，建议放子线程
val engine = AmphionRuntime.create(
    context,
    AsrLanguage.ZH_EN,
    AsrConfig.Builder()
        .numThreads(2)
        .punctuation(true)   // 自动给 final 加标点（默认 true）
        .itn(true)           // 中文 ITN（默认 true，仅 ZH_EN 生效）
        .vad(true)           // 启用 VAD：Gate + 主动 endpoint（默认 true）
        .endpoint(true)      // 端点检测自动出 final（默认 true）
        .build(),
)

val session = engine.newSession(object : AsrCallback {
    override fun onPartial(text: String) {
        // 流式增量，UI 直接覆盖显示
    }
    override fun onFinal(text: String, confidence: Float) {
        // 一段话最终结果，已经做过 ITN + 标点
    }
    override fun onEndpoint() {
        // 端点检测命中（onFinal 之前）
    }
    override fun onError(error: AsrError) {
        // 错误码 见 §7
    }
})

// 业务自己的录音线程把 16kHz / 16-bit / 单声道 PCM 喂进来
session.acceptPcmShort(samples)
// ...
session.stop()        // 触发尾段 final
session.close()       // 释放 session
engine.close()        // 不再识别时释放 ASR / 标点 / ITN / VAD 全部 native 资源
```

## 6. 切换语言

每个 `AsrEngine` 绑定一种 [AsrLanguage]。要切到另一种语言：

```kotlin
oldEngine.close()
val newEngine = AmphionRuntime.create(context, AsrLanguage.YUE_EN)
```

- 已 `preload` 过 ZH_EN + YUE_EN：上面两步加起来 ~100 ms，肉眼无感
- 没有 preload：会同步走解包 + 加载，1~3 秒，建议放子线程

详细机制见 §11。

## 7. 错误码

| 区段 | 含义 |
| --- | --- |
| 1xxx | 调用约定（参数 / 状态） |
| 2xxx | 资源（首次安装失败） |
| 3xxx | 运行时（识别 / 后处理） |
| 6xxx | 商用授权 license（仅武装构建；通过 init 抛异常，见 §14） |
| 9xxx | native 兜底 |

| 常量 | 取值 | 触发场景 |
| --- | --- | --- |
| INVALID_ARGUMENT | 1001 | 参数越界 / 非法 |
| SDK_NOT_INITIALIZED | 1002 | 用了 SDK 但忘了 init |
| SESSION_ALREADY_CLOSED | 1003 | 用了已 close 的 session / engine |
| LANGUAGE_UNAVAILABLE | 2001 | 当前 SDK 版本不支持你传入的 AsrLanguage |
| ASSET_INSTALL_FAILED | 2002 | 首次解包模型失败 |
| STORAGE_INSUFFICIENT | 2003 | filesDir 写不下 |
| DECODE_FAILED | 3001 | 识别过程异常 |
| POSTPROCESS_FAILED | 3002 | ITN 或标点过程异常（已自动降级到原文，仅日志/回调） |
| LICENSE_MISSING | 6001 | 武装构建未提供 .lic（assets 缺文件且未传 license 字符串） |
| LICENSE_MALFORMED | 6002 | .lic 格式损坏 / 缺必填字段 |
| LICENSE_SIGNATURE_INVALID | 6003 | 验签失败（被篡改或非我方签发） |
| LICENSE_APP_MISMATCH | 6004 | 保留错误码；当前正式设备白名单 license 不按 applicationId 限制宿主 |
| LICENSE_CERT_MISMATCH | 6005 | .lic 绑定的签名证书与你的不一致 |
| LICENSE_EXPIRED | 6006 | .lic 已过期 |
| NATIVE_CRASH | 9001 | native 兜底；建议 close session 重建 |

业务方一般只需要关心：
- `SDK_NOT_INITIALIZED`：忘了调 `AmphionRuntime.init`
- `ASSET_INSTALL_FAILED` / `STORAGE_INSUFFICIENT`：首次解包磁盘问题
- 其他错误码视为「重启 session 重试」即可
- `6xxx`（仅武装构建）：授权问题，按 §14 处理；常见是没放 `.lic`、设备 SN 不在白名单、或签名 / 到期不匹配

## 8. 数据格式

| 项 | 取值 |
| --- | --- |
| 采样率 | 16000 Hz（SDK 锁定，不接受其他值） |
| 通道数 | 1（单声道） |
| 采样格式 | 16-bit / float32（[-1.0, 1.0]） |
| 推荐每帧长度 | ~100 ms（@16kHz 即 1600 个 sample） |

如果你的录音是 44.1 / 48 kHz，请先在业务侧重采样到 16 kHz 再喂进 SDK。

## 9. 隐私 / 网络

SDK 不发起任何网络请求。所有模型加载、识别都在端上完成；不会上传音频或文本，也不会读取任何 ID。详见 [PRIVACY.md](PRIVACY.md)。

## 10. FAQ

### Q: AAR 太大（~280 MB）能瘦身吗？
0.2.0 的 AAR 已经把全部 5 类模型（中英 ASR / 粤英 ASR / 标点 / ITN / VAD）打进 assets。如果你的业务**不需要**某种语言或某项后处理，可以联系我们出一份精简包；模型粒度的开关都在 [AssetRegistry] 集中维护。

### Q: 第一次启动卡了 30 秒？
首次解包是阻塞的，建议在 splash 上调 `AmphionRuntime.preInstall`，把这件事提前到用户感知不到的时间。

### Q: SDK 升级后用户要重新解包吗？
是的。SDK 通过 `BuildConfig.SDK_VERSION` 维护 `install.flag`，版本变更会自动重新解包；用户无感（解包还是几十秒）。

### Q: 我可以在 Java 项目里用吗？
可以。所有公开 API 都是 Java-friendly：
- `AmphionRuntime.init(ctx)` / `AmphionRuntime.create(ctx, AsrLanguage.ZH_EN)` 直接用
- `AsrConfig.Builder()` 可链式调用
- `AsrCallback` 是 Java interface

### Q: 支持多 session 并发吗？
同一个 `AsrEngine` 可以创建多个 `AsrSession`。但每条 session 各自独立的解码线程，并发越多 CPU 占用越高，建议根据机型评估。

### Q: 怎么开 debug 日志？
```kotlin
AmphionRuntime.init(this, AmphionOptions(logLevel = AmphionLogLevel.DEBUG))
```
logcat tag = `AmphionRuntime`。

### Q: 想用自己的模型怎么办？
0.2.0 的设计目标是「一份 AAR 全程黑盒」。如果你需要替换内置模型，请联系我们走定制流程；我们会用 `asr/tools/08_pack_sdk_assets.sh` 出一份带你私有模型的专属 AAR。

### Q: VAD 开了，为什么长句子说一半还是不切分？
0.2.x 起 SDK 把 silero VAD 真正接入了流式管线（之前版本里 VAD 对象被构造但没参与解码，所以"开"和"不开"效果一样）。VAD 现在做两件事：(1) 维护 speech/silence 状态机；(2) speech 之后尾静音达到阈值时主动给 ASR 出 final。默认阈值 500 ms，比 `endpointRules.rule2MinTrailingSilenceSec` 的 1.4 秒更敏感。

如果还是觉得不够灵敏，按下面方式调小 `activeEndpointSilenceMs`：

```kotlin
val config = AsrConfig.Builder()
    .vad(true)
    .vadConfig(VadConfig(activeEndpointSilenceMs = 300))   // 300 ms 就切
    .build()
```

反之，如果误切（正常停顿被切分），可以调大到 800~1000；设 0 就退化成只有 sherpa endpoint 规则（与 0.1.x 行为一致）。

### Q: 想用 ten-vad 代替 silero？
`VadConfig.modelType` 留了 `VadModelType.TEN_VAD` 枚举位，但 **当前 AAR 没打包 ten-vad 资产**，选了会在 `AmphionRuntime.create` 时抛 `UnsupportedOperationException`。silero 在手机近场场景已足够；ten-vad 主要优势在低 SNR / 远场。需要的话联系我们出带 ten-vad 的定制 AAR。

## 11. 多语言预加载

### 11.1 使用方式

`AmphionRuntime.preload(ctx, languages, config)` 会一次性把所有语言加载到 SDK 内部的 ASR 池里。建议在 splash / onboarding 阶段调用一次：

```kotlin
val handle = AmphionRuntime.preload(
    this,
    listOf(AsrLanguage.ZH_EN, AsrLanguage.YUE_EN),
    AsrConfig.Builder()
        .numThreads(2)
        .punctuation(true)
        .itn(true)
        .vad(true)
        .endpoint(true)
        .build(),
) { stage, percent ->
    // stage ∈ {"install", "shared", "asr-ZH_EN", "asr-YUE_EN"}
    // percent: 0..100，每个 stage 各自走完整 0..100
}

// 不需要时可以 cancel；已经加载的部分保留在池里
handle.cancel()
```

### 11.2 三阶段进度

| stage | 含义 | 典型耗时（HarmonyOS 4.3） |
| --- | --- | --- |
| install | 把全部 5 类模型从 APK assets 解包到 internal storage | 首装 4~6 s；已 cache 0 s |
| shared | 加载共享 punct + itn 单例（进程级一份，跨语言共享） | 0.5~1 s |
| asr-ZH_EN / asr-YUE_EN | 并行加载每个语言的 OnlineRecognizer | 1~2 s/份（并行） |

### 11.3 与 create 的协作

| 调用 | 池命中（preload 过且 config 兼容） | 未命中 |
| --- | --- | --- |
| AmphionRuntime.create | O(ms)：池里借 recognizer + 现场建 VAD | 同步走解包 + 加载 |
| AsrEngine.close | 释放 sessions 与 VAD；recognizer 留在池里 | 释放 sessions / recognizer / VAD |
| AmphionRuntime.release | 真的清空 ASR 池 + 释放共享 punct/itn | 同左 |

### 11.4 内存预算

| 项 | 大小 | 备注 |
| --- | --- | --- |
| 共享 punct（CT-Transformer INT8） | ~70 MB | 跨语言共享一份 |
| 共享 itn（WeText fst） | ~4 MB | 仅 ZH_EN 生效；占用极小 |
| 单语言 ASR（zipformer2 INT8） | ~50 MB | 每语言一份 |
| VAD（silero） | <1 MB | per-engine，可忽略 |
| 预加载 2 语言总计 | ~180 MB native | RSS 包含 SDK 自身 .so 与 Zygote 共享部分 |

### 11.5 配置兼容性

`preload(config)` 用的 config 决定了池里 recognizer 的「线程数 / 端点 / 是否带 hotwords」。后续 `create(language, config)` 如果这些字段与 preload 一致就直接复用；否则会跳过池、单独建 recognizer，并在 logcat 打 WARN。建议保持 preload 和 create 用同一份 config builder。

## 12. 运行时指标

### 12.1 监听方式

业务方实现 `AsrCallback.onMetrics`：

```kotlin
override fun onMetrics(metrics: AmphionMetrics) {
    when (metrics.kind) {
        AmphionMetricsKind.UTTERANCE -> {
            // 每段话 onFinal 同帧派发
            // metrics.utteranceE2eLatencyMs / .firstPartialLatencyMs / .rtf / .nativeRssMb / ...
        }
        AmphionMetricsKind.SESSION -> {
            // session close 时派发一次
            // metrics.totalUtterances / .avgRtf / .p95Rtf / .peakNativeRssMb
        }
    }
}
```

不实现也没关系：所有指标都会通过 logcat 输出，调试期 `adb logcat -s AmphionMetrics` 直接拉一行 KV。

### 12.2 字段（v1，与未来鸿蒙端共用 schema）

每段 utterance（kind = UTTERANCE）：

| 字段 | 含义 |
| --- | --- |
| utteranceIndex | 该 engine 上 utterance 序号，从 1 开始 |
| utteranceDurationMs | 本段音频物理时长（pcmBytes 推导） |
| decodeDurationMs | 第一帧 PCM 进 decoder → raw final 出来；不含后处理 |
| postProcessMs | ITN + 标点合计耗时 |
| firstPartialLatencyMs | 第一帧 PCM accept → 第一个 partial；无 partial 时 -1 |
| endpointToFinalLatencyMs | endpoint 命中 → onFinal；非 endpoint 触发为 -1 |
| utteranceE2eLatencyMs | 第一帧 PCM accept → onFinal |
| rtf | decodeDurationMs / utteranceDurationMs；越小越流畅 |
| nativeRssMb | 本段结束时 native VmRSS 绝对值（MB） |
| nativeRssMbDelta | 相比上段结束时的增量；>0 持续上涨需关注泄漏 |
| pcmBytesAccepted | 本段累计 PCM 字节 |

第一段会附带启动期字段（assetInstallMs / engineReadyMs / nativeRssMbAtReady）；后续段为 -1。

session 总结（kind = SESSION）：

| 字段 | 含义 |
| --- | --- |
| totalUtterances | 该 engine 生命周期内的 utterance 总数 |
| totalPcmBytes | 累计 PCM 字节 |
| avgRtf | RTF 算术平均；样本不足 -1 |
| p95Rtf | RTF p95 分位；< 5 段时退化为最大值 |
| peakNativeRssMb | 该 engine 生命周期内 native RSS 峰值 |
| nativeRssMb | session close 时的 RSS |

### 12.3 logcat 输出

每条指标走独立 tag `AmphionMetrics`，KV 行：

```
AmphionMetrics: kind=UTTERANCE language=ZH_EN sessionId=1 utteranceIndex=1 utteranceDurationMs=1840 decodeDurationMs=120 postProcessMs=18 firstPartialLatencyMs=78 endpointToFinalLatencyMs=320 utteranceE2eLatencyMs=148 rtf=0.065 nativeRssMb=176 nativeRssMbDelta=0 pcmBytesAccepted=58880 assetInstallMs=0 assetTotalBytes=0 engineReadyMs=42 nativeRssMbAtReady=176
```

```
AmphionMetrics: kind=SESSION language=ZH_EN sessionId=1 totalUtterances=12 totalPcmBytes=720000 avgRtf=0.072 p95Rtf=0.110 peakNativeRssMb=181
```

业务方需要做 dashboard 时直接 grep 即可。SDK 自身不上报、不持久化、不跨进程——零网络、零磁盘副作用。

### 12.4 性能验收基线（HarmonyOS 4.3 / Android 12）

| 指标 | 预期 | 红线 |
| --- | --- | --- |
| preload 全部完成 | ≤ 6 s（首装） | > 12 s 视为故障 |
| 切语言 create→engine ready | ≤ 100 ms | > 500 ms 视为池失效 |
| utteranceE2eLatencyMs | ≤ 200 ms | > 500 ms 视为算力不足 |
| firstPartialLatencyMs | ≤ 200 ms | > 800 ms 视为算力不足 |
| rtf（流式） | ≤ 0.3 | > 0.8 视为跟不上实时 |
| 预加载 2 语言常驻 RSS | ≤ 200 MB | > 280 MB 视为泄漏 |

## 13. 目标说话人（可选）

> 0.2.x 的可选增量能力，默认不启用、不影响现有接入。仅 Android 端提供。

### 13.1 能做什么

开启后，SDK 只把目标说话人说的话当作 onFinal 输出，其他人说的话改走 onFinalRejected（默认丢弃）。典型场景：嘈杂环境只转写机主、问诊 / 考试只记录特定人。

实现是输出门控（形态A）：ASR 始终流式全量识别，onPartial 不受影响；声纹只在每段话结束时对该段音频打一次分，决定这段的 onFinal 是否保留。由此带来两条语义：

- onPartial 阶段不门控（声纹需要完整语音段才稳）。开关开启时，正在进行的那段 partial 仍按原文滚动，到段末才裁决
- 开关可运行时随时切。一段话中途切换，以该段结束时刻的状态为准

### 13.2 声纹模型

需要一个声纹 embedding 模型（如 3D-Speaker eres2net，约 27 MB）。为避免给所有用户的 AAR 平白增重，该模型默认不打进 AAR，由业务自行下发到设备并提供绝对路径。模型与离线评测脚本见仓库 asr/tools/speaker/。如需把声纹模型一起打进 AAR 黑盒分发，联系我们走定制（同 §10 想用自己的模型）。

### 13.3 注册目标说话人（离线，一次性）

用 SpeakerEnroller 把多段注册音频压成一个目标向量，业务自行持久化：

```kotlin
val enroller = SpeakerEnroller(modelPath = "/data/.../eres2net.onnx")
// 建议 >=3 段、每段 5~10s、覆盖不同语速 / 距离 / 设备
val segments: List<FloatArray> = listOf(seg1Pcm, seg2Pcm, seg3Pcm) // 16k mono float
val targetEmbedding: FloatArray = enroller.enroll(segments)
enroller.close() // 注册是一次性的，用完即释放模型

// 持久化 targetEmbedding 供运行时加载
```

为什么要多段：单段注册在跨域（远场 / 方言 / 换设备）下错误率显著上升；多段取均值能同时压低短音频不稳与跨域漂移两个失败域。

### 13.4 启用能力 + 运行时开关

创建 engine 时通过 AsrConfig 声明能力（加载声纹模型），运行时用 session 三方法控制：

```kotlin
val engine = AmphionRuntime.create(
    context,
    AsrLanguage.ZH_EN,
    AsrConfig.Builder()
        .vad(true)
        .endpoint(true)
        .targetSpeaker(
            TargetSpeakerConfig(
                modelPath = "/data/.../eres2net.onnx",
                threshold = 0.30f,        // 见 13.6 标定
                preload = true,           // 随 create 即加载，开关秒级生效
                enabledByDefault = false, // 初始关
            ),
        )
        .build(),
)

val session = engine.newSession(object : AsrCallback {
    override fun onPartial(text: String) { /* 全量滚动，不门控 */ }
    override fun onFinal(result: AsrResult) {
        // 目标说话人的段（或开关关闭时的全部段）
        // result.speakerScore / result.isTargetSpeaker：开关开启且完成打分时非空
    }
    override fun onFinalRejected(result: AsrResult) {
        // 被判为非目标的段；默认丢弃，这里可自定义呈现（灰显 / 折叠）
    }
    override fun onError(error: AsrError) {}
})

session.setTargetSpeaker(targetEmbedding) // 注入注册向量
session.setTargetSpeakerEnabled(true)     // 打开门控
// ...
session.setTargetSpeakerEnabled(false)    // 关闭：恢复全量输出
session.clearTargetSpeaker()              // 清除目标：即使开关开也不过滤
```

注意 onFinal 有两个重载：onFinal(text, confidence) 与 onFinal(result: AsrResult)。目标说话人信息挂在 AsrResult 上，要拿 speakerScore / isTargetSpeaker 请实现 result 版。

### 13.5 判定逻辑（与离线评测同口径）

| 步骤 | 行为 |
| --- | --- |
| 段长 < minSegSec（默认 1.5s） | 不打分，按未判定放行（speakerScore=null，走 onFinal） |
| minSegSec ~ winSec（默认 2.5s） | 整段单次打分 |
| 段长 >= winSec | 按 winSec / hopSec 滑窗，取窗内最大余弦 |
| 余弦 >= threshold | 判为目标，走 onFinal |
| 余弦 < threshold | 判为非目标，走 onFinalRejected |

模型加载失败 / 未注册目标 / 开关关闭时，一律放行全部（门控降级，不影响 ASR 主链路）。

### 13.6 阈值标定

默认 threshold=0.30 对应离线评测的保守点（少误纳、偶有漏判）。不同声纹模型 / 机型 / 噪声环境最优阈值不同，上线前建议：

1. 用 asr/tools/speaker 的评测脚本在你的数据上跑 EER / FAR / FRR 曲线
2. 按业务偏好取点：偏好宁可漏判不可误纳取高阈值，反之取低
3. 把标定值回填 TargetSpeakerConfig.threshold

可先把 speakerScore 打到日志观察分布，再定阈值。

### 13.7 已知限制

| 限制 | 说明 |
| --- | --- |
| 仅 Android | iOS 端 VAD / 管线尚未对齐，暂不提供 |
| 段末有额外开销 | 段越长滑窗越多，段末打分在解码线程串行，长段（接近 20s）可能多花几百 ms；endpoint rule3 20s 会强制切，正常对话无感 |
| partial 不门控 | 声纹需完整段，partial 始终全量；介意的话在 UI 上等 onFinal 再定稿 |
| 单目标 | 当前一个 session 跟一个目标说话人；多目标需求联系我们 |

## 14. 商用授权 License（武装构建需要）

> 如果你拿到的是「武装构建」AAR（我方在构建期注入了 license 公钥），必须放入我方为你签发的 `.lic` 才能通过 `AmphionRuntime.init`。开发 / 评测用的未武装 AAR 不校验授权，本章可跳过；用 `AmphionRuntime.licenseStatus().state` 可判断当前 AAR 是否武装（`DEV_UNLICENSED` = 未武装）。

授权是纯离线的：SDK 用内置公钥本地验签，不发起任何网络请求，与零网络承诺一致。

### 14.1 放入 license 文件

把我方签发的 `.lic` 放到你 App 的 assets，默认文件名 `amphion-license.lic`：

```
app/src/main/assets/amphion-license.lic
```

`AmphionRuntime.init(this)` 默认会读这个文件，无需额外配置。

### 14.2 自定义来源 / 策略（可选）

```kotlin
AmphionRuntime.init(
    this,
    AmphionOptions(
        // 改 asset 文件名（默认 "amphion-license.lic"）
        licenseAssetName = "amphion-license.lic",
        // 或不放 assets，直接传 .lic 全文（优先于 asset），便于从你自己的下发通道注入
        license = null,
        // 到期宽限天数，规避设备时钟误差（默认 0）
        expiryGraceDays = 0,
        // 校验失败策略（默认 ENFORCE：失败即 init 抛异常）
        licenseEnforcement = LicenseEnforcement.ENFORCE,
        // 设备 SN 由宿主或交付适配层注入；返回值需与提供给我方签发的 SN 清单一致
        deviceIdProvider = AmphionDeviceIdProvider { _ -> "DEVICE-SN-FROM-DINGQIAO" },
    ),
)
```

如果 license 启用了设备 SN 白名单，`deviceIdProvider` 必须能返回稳定 SN；否则武装态初始化会因设备 SN 不可用或白名单不匹配而失败。鼎桥 Android 封装层已默认使用 `Build.getSerial()` 读取 SN；宿主 App 需要作为系统应用申请并获得 `android.permission.READ_PRIVILEGED_PHONE_STATE`。如果业务 App 自行集成 ASR 基础 SDK，则按上面示例注入同一个 SN。

### 14.3 查询授权状态

```kotlin
val s = AmphionRuntime.licenseStatus()
when (s.state) {
    AmphionLicenseStatus.State.LICENSED ->
        Unit // s.customer / s.expiresAt / s.installTier / s.features 可用于「关于」页展示
    AmphionLicenseStatus.State.DEV_UNLICENSED -> Unit // 未武装构建，不校验
    AmphionLicenseStatus.State.INVALID -> Unit // 仅 PERMISSIVE 模式会到达，s.errorCode 见下表
    AmphionLicenseStatus.State.NOT_INITIALIZED -> Unit // 还没 init
}
```

### 14.4 授权错误码

ENFORCE 模式下校验失败，`AmphionRuntime.init` 抛 `IllegalStateException`，message 形如 `code=6003: ...`：

| 常量 | 取值 | 触发场景 | 处理 |
| --- | --- | --- | --- |
| LICENSE_MISSING | 6001 | 没找到 .lic（assets 无该文件且未传 license 字符串） | 确认 .lic 已放进 assets |
| LICENSE_MALFORMED | 6002 | .lic 格式损坏 / 缺字段 | 向我方重新获取 |
| LICENSE_SIGNATURE_INVALID | 6003 | 验签失败（被篡改或非我方签发） | 向我方重新获取 |
| LICENSE_APP_MISMATCH | 6004 | 保留错误码；当前正式设备白名单 license 不按 applicationId 限制宿主 | 无需按包名重签 |
| LICENSE_CERT_MISMATCH | 6005 | 签名证书与 license 绑定的不一致 | 换签名证书需告知我方重签 |
| LICENSE_EXPIRED | 6006 | 已过期 | 联系我方续期 |
| LICENSE_DEVICE_MISMATCH | 6007 | 设备 SN 不可用或 SN 哈希不在白名单 | 确认 `deviceIdProvider` 返回值与授权 SN 清单一致 |
| LICENSE_SDK_MAJOR_MISMATCH | 6008 | license 授权 SDK 大版本与当前 SDK 不一致 | 使用匹配版本或重签 |
| LICENSE_MAINTENANCE_EXPIRED | 6009 | 当前 SDK 发布时间晚于维护期 | 续期后重签 |
| LICENSE_FEATURE_MISSING | 6010 | license 未授权 ASR | 使用包含 ASR 的 license |

### 14.5 常见问题

- 换了 release 签名证书：若 license 绑了 certSha256，需把新证书 SHA-256 给我方重签。
- 改了 applicationId：需用新包名重签。
- 启用了设备白名单：需在 `AmphionOptions.deviceIdProvider` 注入设备 SN，且 SN 与签发清单一致。
- 到期续期：我方重签一份更晚到期的 `.lic`，随你的 App 更新替换 assets 内文件即可，代码不动。
- 灰度上线：可临时用 `LicenseEnforcement.PERMISSIVE` 让校验失败不阻断启动（仅记录），不建议长期使用。
