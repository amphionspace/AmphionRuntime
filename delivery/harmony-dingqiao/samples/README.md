# HarmonyOS Samples

- `dingqiao-demo/`：鼎桥验收 HAP，实时麦克风识别走 `SpeechRecognizeSdk` 契约，并演示 `TextToSpeechSdk` 离线合成。

运行前准备：

1. `bash asr/tools/04_build_harmony_so.sh`
2. `bash asr/tools/05_package_har_libs.sh`
3. `bash asr/tools/08_pack_harmony_assets.sh`
4. `bash tts/tools/harmony/pack_harmony_tts_assets.sh`（如需 TTS）
5. 按 [命令行工具链说明](../../../asr/tools/HARMONY_TOOLCHAIN.md) 配置环境，执行 `delivery/harmony-dingqiao/delivery/build_install_smoke.sh` 构建并安装 `amphion_asr_demo`。

当前 USB 问题验证只构建和安装一个参数为 `zh-CN`（`ZH_EN`）的 `amphion_asr_demo` HAP；除非
问题明确涉及其他语种，不额外生成或安装其他语种测试 HAP。SDK/HAR 的公开语种能力不因此改变。
