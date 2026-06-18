# 鼎桥语音识别 Demo

交付用示例 APK，仅依赖 `:sdk-dingqiao`（鼎桥 `SpeechRecognizeSdk` API）。

完整交付说明见 **[docs/DINGQIAO_DELIVERY.md](../docs/DINGQIAO_DELIVERY.md)**。

## 快速构建

```bash
cd asr/android
./gradlew :sample-dingqiao-demo:assembleDebug
```

## 声纹模型

```bash
adb push eres2net.onnx /sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/
```
