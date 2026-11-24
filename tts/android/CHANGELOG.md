# Changelog

## [3.3] - 2026-11-23

### Fixed
- 中文词典读音：`南站` 由 na1 改为 nan2（"成都南站 / 广州南站 / 火车南站"等均受影响），`南昆线` 同步修正；
  补充 `重做 / 重跑 / 重测 / 重拨` 为 chong2，此前缺词时按单字默认 zhong4 读出。
  修复同时落在主词典（重建 `chinese_lexicon.bin`）与运行时覆盖表 `polyphone_phrases.txt`。
- 号码读法：`18912345678` 等 7 位以上整数此前会被前端预处理读成基数词（"一百八十九亿…"）。现在
  号码类字段与拨号动词（号码 / 手机 / 电话 / 联系方式 / 来电 / 拨打 / 回拨 / 呼叫 / 工号 / 警号 / 编号 / 案号 /
  订单号 / 卡号 / 账号 / 证号 / 流水号 / 序列号 / 车架号 等）后的 5 位以上整数逐位读（电话类读"幺"），
  无标签的大陆手机号（1[3-9] 开头 11 位）也逐位读；后面跟量词或单位（元 / 人 / 次 等）的大数仍按数量读，
  前导零的长数字逐位读。
- 模型、推理参数、公共 API、资源内置与解包方式、授权公钥与 3.2 相同；5 个 ONNX 不变。

## [3.2] - 2026-11-16

- 修复缺陷 #94：英文/中英文本里句末标点紧贴下一句（如 "Are you ready?Yes"、"ready.Yes"、"Ready...Yes"）时，`?`、`.`、`…` 会被当成 URL/文件名之类技术 token 的一部分读成 "question mark" / "dot" /「问号」/「点」。现在这类标点先与下一句分开，再走原有分句与归一化，和带空格写法的合成结果完全一致。
- 合法粘连不受影响："?key=" 查询串、URL/路径/邮箱、文件名、版本号（v1.2.3）、小数（3.14）、缩写（U.S.A）仍按技术读法。
- 模型、推理参数、公共 API、资源内置与加载方式与 3.1 相同（IMF 170000、24 kHz Vocos、173 token、speaker 1、温度 0、两步、默认 50 帧）；授权兼容主版本仍为 1。
- 产物身份与验证范围见 [3.2 交付记录](docs/releases/3.2-20261116.md)。

## [3.1] - 2026-09-17

- 交付 IMF 170000 模型及配套 24 kHz Vocos、173 token 前端资源，默认 speaker 1、温度 0、两步、50 帧流式。
- 沿用 stageSdkDelivery 的交付结构、原有 API / INTEGRATION / PSEUDOCODE 接入示例，包含内置完整模型和前端资源的 Release AAR，Demo APK 自动携带相同资源；不含授权文件或内部 validation 材料。
- 本次保留交付版本和命名、相同模型与推理参数；license 兼容主版本仍为 1。
- 清理旧模型构建说明和内部报告，补齐已有授权接口及回调字段说明；公开 API 与推理行为保持不变，当前模型常规分块覆盖值仍需不小于 40 帧。
- SDK 按 manifest 解包内置模型，校验文件哈希并复用已安装资源；已有外置模型仍优先加载。无需接入方复制模型文件。授权文件仍由使用方单独提供。
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
