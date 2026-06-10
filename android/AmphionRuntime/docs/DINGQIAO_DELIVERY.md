# 鼎桥警务语音识别 SDK 交付说明

> 面向鼎桥（Dingqiao）集成的 Android 离线 ASR + 警务域增强 + 声纹能力。  
> 接口定义见仓库根目录 [`语音识别SDK接口.md`](../../../../语音识别SDK接口.md)（相对本文件：`/Users/amphion/Desktop/work/projects/鼎桥/语音识别SDK接口.md`）。

## 1. 模块与依赖

```
:sdk                  核心 ASR（com.amphion.asr）
:sdk-police           警务三域后处理（术语 / 车牌 / 派出所）
:sdk-dingqiao         鼎桥 API 适配（SpeechRecognizeSdk）
:sample-dingqiao-demo 交付 Demo APK（不含 cloud / batch eval）
```

依赖链：`:sample-dingqiao-demo` → `:sdk-dingqiao` → `:sdk-police` → `:sdk`

| 模块 | 包名 | 对外入口 |
|------|------|----------|
| `:sdk-dingqiao` | `com.amphion.dingqiao` | `SpeechRecognizeSdk` |
| `:sdk-police` | `com.amphion.police` | `PoliceEnhancePipeline`（由 dingqiao 内部调用） |

**不在交付范围：** `:sample` 云端 ASR、Batch Eval；`:sample-eval` 内部评测。

## 2. 交付物清单（v0.1）

| 产物 | 路径 / 命令 | 说明 |
|------|-------------|------|
| Demo Debug APK | `./gradlew :sample-dingqiao-demo:assembleDebug` | `sample-dingqiao-demo/build/outputs/apk/debug/` |
| Demo Release APK | `./gradlew :sample-dingqiao-demo:assembleRelease` | 需配置签名；release 开启 R8 |
| SDK AAR（集成用） | 见 §4 | 业务方 Gradle 依赖 `:sdk-dingqiao` 或发布 AAR |

额外文件（需单独下发，不打进 AAR）：

| 文件 | 用途 |
|------|------|
| `eres2net.onnx` | 声纹 embedding 模型（约 27 MB），放入 `setWorkPath` 目录 |
| `amphion-license.lic` | 商用授权（武装构建 AAR 时必需，见 `docs/LICENSING.md`） |

## 3. 构建环境

```bash
cd android/AmphionRuntime

# 单元测试（警务域 + 鼎桥适配）
./gradlew :sdk-police:testDebugUnitTest :sdk-dingqiao:testDebugUnitTest

# 交付 Demo
./gradlew :sample-dingqiao-demo:assembleDebug
```

要求：JDK 17、Android SDK 34、NDK（arm64-v8a）。首次构建会解包 AAR 内 ASR 模型，耗时数分钟。

## 4. 业务方 Gradle 集成

在 `settings.gradle.kts` 中 include 模块后：

```kotlin
dependencies {
    implementation(project(":sdk-dingqiao"))
}
```

若只分发 AAR，需同时提供 `:sdk`、`:sdk-police`、`:sdk-dingqiao` 三个 library 的 release AAR（或合并为单一 fat AAR，需自行脚本打包）。当前工程未配置 `:sdk-dingqiao` 的 `maven-publish`，正式交付前需补发布任务或拷贝 `build/outputs/aar/*.aar`。

## 5. 初始化与 API 映射

### 5.1 Android 初始化（必须）

```kotlin
SpeechRecognizeSdk.init(applicationContext)
SpeechRecognizeSdk.setWorkPath("/data/your_app/asr_work")  // 可读写目录
```

`setWorkPath` 用于：

- 声纹 embedding 持久化（`voiceprints/{voiceprintId}/`）
- 声纹模型路径：`{workPath}/eres2net.onnx`

### 5.2 识别主链

```
createEngine → setListener → startListening
  → writeAudio(640B/20ms) × N
  → finish
  → onResult(isFinal=true, 增强文本)
  → onComplete
```

| 鼎桥 API | 实现要点 |
|----------|----------|
| `createEngine` | `AmphionRuntime.create` + 警务热词默认全开 |
| `writeAudio` | 仅接受 640 字节 PCM 帧 |
| `finish` | 触发 final；`isLast=true` |
| `onResult` | **partial**：ASR 原文；**final**：警务增强后文本 |
| `speakerSimilarity` | final 且启用声纹校验时返回；SDK **不丢弃**非目标人结果 |

警务后处理顺序：**术语 → 车牌 → 派出所**（`PoliceEnhancePipeline`）。

### 5.3 声纹

| API | 说明 |
|-----|------|
| `registerVoiceprint` | 3~5 段样本，每段 3~8 s，PCM/WAV 16 kHz mono |
| `deleteVoiceprint(voiceprintId)` | 删除 `{workPath}/voiceprints/{id}/` |
| 会话校验 | `startListening.extraParams`：`enableVoiceprintVerification=true`，`voiceprintIds=["vp-xxx"]` |

判决阈值（典型 0.4）由**客户端**根据 `speakerSimilarity` 自行判断，SDK 不做 reject。

## 6. Demo 使用说明

包名：`com.amphion.dingqiao.demo`

1. 安装 APK，授予录音权限  
2. 推送声纹模型（示例）：

```bash
adb push eres2net.onnx /sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/
```

3. 菜单 → **声纹注册**：录 3~5 段 → **注册声纹**  
4. 主界面打开 **声纹校验** 开关 → 开始识别 → final 行显示增强文本与相似度  
5. 删除声纹：主界面菜单 **删除声纹**，或注册页 **删除已注册声纹**（调用 `deleteVoiceprint`）

工作目录默认：`getExternalFilesDir()/dingqiao_work/`

## 7. 能力与默认行为（v0.1 锁定）

- 语种：`zh-CN`（映射内部 `AsrLanguage.ZH_EN`）
- 离线 only；警务三场景 normalize **默认开启**
- FST 后处理默认关（可在 `sdk-police` prefs 层扩展）
- 系统热词：`CreateEngineParams.extraParams["sysGeneralLexicon"]`

## 8. License 与 Release 打包

### 8.1 武装 AAR（§DELIVERY.md 3.6）

`gradle.properties` 已注入 `AMPHION_LICENSE_PUBLIC_KEY` 时，`:sdk` release 构建会启用离线验签。

```bash
cd android/AmphionRuntime

# 1) 若无密钥对，一次性生成（私钥写入仓库根 .secure/，不进 git）
cd ../../tools/license
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python gen_keypair.py --out-private ../../.secure/amphion-license-private.pem
# 公钥贴回 android/AmphionRuntime/gradle.properties → AMPHION_LICENSE_PUBLIC_KEY

# 2) 武装 AAR + 全链 release
cd ../../android/AmphionRuntime
./gradlew :sdk:assembleRelease :sample-dingqiao-demo:assembleRelease
```

产物：

| 文件 | 路径 |
|------|------|
| 武装 `:sdk` AAR | `sdk/build/outputs/aar/sdk-release.aar` |
| Demo Release APK | `sample-dingqiao-demo/build/outputs/apk/release/sample-dingqiao-demo-release.apk` |

> R8 变更后若 `:sdk:minifyReleaseWithR8` 失败，见 `sdk/proguard-rules.pro`；Demo 侧 include 了 `sdk/consumer-rules.pro`。

### 8.2 Demo 签名

1. 复制 `local.properties.example` → `local.properties`  
2. 生成 keystore（仅首次，文件在 `keystore/`，已 gitignore）：

```bash
keytool -genkeypair -v -storetype PKCS12 \
  -keystore keystore/dingqiao-demo-release.jks -alias dingqiao-demo \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass <pwd> -keypass <pwd> \
  -dname "CN=Dingqiao Demo, OU=Amphion, O=Amphion, C=CN"
```

3. 在 `local.properties` 填写 `dingqiaoReleaseStoreFile` 等四项。

### 8.3 签发 Demo `.lic`

`.lic` **不进 git**；构建 Release 前生成并放入 Demo assets：

```bash
bash ../../tools/license/issue_dingqiao_demo.sh
# → sample-dingqiao-demo/src/main/assets/amphion-license.lic
```

鼎桥客户正式包：用同一私钥，按 [`docs/DELIVERY.md`](DELIVERY.md) §11 对其 **applicationId + release 证书 SHA256** 单独签发。

### 8.4 Release 真机 smoke

```bash
# Release 与 Debug 签名不同，需先卸载旧包
adb uninstall com.amphion.dingqiao.demo
adb install sample-dingqiao-demo/build/outputs/apk/release/sample-dingqiao-demo-release.apk

# 声纹模型（卸载后需重 push）
adb push eres2net.onnx /sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/

# 日志：启动后应无 code=6001/6003；AmphionRuntime 进入 LICENSED
adb logcat -s AmphionRuntime:D DingqiaoDemo:W
```

验证项：

- [x] App 正常启动（无 `IllegalStateException` / `6001` 缺 license / `6003` 验签失败）
- [x] 识别 + 警务增强 final 正常（R8 未误伤 JNI / 验签）
- [x] ITN：如「两点五八万」→「2.58万」
- [x] 声纹 register / verify / delete

部分机型若 adb 启动后被系统杀进程，请在手机上手动打开 App，并在电池优化里允许后台运行。

## 9. 验证清单

- [x] `:sdk-police:testDebugUnitTest` 通过（P0 回放）  
- [x] `:sdk-dingqiao:testDebugUnitTest` 通过  
- [x] Demo Debug 真机 smoke  
- [x] Release APK 已构建（`assembleRelease`）  
- [x] Release 真机：license + R8 + 识别链路  
- [x] 声纹：register → 校验 → delete  
- [x] `sherpa-onnx` patch 流程（`apply_sherpa_patches.sh`，upstream v1.13.1）  

## 10. 相关文档

| 文档 | 内容 |
|------|------|
| [`语音识别SDK接口.md`](../../../../语音识别SDK接口.md) | 鼎桥抽象接口（客户契约） |
| [`docs/INTEGRATION.md`](INTEGRATION.md) | 底层 `:sdk` 接入 |
| [`docs/DELIVERY.md`](DELIVERY.md) | 通用 AAR 交付 SOP |
| [`docs/LICENSING.md`](LICENSING.md) | 离线授权方案 |
