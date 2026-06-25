# 鼎桥警务语音识别 SDK 集成说明（v0.1）

面向 Android 离线 ASR + 警务域增强 + 声纹。API 契约见同目录 [`语音识别SDK接口.md`](语音识别SDK接口.md)。

## 1. 交付物

| 文件 | 说明 |
|------|------|
| `aar/dingqiao-asr-v0.1.0.aar` | 集成用 SDK（含 ASR 模型、JNI、警务域、鼎桥 API） |
| `models/eres2net.onnx` | 声纹模型（约 38 MB），运行时放入 `setWorkPath` |
| `demo/*.apk` | 参考 Demo（可选，用于验收） |
| `docs/` | 接口、集成说明、商用授权（LICENSE.md）、**第三方开源声明（NOTICE）** |

商用授权文件 `amphion-license.lic` 由我方单独签发，见 [`LICENSE.md`](LICENSE.md)。

## 2. Gradle 集成

将 AAR 放入工程 `libs/`，例如：

```kotlin
dependencies {
    implementation(files("libs/dingqiao-asr-v0.1.0.aar"))
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
- 声纹模型：`{workPath}/eres2net.onnx`（请从交付包 `models/` 拷贝或自行下发）

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
| 声纹 | final 且开启校验时返回 `speakerSimilarity`；阈值由客户端判定 |

## 5. 声纹

| API | 要求 |
|-----|------|
| `registerVoiceprint` | 至少 1 段样本，每段 3～8 秒，16 kHz mono PCM/WAV；多段样本可提升稳定性 |
| `deleteVoiceprint` | 删除对应 ID 的本地 embedding |
| 会话校验 | `startListening` 的 extraParams：`enableVoiceprintVerification=true`，`voiceprintIds=["vp-xxx"]` |

## 6. Demo 验收（可选）

包名：`com.amphion.dingqiao.demo`

1. 安装 `demo/` 下 APK，授予录音权限  
2. 推送声纹模型，例如：

```bash
adb push eres2net.onnx /sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/
```

3. 菜单注册声纹 → 主界面识别 → 可选开启声纹校验  

建议验收项：启动无授权错误、识别 + 警务增强、中文 ITN、声纹注册 / 校验 / 删除。

## 7. 端侧存储（参考）

| 类别 | 约占用 |
|------|--------|
| AAR 内 ASR 模型（含双语种资产） | ~420 MB（安装包内） |
| 首次运行解包（zh-CN 常用） | ~250 MB（`filesDir`） |
| 警务域 + JNI | 已含于 AAR |
| 声纹模型（外置） | ~38 MB |

实际占用与是否启用声纹、系统是否保留 APK 内 assets 有关；与贵司约定的存储上限对比时，请明确验收口径（仅运行模型 vs 安装总占用）。

## 8. 默认行为（v0.1）

- 离线 only；警务三场景 normalize 默认开启  
- 系统热词：`CreateEngineParams.extraParams["sysGeneralLexicon"]`  

## 9. 相关文档

| 文档 | 内容 |
|------|------|
| [`语音识别SDK接口.md`](语音识别SDK接口.md) | API 契约 |
| [`LICENSE.md`](LICENSE.md) | 商用授权接入 |
| [`NOTICE`](NOTICE) | 第三方开源组件声明（sherpa-onnx / ONNX Runtime / silero-vad / 3D-Speaker 等） |
