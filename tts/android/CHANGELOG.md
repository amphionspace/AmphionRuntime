# Changelog

## [3.1] - 2026-09-17

- 交付 IMF 170000 模型及配套 24 kHz Vocos、173 token 前端资源，默认 speaker 1、温度 0、两步、50 帧流式。
- 沿用 stageSdkDelivery 的交付结构、原有 API / INTEGRATION / PSEUDOCODE 接入示例，包含 Release AAR 和外置资源；不含授权文件或内部 validation 材料。
- 本次整理交付版本和命名，复用已验收的 AAR 和模型；license 兼容主版本仍为 1。
- 产物身份、验证范围和限制见 [3.1 交付记录](docs/releases/3.1-20260917.md)。

## [0.1.0] - 2026-06

### Added

- Android AAR 纯 TTS SDK，包名 `com.lits.tts.sdk`。
- 内置 `lits_delivery_16k_hifigan` 模型资源，支持 `zh-en` 与 `en-US`。
- `TextToSpeechSdk.createEngine` / `listVoices` 同步与 callback 版本。
- callback 版 `createEngine` / `listVoices` 内部异步执行，Android 环境下回调派回主线程。
- `TextToSpeechEngine.speak` 支持 `SYNTHESIZE_ONLY` 与 `SYNTHESIZE_AND_PLAY`。
- `SpeakListener` 回调异步派发。
- `SpeakParams.soundChannel` 支持 Android `AudioManager.STREAM_*` legacy stream type。
- SDK-only 交付文档、第三方 NOTICE、混淆规则和校验说明。

### Changed

- `SYNTHESIZE_AND_PLAY` 不再通过 `onData` 返回 PCM，符合接口文档默认语义。
- App 启动预加载模型的接入方式明确写入文档。

### Verification

- `:sdk:testDebugUnitTest`
- `:sdk:assembleRelease`
- `:sample:assembleRelease`
