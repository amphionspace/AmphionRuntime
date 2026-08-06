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

为了让 Android instrumentation test 可以直接读取，稳定性三份 JSONL 同步到了：

```text
tts/android/aarHost/src/androidTest/assets/
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
tools/dingqiao-android/generate_v3_sdk_stability_1000_cases.py
tools/dingqiao-android/generate_improved_v3_sdk_stability_1000_cases.py
tools/dingqiao-android/select_improved_v3_from_v2.py
tools/dingqiao-android/run_android_frontend_parity.py
tools/dingqiao-android/run_android_phone_frontend_batch.py
tools/dingqiao-android/compare_android_frontend_batch_tokens.py
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

## 4. 运行稳定性批测

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
python3 tools/dingqiao-android/generate_v3_sdk_stability_1000_cases.py
python3 tools/dingqiao-android/generate_improved_v3_sdk_stability_1000_cases.py
python3 tools/dingqiao-android/select_improved_v3_from_v2.py
```

其中：

- `generate_v3_sdk_stability_1000_cases.py` 生成基础 v3 1000 条设计样例。
- `generate_improved_v3_sdk_stability_1000_cases.py` 生成可在设备上长期跑的 improved 1000 条和 reduced 100 条。
- `select_improved_v3_from_v2.py` 从 improved 1000 条里抽取当前 424 条中量集。

重新生成后，需要把最终要跑的稳定性 JSONL 同步到 `tts/android/aarHost/src/androidTest/assets/`，把发音正确性 JSONL 同步到 `tts/android/sdk/src/androidTest/assets/`。

## 8. 注意事项

- 批测样例是文本和 JSON，不包含 ONNX、TN 二进制、license 或签名材料。
- `tts/android/build/reports/`、设备拉回结果、APK/AAR、`external-resources/` 都属于本地输出，不应提交。
- 1000 条完整批测耗时较长，建议先跑 100 条确认设备、模型和 license 链路正常。
- 内存类样例的 native heap delta 是即时采样指标，失败时需要结合复跑、GC/settling 和系统日志判断，不应单独作为泄漏结论。
