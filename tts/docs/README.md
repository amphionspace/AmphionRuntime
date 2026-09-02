# TTS 能力级文档

本目录保存不绑定 Android 或 HarmonyOS 实现的 TTS 接口契约，以及跨平台可复用的优化报告。平台构建、集成和测试说明继续放在各平台自己的 `docs/` 目录。

## 接口契约

- [语音合成 SDK 接口文档](api/语音合成SDK接口.md)：语言无关的 TTS 公共接口基线。

## 优化报告

- [TN 体积优化报告](optimization/TN_SIZE_OPT_REPORT.md)：端侧 TTS 文本归一化的 ICU 数据裁剪结论和验证方法。
