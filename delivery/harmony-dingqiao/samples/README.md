# HarmonyOS Samples

- `dingqiao-demo/`：鼎桥验收 HAP，实时麦克风识别走 `SpeechRecognizeSdk` 契约，并演示 `TextToSpeechSdk` 离线合成。

运行前准备：

1. `bash asr/tools/04_build_harmony_so.sh`
2. `bash asr/tools/05_package_har_libs.sh`
3. `bash asr/tools/08_pack_harmony_assets.sh`
4. `bash tts/tools/harmony/pack_harmony_tts_assets.sh`（如需 TTS）
5. 用 DevEco Studio 打开 `delivery/harmony-dingqiao/`，运行 `dingqiao_demo` 模块。
