# Dingqiao v3 Android 批测说明

本文说明当前仓库内置的 Dingqiao v3 TTS Android 批测样例、批测代码和运行方式。批测目标是验证 SDK AAR 在真实 Android 设备上的稳定性、回调契约、资源释放、长文本、流式参数和发音正确性。

## 1. 样例文件

批测样例统一保存在：

```text
tts/android/testdata/dingqiao_batch_cases/
```

当前保留的主要版本：

| 用途 | 文件 | 行数 |
| --- | --- | --- |
| 稳定性快速批测 | `android_v3_sdk_stability_100_cases_improved_v2.jsonl` | 100 |
| 稳定性中量批测 | `android_v3_sdk_stability_424_cases_improved_v3.jsonl` | 424 |
| 稳定性完整批测 | `android_v3_sdk_stability_1000_cases_improved.jsonl` | 1000 |
| 发音正确性批测 | `pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl` | 675 |

说明：本地可找到的中量版本是 424 条，并带有对应 summary；当前仓库没有找到 432 条源文件。

为了让 Android instrumentation test 可以直接读取，Gradle 在构建时把稳定性三份 JSONL 同步到：

```text
tts/android/aarHost/build/generated/androidTestAssets/
```

发音正确性样例同步到了：

```text
tts/android/sdk/src/androidTest/assets/
```

## 2. 批测代码

稳定性 AAR 批测入口：

```text
tts/android/aarHost/src/androidTest/java/com/lits/tts/aarhost/AarStability1000DeviceTest.kt
```

发音正确性批测入口：

```text
tts/android/sdk/src/androidTest/java/com/lits/tts/sdk/internal/PronunciationRound15FrontendDeviceTest.kt
```

辅助脚本：

```text
tts/tools/android/generate_v3_sdk_stability_1000_cases.py
tts/tools/android/generate_improved_v3_sdk_stability_1000_cases.py
tts/tools/android/select_improved_v3_from_v2.py
tts/tools/android/run_android_frontend_parity.py
tts/tools/android/run_android_phone_frontend_batch.py
tts/tools/android/compare_android_frontend_batch_tokens.py
```

## 3. 环境准备

进入 Android 工程目录：

```bash
cd tts/android
```

使用本机已有 JDK 17 和 Android SDK：

```bash
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk
export ANDROID_SDK_ROOT=/path/to/android-sdk
```

确保设备在线：

```bash
adb devices
```

稳定性批测会先构建 `:sdk:assembleRelease`，再用 `aarHost` 作为宿主 App 通过 `implementation(files("../sdk/build/outputs/aar/sdk-release.aar"))` 验证真实 AAR 接入路径。

### 当前 Release AAR 最小接入门禁

`AarFrontendContractDeviceTest` 只通过公开 API 验证 Release AAR 的授权、外置资源加载及一次合成请求。它不访问 SDK 内部类，也不清空调用方的资源目录。输入包含负温度、日期和跨 50 字符位置的 URL；本门禁检查回调和 PCM 格式，不替代前端 token 对照、完整发音语料或长稳压。

先按[源码编译说明](BUILD_FROM_SOURCE.md)准备模型和授权构建配置，再构建宿主及测试 APK：

```bash
./gradlew --no-daemon :aarHost:assembleDebug :aarHost:assembleDebugAndroidTest
adb install -r aarHost/build/outputs/apk/debug/aarHost-debug.apk
adb install -r aarHost/build/outputs/apk/androidTest/debug/aarHost-debug-androidTest.apk
```

宿主是 Debug 应用（便于通过 `run-as` 部署测试资源），其 SDK 依赖始终是 `sdk-release.aar`。测试页面仅存在于宿主 Debug 构建，保持前台及亮屏，不更改系统冻结策略。请先解锁手机并按系统提示确认安装。

选择专用测试目录，将 `external-resources/tts/` 放入其 `tts/` 子目录；勿使用业务数据目录。以下示例首次部署到 `files/tts-contract`，复验可直接复用已校验资源。macOS 的 `COPYFILE_DISABLE=1` 用于避免打入 AppleDouble 元数据：

```bash
adb shell run-as com.lits.tts.aarhost mkdir -p files/tts-contract
COPYFILE_DISABLE=1 tar -C external-resources -cf - tts | \
  adb shell -T run-as com.lits.tts.aarhost tar -xf - -C files/tts-contract
```

将有效且适用于本宿主的 `tts.lic` 放在应用私有目录，不要提交到 Git 或打入公开测试 APK。下例从受控的本机目录直接传入，避免落地到手机公共目录；请替换 `/secure/path`：

```bash
COPYFILE_DISABLE=1 tar -C /secure/path -cf - tts.lic | \
  adb shell -T run-as com.lits.tts.aarhost tar -xf - -C files
adb shell am instrument -w -r \
  -e class com.lits.tts.aarhost.AarFrontendContractDeviceTest \
  -e workPath /data/user/0/com.lits.tts.aarhost/files/tts-contract \
  -e licensePath /data/user/0/com.lits.tts.aarhost/files/tts.lic \
  com.lits.tts.aarhost.test/androidx.test.runner.AndroidJUnitRunner
```

必须得到 `OK (1 test)`。未注入授权公钥的 `DEV_UNLICENSED` 构建不能通过。断言要求同一 requestId 下唯一 start、连续有序且非空的 PCM、唯一 `SYNTHESIS_COMPLETE`，没有 error/stop，随后 shutdown 返回；不固定 PCM 块数或合成耗时。

日志中的 `AAR_FRONTEND_REPORT` 给出此次唯一 JSON 路径；成功和失败记录均保留。用该实际路径导出，例如：

```bash
adb shell run-as com.lits.tts.aarhost cat files/aar-frontend-<timestamp>.json
```

归档时同时记录源码提交、Release AAR/两个 APK 的 SHA-256、已安装 APK 的校验值、模型清单和设备系统。仅在相关代码或二进制变化时重跑；文档修改不使原有真机证据失效。

## 4. 运行稳定性批测

以下为旧批测入口的参数参考，**尚未适配当前授权和外置资源流程，不是当前可用的发布门禁**：它没有初始化 license，而且默认清空 workPath。不要把已部署的资源目录传给旧入口；当前最小接入验收使用上一节的新入口，完整批测迁移单独推进。

### 100 条快速批测

```bash
./gradlew --no-daemon :aarHost:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.lits.tts.aarhost.AarStability1000DeviceTest \
  -Pandroid.testInstrumentationRunnerArguments.inputAsset=android_v3_sdk_stability_100_cases_improved_v2.jsonl
```

### 424 条中量批测

```bash
./gradlew --no-daemon :aarHost:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.lits.tts.aarhost.AarStability1000DeviceTest \
  -Pandroid.testInstrumentationRunnerArguments.inputAsset=android_v3_sdk_stability_424_cases_improved_v3.jsonl
```

### 1000 条完整批测

```bash
./gradlew --no-daemon :aarHost:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.lits.tts.aarhost.AarStability1000DeviceTest \
  -Pandroid.testInstrumentationRunnerArguments.inputAsset=android_v3_sdk_stability_1000_cases_improved.jsonl
```

也可以只跑一段样例，用于复现某个区间：

```bash
./gradlew --no-daemon :aarHost:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.lits.tts.aarhost.AarStability1000DeviceTest \
  -Pandroid.testInstrumentationRunnerArguments.inputAsset=android_v3_sdk_stability_1000_cases_improved.jsonl \
  -Pandroid.testInstrumentationRunnerArguments.caseStart=200 \
  -Pandroid.testInstrumentationRunnerArguments.caseLimit=50
```

## 5. 运行发音正确性批测

```bash
./gradlew --no-daemon :sdk:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.lits.tts.sdk.internal.PronunciationRound15FrontendDeviceTest \
  -Pandroid.testInstrumentationRunnerArguments.inputAsset=pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl
```

该测试会读取 golden pinyin，并用当前设备上的 SDK frontend 输出做 pinyin 序列对齐。测试会生成结果 JSONL、失败 JSONL 和 summary JSON。

## 6. 结果位置

稳定性批测结果写到设备侧：

```text
/sdcard/Android/data/com.lits.tts.aarhost/files/aar-stability-1000/
```

发音正确性批测结果写到设备侧：

```text
/sdcard/Android/data/com.lits.tts.sdk.test/files/pronunciation-round15-device/
```

可以用 `adb pull` 拉回：

```bash
adb pull /sdcard/Android/data/com.lits.tts.aarhost/files/aar-stability-1000/ \
  tts/android/build/reports/aar-stability-1000/

adb pull /sdcard/Android/data/com.lits.tts.sdk.test/files/pronunciation-round15-device/ \
  tts/android/build/reports/pronunciation-round15-device/
```

如果设备或 Android 版本限制直接读取 `/sdcard/Android/data`，可用 Android Studio Device Explorer 导出，或先通过测试日志里的 `resultsFile` / `summary` 路径定位。

## 7. 样例再生成

如需重新生成稳定性样例：

```bash
python3 tts/tools/android/generate_v3_sdk_stability_1000_cases.py
python3 tts/tools/android/generate_improved_v3_sdk_stability_1000_cases.py
python3 tts/tools/android/select_improved_v3_from_v2.py
python3 tts/tools/android/generate_edge_text_200_cases.py
```

其中：

- `generate_v3_sdk_stability_1000_cases.py` 生成基础 v3 1000 条设计样例。
- `generate_improved_v3_sdk_stability_1000_cases.py` 生成可在设备上长期跑的 improved 1000 条和 reduced 100 条。
- `select_improved_v3_from_v2.py` 从 improved 1000 条里抽取当前 424 条中量集。
- `generate_edge_text_200_cases.py` 生成数字、中英混合、符号、Emoji 和路径等文本边界语料。

重新生成后不需要手工复制。`tts/android/testdata/dingqiao_batch_cases/` 是唯一源目录；Gradle 在构建 AndroidTest 时只会把对应用例同步到 `build/generated/androidTestAssets/`。

## 8. 注意事项

- 批测样例是文本和 JSON，不包含 ONNX、TN 二进制、license 或签名材料。
- `tts/android/build/reports/`、设备拉回结果、APK/AAR、`external-resources/` 都属于本地输出，不应提交。
- 1000 条完整批测耗时较长，建议先跑 100 条确认设备、模型和 license 链路正常。
- 内存类样例的 native heap delta 是即时采样指标，失败时需要结合复跑、GC/settling 和系统日志判断，不应单独作为泄漏结论。
