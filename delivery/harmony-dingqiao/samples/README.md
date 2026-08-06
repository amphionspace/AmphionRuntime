# HarmonyOS Samples

- `dingqiao-demo/`：鼎桥验收 HAP，实时麦克风识别走 `SpeechRecognizeSdk` 契约，并演示 `TextToSpeechSdk` 离线合成。

运行前准备：

1. `bash asr/tools/04_build_harmony_so.sh`
2. `bash asr/tools/05_package_har_libs.sh`
3. `bash asr/tools/08_pack_harmony_assets.sh`
4. `bash tts/tools/harmony/pack_harmony_tts_assets.sh`（如需 TTS）
5. 用 DevEco Studio 打开 `delivery/harmony-dingqiao/`，运行 `amphion_asr_demo` 模块。

当前 USB 问题验证只构建和安装一个参数为 `zh-CN`（`ZH_EN`）的 `amphion_asr_demo` HAP；除非
问题明确涉及其他语种，不额外生成或安装其他语种测试 HAP。SDK/HAR 的公开语种能力不因此改变。

## Speaker VAD 与目标说话人增强

Demo 的 Speaker VAD 默认直接处理原始麦克风 PCM。注册声纹后，可显式开启“目标说话人增强”：
Demo 会同时开启 Speaker VAD，并把增强后的 PCM 送入 Speaker VAD 与 ASR。关闭增强后，Speaker VAD
仍可单独使用原始 PCM；该开关默认关闭且按设备持久化。开启增强的 HAP 必须包含对应的目标说话人
分离模型。

页面底部“调试信息”可展开查看本轮配置、音频帧计数和 SDK 回调时间线。停止识别后，完整配置、
采集统计、识别结果、增强应用标记和有界时间线会写入 `last_sdk_input.json`，并与
`last_sdk_input.wav` 一起供真机复现；系统日志中的结构化记录使用 `DemoDebug` 标签。
