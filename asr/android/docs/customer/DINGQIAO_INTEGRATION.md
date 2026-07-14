# 鼎桥警务语音识别 SDK 集成说明（v3.0）

面向 Android 离线 ASR + 警务域增强 + 声纹。API 契约见同目录 [`语音识别SDK接口.md`](语音识别SDK接口.md)。

## 1. 交付物

| 文件 | 说明 |
|------|------|
| `aar/dingqiao-asr-v3.0.aar` | 集成用 SDK（含 ASR 模型、JNI、警务域、鼎桥 API） |
| `demo/*.apk` | 参考 Demo（可选，用于验收） |
| `docs/` | 接口、集成说明、商用授权（LICENSE.md）、第三方开源声明（NOTICE） |

商用授权文件 `amphion-license.lic` 由我方单独签发，见 [`LICENSE.md`](LICENSE.md)。本次正式授权供贵司正式宿主使用，ASR 与 TTS 共用同一份 license，绑定设备 SN 清单并限制到期时间；包名仅作记录，不作为授权限制。

## 2. Gradle 集成

将 AAR 放入工程 `libs/`，例如：

```kotlin
dependencies {
    implementation(files("libs/dingqiao-asr-v3.0.aar"))
}
```

要求：**minSdk 24**，**arm64-v8a**，JDK 17，Android SDK 34。

AAR 内已包含 ProGuard / R8 消费规则；贵司 App 开启混淆时请保留 AAR 自带的 consumer rules（Gradle 通常会自动合并）。

## 3. 初始化

```kotlin
SpeechRecognizeSdk.init(applicationContext)
SpeechRecognizeSdk.setWorkPath("/data/your_app/asr_work")  // 可读写目录
```

`setWorkPath` 用途：

- 声纹 embedding：`{workPath}/voiceprints/{voiceprintId}/`
- 声纹模型：SDK 会自动把内置 `eres2net.onnx` 准备到 `{workPath}/eres2net.onnx`

首次启动会将 AAR 内 ASR 模型解包到 App 私有目录，耗时数秒至数十秒，属正常现象。

## 4. 识别流程

```
createEngine → setListener → startListening
  → writeAudio(640 字节 PCM / 20 ms) × N
  → finish
  → onResult(isFinal=true, 警务增强后文本)
  → onComplete
```

| 要点 | 说明 |
|------|------|
| 语种 | `zh-CN`（离线中英 ASR） |
| partial | ASR 原文 |
| final | 警务增强后文本（术语 → 车牌 → 派出所） |
| 声纹 | final 且开启校验、有效语音达到门槛时返回 `speakerSimilarity`；短句省略分数但仍返回识别结果，阈值由客户端判定 |

## 5. 声纹

| API | 要求 |
|-----|------|
| `registerVoiceprint` | 至少 1 段样本，每段 3～8 秒，16 kHz mono PCM/WAV；多段样本可提升稳定性 |
| `deleteVoiceprint` | 删除对应 ID 的本地 embedding |
| 会话校验 | `startListening` 的 extraParams：`enableVoiceprintVerification=true`，`voiceprintIds=["vp-xxx"]` |

## 6. Demo 验收（可选）

包名：`com.amphion.dingqiao.demo`

Demo APK 内置授权只用于体验：记录 Demo 包名，可绑定 Demo 签名，限制期限，不绑定设备 SN。正式 App 的 SDK 授权与 Demo 授权分开下发，正式授权需要绑定 SN 清单。

1. 安装 `demo/` 下 APK，授予录音权限  
2. 菜单注册声纹 → 主界面识别 → 可选开启声纹校验  

建议验收项：启动后显示引擎就绪、识别 + 警务增强、中文 ITN、声纹注册 / 校验 / 删除。若正式 App 使用 SN 绑定 license，请确认宿主系统能读取本机 SN。

注意：Demo 验收使用的是 Demo APK 内置 license，不使用单独下发给正式宿主的正式 license zip。正式 license 需要在正式宿主可读取或注入设备 SN 的条件下，在白名单设备上单独验收；如正式 license 内写入签名证书 SHA-256，也需使用匹配签名。

## 7. 端侧存储（参考）

| 类别 | 约占用 |
|------|--------|
| AAR 内 ASR 模型（含双语种资产） | ~420 MB（安装包内） |
| 首次运行解包（zh-CN 常用） | ~250 MB（`filesDir`） |
| 警务域 + JNI | 已含于 AAR |
| 声纹模型（内置于 AAR，首次运行解包） | ~38 MB |

实际占用与是否启用声纹、系统是否保留 APK 内 assets 有关；与贵司约定的存储上限对比时，请明确验收口径（仅运行模型 vs 安装总占用）。

## 8. 默认行为（v3.0）

- 离线 only；警务三场景 normalize 默认开启  
- 系统热词：`CreateEngineParams.extraParams["sysGeneralLexicon"]`  

## 9. 相关文档

| 文档 | 内容 |
|------|------|
| [`语音识别SDK接口.md`](语音识别SDK接口.md) | API 契约 |
| [`LICENSE.md`](LICENSE.md) | 商用授权接入 |
| [`NOTICE`](NOTICE) | 第三方开源组件声明（sherpa-onnx / ONNX Runtime / silero-vad / 3D-Speaker 等） |
