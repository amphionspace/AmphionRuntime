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
SpeechRecognizeSdk.setLogLevel(AmphionLogLevel.INFO) // 可选；排查期在 prepareRuntime 前设置
```

特权宿主需要自行提供稳定设备 SN 时，使用与 HarmonyOS 同名的入口：

```kotlin
SpeechRecognizeSdk.init(
    applicationContext,
    LicenseDeviceIdProvider { _ -> hostDeviceSerial },
)
```

更换 provider 后必须重新执行 `setLicense -> prepareRuntime`，SDK 不会把旧授权身份复用到
新 provider。普通宿主仍可使用原有单参数 `init(applicationContext)`。

`setWorkPath` 用途：

- 声纹 embedding：`{workPath}/voiceprints/{voiceprintId}/`
- 声纹模型：SDK 会自动把内置 `eres2net.onnx` 准备到 `{workPath}/eres2net.onnx`
- 会议说话人分离：按需准备 `pyannote-segmentation-3.0.onnx`，PCM 仅写入 App 私有临时目录

首次启动会将 AAR 内 ASR 模型解包到 App 私有目录，耗时数秒至数十秒，属正常现象。
`setLogLevel` 默认为 `WARN`；它只影响日志阈值，不改变 ASR 或生命周期语义。

需要采集问题现场时，由我方单独提供 diagnostics 变体 AAR。普通交付 AAR 即使调用已废弃的
`configureDiagnostics` 也不会开启采集；diagnostics AAR 使用
`SpeechRecognizeSdk.exportDiagnostics(callback)` 异步导出匿名事件、callback/timeline、资源采样、
崩溃恢复信息、model/build identity 和有界 PCM/WAV。
定位完成后必须换回正式 AAR。

## 4. 识别流程

```
createEngine → setListener → startListening
  → writeAudio(DINGQIAO_AUDIO_FRAME_BYTES_20MS 字节 PCM / 20 ms) × N
  → finish
  → onResult(isFinal=true, 警务增强后文本)
  → onComplete
```

| 要点 | 说明 |
|------|------|
| 语种 | `zh-CN`（离线中英 ASR） |
| partial | ASR 原文 |
| final | 默认返回警务增强后文本（术语 → 车牌 → 派出所）；会话显式关闭增强时返回原始 ASR 文本 |
| 声纹 | final 且开启校验、有 ASR 语音证据和非空真实 PCM 时尝试返回 `speakerSimilarity`；SDK 负责出分，短句风险和阈值由客户端承担 |
| 会议说话人分离 | `StartParams.speakerDiarization=SpeakerDiarizationConfig()` 开启；完全离线，增量 revision 后返回最终 speaker turns |

每个会话可通过 `StartParams.extraParams["enablePoliceEnhancement"]` 控制警务增强。参数类型为
`Boolean`、默认 `true`；显式传 `false` 只影响该会话的 final 文本，不触发引擎重建，也不改变
partial、`isFinal`、`isLast` 或 `onComplete` 时序。

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

## 7. Android / HarmonyOS 0.3.11 对齐状态

| 能力 | Android 当前交付 | HarmonyOS 0.3.11 |
|------|-----------------|------------------|
| short/long、连续识别 | 支持，待最终真机发布门禁 | 支持 |
| 声纹校验、Speaker VAD | 支持，结果字段为 `speakerSimilarity` | 支持 |
| Police 车牌/派出所/术语 | 与 HarmonyOS 公共资产逐文件一致 | 支持 |
| Police 人名 LAC 纠正 | 相同模型/CRF/字典/拼音资产，`sysGeneralLexicon` 候选 | 支持 |
| 离线 Speaker Diarization | 相同 segmentation/embedding 模型、分窗与聚类语义 | 支持端侧离线分离 |
| Diagnostics | 专用 diagnostics 变体支持 schema v2、资源采样、崩溃恢复与 provenance | 专用 diagnostics 构建完整支持 |

Android 不返回假说话人、复用上一句结果或联网上传 PCM。代码/模型能力已对齐；正式命名为 0.3.11
前仍须完成断网、资源预算和生命周期真机门禁。

## 8. 端侧存储（参考）

| 类别 | 约占用 |
|------|--------|
| AAR 内 ASR 模型（含双语种资产） | ~420 MB（安装包内） |
| 首次运行解包（zh-CN 常用） | ~250 MB（`filesDir`） |
| 警务域 + JNI | 已含于 AAR |
| 声纹模型（内置于 AAR，首次运行解包） | ~38 MB |
| Speaker Diarization segmentation（内置、按需解包） | ~5.7 MB |
| Police LAC 人名模型与字典（内置、按需解包） | ~33 MB |

实际占用与是否启用声纹、系统是否保留 APK 内 assets 有关；与贵司约定的存储上限对比时，请明确验收口径（仅运行模型 vs 安装总占用）。

## 9. 默认行为（v3.0）

- 离线 only；警务三场景 normalize 默认开启  
- 系统热词：`CreateEngineParams.extraParams["sysGeneralLexicon"]`  

## 10. 相关文档

| 文档 | 内容 |
|------|------|
| [`语音识别SDK接口.md`](语音识别SDK接口.md) | API 契约 |
| [`LICENSE.md`](LICENSE.md) | 商用授权接入 |
| [`NOTICE`](NOTICE) | 第三方开源组件声明（sherpa-onnx / ONNX Runtime / silero-vad / 3D-Speaker 等） |
