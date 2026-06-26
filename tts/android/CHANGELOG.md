# Changelog

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
