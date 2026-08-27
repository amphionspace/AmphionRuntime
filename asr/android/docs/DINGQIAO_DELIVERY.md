# 鼎桥警务语音识别 SDK 交付说明

> 面向鼎桥（Dingqiao）集成的 Android 离线 ASR + 警务域增强 + 声纹能力。  
> 接口定义以 `docs/customer/语音识别SDK接口-交付批注版.md` 和 `docs/customer/语音识别SDK接口.md` 为准。
> **对外正式交付**请使用 `docs/customer/` 下脱敏文档，打包命令：`bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh`（不含公钥、不含 LICENSING.md 全文）。

交付前置资料清单见仓库根目录 [`docs/dingqiao-offline-license.md`](../../../docs/dingqiao-offline-license.md)。鼎桥需在组包前确认 SN 清单、客户 App 标识记录、可选签名证书指纹、授权功能范围、`sdkMajor`、`maintenanceUntil`、运行期限和 license 固定路径。

## 1. 模块与依赖

```
:sdk                  核心 ASR（com.amphion.asr）
:sdk-police           警务三域后处理（术语 / 车牌 / 派出所）
:sdk-dingqiao         鼎桥 API 适配（SpeechRecognizeSdk）
:samples:dingqiao-demo 交付 Demo APK（不含 cloud / batch eval）
```

依赖链：`:samples:dingqiao-demo` → `:sdk-dingqiao` → `:sdk-police` → `:sdk`

| 模块 | 包名 | 对外入口 |
|------|------|----------|
| `:sdk-dingqiao` | `com.amphion.dingqiao` | `SpeechRecognizeSdk` |
| `:sdk-police` | `com.amphion.police` | `PoliceEnhancePipeline`（由 dingqiao 内部调用） |

**不在交付范围：** `:samples:public-demo` 云端 ASR、Batch Eval；`:samples:internal-eval` 内部评测。

## 2. 交付物清单（当前 Android ASR 客户包）

| 产物 | 路径 / 命令 | 说明 |
|------|-------------|------|
| Demo Debug APK | `./gradlew :samples:dingqiao-demo:assembleDebug` | `samples/dingqiao-demo/build/outputs/apk/debug/` |
| Demo Release APK | `./gradlew :samples:dingqiao-demo:assembleRelease` | 需配置签名；release 开启 R8 |
| SDK AAR（集成用） | 见 §4 | 业务方 Gradle 依赖 `:sdk-dingqiao` 或发布 AAR |

模型与授权：

| 文件 | 用途 |
|------|------|
| 声纹模型 `eres2net.onnx` | 已内置于 `dingqiao-asr-v*.aar`，首次运行自动解包到 `setWorkPath` |
| 说话人分离模型 `pyannote-segmentation-3.0.onnx` | 已内置于 AAR，与 eres2net 一起在启用 diarization 时按需准备 |
| LAC 人名模型/字典 | 已内置于 `sdk-police`，仅对调用方 `sysGeneralLexicon` 中的人名候选做门控纠正 |
| `amphion-license.lic` | 商用授权（武装构建 AAR 时必需，见 `docs/LICENSING.md`） |

## 3. 构建环境

```bash
cd asr/android

# 单元测试（警务域 + 鼎桥适配）
./gradlew :sdk-police:testDebugUnitTest :sdk-dingqiao:testDebugUnitTest

# 交付 Demo
./gradlew :samples:dingqiao-demo:assembleDebug
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

### 4.1 交付打包脚本（AmphionRuntime 仓库根目录执行）

| 脚本 | 用途 |
|------|------|
| `asr/tools/delivery/pack_dingqiao_customer_delivery.sh` | 鼎桥正式发包（fat AAR + Demo + 客户文档） |
| `asr/tools/delivery/pack_dingqiao_delivery_scheme_a_aligned.sh` | 内部预览（fat AAR 与 Demo 同 AAR 对齐） |
| `asr/tools/delivery/pack_dingqiao_delivery.sh` | 内部 scheme A（含 LICENSING 等） |
| `asr/tools/delivery/pack_dingqiao_delivery_scheme_b.sh` | 三 AAR 分模块 scheme B |
| `asr/tools/delivery/merge_dingqiao_fat_aar.sh` | 仅合并 fat AAR |
| `asr/tools/delivery/verify_dingqiao_delivery.sh` | 校验 VERSION.txt / AAR 与 Demo APK native 库 / 交付目录含 `docs/NOTICE` |
| `tools/delivery/verify_delivery_zip_e2e.sh` | 通用 zip-only 验证；只以最终 zip 为输入，解压后校验 AAR/APK/license/声纹模型，可选安装 Demo 和运行 demo-src 设备测试，并生成验收报告 |

**构建溯源（强制）**

1. 在 **AmphionRuntime git 仓库**内打包；`VERSION.txt` 写入 `git_commit_full`（40 字符）+ `git_commit`（短 hash），且 **本地必须能 `git cat-file -e` 该 commit**。
2. `sdk_version` / `buildconfig_sdk_version` 均来自 **`gradle.properties` → `AMPHION_RUNTIME_VERSION`**，打包前校验与 `BuildConfig.SDK_VERSION` 一致。
3. fat AAR 内嵌 `META-INF/amphion-dingqiao-build.properties`（与 VERSION.txt 同批 git/sdk 信息）。
4. 正式客户包脚本必须用严格模式拷贝 `arm64-v8a` native 库，缺少构建产物时直接失败。
5. fat AAR 必须包含 sherpa、ONNX Runtime、`libamphion_diarization_jni.so` 与
   `libamphion_police_jni.so`；Demo APK 必须包含对应 `lib/arm64-v8a/*.so`。缺失会导致创建引擎或
   首次说话人分离/LAC 推理失败。
6. 工作区须 **clean**（无未提交改动）；本地预览可设 `DINGQIAO_ALLOW_DIRTY=1`。
7. 交付版本号默认 = `AMPHION_RUNTIME_VERSION`（勿再手写 `0.1.0` 与 SDK `0.2.x` 混用）。

```bash
# 正式发包（仓库根）
bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh

# 验收同事收到的包
bash asr/tools/delivery/verify_dingqiao_delivery.sh delivery/.../VERSION.txt
bash asr/tools/delivery/verify_dingqiao_delivery.sh delivery/.../aar/dingqiao-asr-v*.aar
bash asr/tools/delivery/verify_dingqiao_delivery.sh delivery/.../amphion-dingqiao-*-customer/
bash asr/tools/delivery/verify_dingqiao_delivery.sh delivery/.../amphion-dingqiao-*.zip

# 最终交付验收必须从 zip 开始；设备验证也安装 zip 解压出的 Demo APK
ZIP=delivery/.../amphion-dingqiao-*.zip
export DELIVERY_VERIFY_REQUIRED_AAR_ENTRIES='jni/arm64-v8a/libsherpa-onnx-jni.so:1,jni/arm64-v8a/libonnxruntime.so:1,jni/arm64-v8a/libamphion_diarization_jni.so:1,jni/arm64-v8a/libamphion_police_jni.so:1,assets/amphion-dingqiao/eres2net.onnx:31457280,assets/amphion-dingqiao/pyannote-segmentation-3.0.onnx:5242880,assets/lac/v1/lac_encoder.onnx:20971520'
export DELIVERY_VERIFY_REQUIRED_APK_ENTRIES='lib/arm64-v8a/libsherpa-onnx-jni.so:1,lib/arm64-v8a/libonnxruntime.so:1,lib/arm64-v8a/libamphion_diarization_jni.so:1,lib/arm64-v8a/libamphion_police_jni.so:1,assets/amphion-dingqiao/eres2net.onnx:31457280,assets/amphion-dingqiao/pyannote-segmentation-3.0.onnx:5242880,assets/lac/v1/lac_encoder.onnx:20971520,assets/amphion-license.lic:1'
export DELIVERY_VERIFY_LICENSE_ENTRY='assets/amphion-license.lic'
export DELIVERY_VERIFY_LICENSE_FEATURES='ASR'
export DELIVERY_VERIFY_LICENSE_DEVICE_HASH_COUNT=0
export DELIVERY_VERIFY_ANDROID_PACKAGE='com.amphion.dingqiao.demo'
export DELIVERY_VERIFY_DEVICE_READY_TEXT='引擎就绪'
export DELIVERY_VERIFY_DEVICE_MODEL_PATH='/sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/eres2net.onnx'
export DELIVERY_VERIFY_FORBIDDEN_RELATIVE_PATHS='models/eres2net.onnx'
DELIVERY_VERIFY_DEVICE=1 bash tools/delivery/verify_delivery_zip_e2e.sh "$ZIP"

# 强校验：同时从 zip 内 demo-src 工程运行声纹自动解包 / 注册测试
DELIVERY_VERIFY_DEVICE=1 \
DELIVERY_VERIFY_SOURCE_TEST=1 \
DELIVERY_VERIFY_SOURCE_DIR='demo-src' \
DELIVERY_VERIFY_SOURCE_GRADLE_TASK=':sample-dingqiao-demo:connectedDebugAndroidTest' \
DELIVERY_VERIFY_SOURCE_GRADLE_ARGS='-Pandroid.testInstrumentationRunnerArguments.class=com.amphion.dingqiao.demo.DingqiaoEmbeddedVoiceprintModelInstrumentedTest' \
  bash tools/delivery/verify_delivery_zip_e2e.sh "$ZIP"
```

**第三方开源声明（NOTICE）**

正式客户包与 scheme A aligned 预览包的 `docs/NOTICE` 来自 `asr/android/docs/customer/NOTICE`（打包时由 `dingqiao_stage_customer_docs` 复制）。内部 scheme A/B 包使用 `asr/android/NOTICE`。随包分发，满足 sherpa-onnx（Apache-2.0）、ONNX Runtime（MIT）、silero-vad（MIT）、3D-Speaker eres2net（Apache-2.0）等组件的常规合规要求；WeTextProcessing（ITN）亦在 NOTICE 中列出。

| 客户包 `docs/` 文件 | 说明 |
|---------------------|------|
| `语音识别SDK接口.md` | API 契约 |
| `DINGQIAO_INTEGRATION.md` | 集成说明 |
| `LICENSE.md` | 商用授权接入（不含验签公钥） |
| `NOTICE` | 第三方开源组件声明（必含） |

**Windows 解压（中文文件名）**

交付 zip 使用 `asr/tools/delivery/dingqiao_zip_utf8.py` 写入 **UTF-8 EFS**（语言编码标志位），避免 `语音识别SDK接口.md` 在 Windows 资源管理器中解压乱码。勿用 macOS 自带 `zip -r`（Info-ZIP 3.0 默认 EFS=false）。

## 5. 初始化与 API 映射

### 5.1 Android 初始化（必须）

```kotlin
SpeechRecognizeSdk.init(applicationContext)
SpeechRecognizeSdk.setWorkPath("/data/your_app/asr_work")  // 可读写目录
```

`setWorkPath` 用于：

- 声纹 embedding 持久化（`voiceprints/{voiceprintId}/`）
- 声纹模型路径：`{workPath}/eres2net.onnx`（由 SDK 从 AAR assets 自动准备）

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
| `onResult` | partial：ASR 原文；final：警务增强后文本 |
| `speakerSimilarity` | final 且启用声纹校验、有效语音达到门槛时返回；短句省略分数但仍返回识别结果，SDK 不丢弃非目标人结果 |

警务后处理顺序：**术语 → LAC 人名 → 车牌 → 派出所**（`PoliceEnhancePipeline`）。

会议模式可在 `StartParams.speakerDiarization` 传入 `SpeakerDiarizationConfig(maxSpeakers=1..4)`。
增量 revision 与最终说话人结果均为离线端侧计算；终态顺序固定为 last → diarization result → complete。

### 5.3 声纹

| API | 说明 |
|-----|------|
| `registerVoiceprint` | 至少 1 段样本，每段 3~8 s，PCM/WAV 16 kHz mono；多段样本可提升稳定性 |
| `deleteVoiceprint(voiceprintId)` | 删除 `{workPath}/voiceprints/{id}/` |
| 会话校验 | `startListening.extraParams`：`enableVoiceprintVerification=true`，`voiceprintIds=["vp-xxx"]` |

`TargetSpeakerConfig.minSegSec` 在鼎桥适配层固定为 `0`。只要 ASR 已确认语音、当前句有真实 PCM
且 extractor 技术上可计算，SDK 就尝试返回 `speakerSimilarity`，不按时长或相似度 reject；音频
时长、判决阈值及短句精度风险由**客户端**自行判断。

## 6. Demo 使用说明

包名：`com.amphion.dingqiao.demo`

1. 安装 APK，授予录音权限  
2. 菜单 → **声纹注册**：录至少 1 段 → **注册声纹**  
3. 主界面打开 **声纹校验** 开关 → 开始识别 → final 行显示增强文本与相似度  
4. 删除声纹：主界面菜单 **删除声纹**，或注册页 **删除已注册声纹**（调用 `deleteVoiceprint`）

工作目录默认：`getExternalFilesDir()/dingqiao_work/`

## 7. 能力与默认行为（当前交付口径）

- 语种：`zh-CN`（映射内部 `AsrLanguage.ZH_EN`）
- 离线 only；警务三场景 normalize **默认开启**
- FST 后处理默认关（可在 `sdk-police` prefs 层扩展）
- 系统热词：`CreateEngineParams.extraParams["sysGeneralLexicon"]`
- 离线说话人分离：会议模式按需启用，内置 pyannote segmentation + eres2net，支持重叠说话和显式降级结果
- 冷启动默认跳过 ORT INT8 prepack；如需吞吐优先可设置 `CreateEngineParams.extraParams["disablePrepack"]=false`

## 8. License 与 Release 打包

### 8.1 武装 AAR（§DELIVERY.md 3.6）

`gradle.properties` 已注入 `AMPHION_LICENSE_PUBLIC_KEY` 时，`:sdk` release 构建会启用离线验签。

```bash
cd asr/android

# 1) 若无密钥对，一次性生成（私钥写入仓库根 .secure/，不进 git）
cd ../../tools/license
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python gen_keypair.py --out-private ../../.secure/amphion-license-private.pem
# 公钥贴回 asr/android/gradle.properties → AMPHION_LICENSE_PUBLIC_KEY

# 2) 武装 AAR + 全链 release
cd ../../asr/android
./gradlew :sdk:assembleRelease :samples:dingqiao-demo:assembleRelease
```

产物：

| 文件 | 路径 |
|------|------|
| 武装 `:sdk` AAR | `sdk/build/outputs/aar/sdk-release.aar` |
| Demo Release APK | `samples/dingqiao-demo/build/outputs/apk/release/dingqiao-demo-release.apk` |

> R8：`sdk/consumer-rules.pro` 必须含 `-dontwarn java.lang.invoke.StringConcatFactory`（Java 17 字符串拼接；客户 `minifyEnabled=true` 时由 AAR 的 `proguard.txt` 注入）。fat AAR 合并脚本会拼接 sdk + sdk-police + sdk-dingqiao 三份 consumer 规则；**勿用旧版 sdk-release.aar 内嵌的 proguard.txt 代替源码 `consumer-rules.pro`**。重打 fat AAR：`bash asr/tools/delivery/merge_dingqiao_fat_aar.sh <版本>`（需先 `./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease`）。

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

`.lic` **不进 git**；构建 Release 前生成并放入 Demo assets。Demo 授权为**限期试用**（默认自签发日起 **2 个月**），记录 `com.amphion.dingqiao.demo` 包名，可绑定 Demo Release 证书 SHA-256，不绑定设备 SN；到期后 SDK 返回 `6006 LICENSE_EXPIRED`。交付打包脚本会在构建 Demo Release 前自动重签。

```bash
bash ../../asr/tools/license/issue_dingqiao_demo.sh
# → samples/dingqiao-demo/src/main/assets/amphion-license.lic
# 可选：DINGQIAO_DEMO_TRIAL_MONTHS=2（默认）调整试用月数
```

每次对外发 Demo APK 或交付 zip 前请确认已重签（`pack_dingqiao_*.sh` 已集成）。续期 = 用同一私钥对同一 Demo 证书记录重签更晚 `expiresAt` 的 `.lic`。

鼎桥客户正式包：用同一私钥，按 [`docs/DELIVERY.md`](DELIVERY.md) §11 对其 **设备 SN 清单** 单独签发；applicationId / bundleName 仅作记录，不作为授权限制。如 license 内写入 release 证书 SHA-256，则同时校验证书。当前 v3.0 正式 license 供 ASR 与 TTS 共用，`features=ASR,TTS`，并限制到期时间。

正式包如启用设备 SN 白名单，Android 鼎桥封装层会通过 `Build.getSerial()` 读取设备序列号。宿主 App 必须作为系统应用声明并获得 `android.permission.READ_PRIVILEGED_PHONE_STATE`；若权限缺失或系统返回空/`UNKNOWN`，license 激活会因设备 SN 不可用失败。不要把 SN 绑定策略套到普通安装的 Demo APK 上，否则 Demo 可能无法完成 `createEngine`。

### 8.4 Release 真机 smoke

```bash
# Release 与 Debug 签名不同，需先卸载旧包；必须安装最终 zip 解压出的 APK
ZIP=delivery/.../amphion-dingqiao-*.zip
rm -rf /tmp/dingqiao-release-smoke
unzip -q "$ZIP" -d /tmp/dingqiao-release-smoke
APK=$(find /tmp/dingqiao-release-smoke -path '*/demo/*.apk' | head -1)
adb uninstall com.amphion.dingqiao.demo
adb install -r "$APK"

# 推荐直接使用通用 zip-only 验证脚本生成报告
DELIVERY_VERIFY_DEVICE=1 bash tools/delivery/verify_delivery_zip_e2e.sh "$ZIP"
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
| [`docs/customer/DINGQIAO_INTEGRATION.md`](customer/DINGQIAO_INTEGRATION.md) | 客户向集成说明（随包复制为 `docs/DINGQIAO_INTEGRATION.md`） |
| [`docs/customer/NOTICE`](customer/NOTICE) | 第三方开源声明（随包复制为 `docs/NOTICE`） |
| [`docs/DELIVERY.md`](DELIVERY.md) | 通用 AAR 交付 SOP |
| [`docs/LICENSING.md`](LICENSING.md) | 离线授权方案 |
