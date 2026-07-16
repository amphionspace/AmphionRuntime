# 鼎桥 Harmony SDK 契约测试规格

本文档记录 Harmony 侧需要在 DevEco / ohosTest 环境执行的接口契约测试。契约基线为 `/Users/boxp/Downloads/语音识别SDK接口-20260622.md`，增补口径见 `asr/android/docs/customer/语音识别SDK接口-交付批注版.md`。

当前仓库环境未配置可执行的 Harmony ohosTest 目标；本文先作为测试规格落库，后续接入鸿蒙设备或 DevEco CI 后应转成自动化用例。

## 1. 错误码表一致性

必须断言 `DingqiaoErrorCode` 的数值与交付批注版完全一致：

| 名称 | 数值 |
|------|------|
| CREATE_ENGINE_FAILED | 1002200001 |
| START_LISTENING_FAILED | 1002200002 |
| MAX_AUDIO_DURATION | 1002200003 |
| FINISH_FAILED | 1002200004 |
| CANCEL_FAILED | 1002200005 |
| ENGINE_BUSY | 1002200006 |
| ENGINE_NOT_INITIALIZED | 1002200007 |
| ENGINE_DESTROYED | 1002200008 |
| INTERNAL_ERROR | 1002200009 |
| NOT_LISTENING | 1002200010 |
| RECOGNITION_ERROR | 1002200011 |
| NO_MIC_PERMISSION | 1002200012 |
| VOICEPRINT_REGISTER_FAILED | 1002200020 |
| VOICEPRINT_SAMPLE_COUNT | 1002200021 |
| VOICEPRINT_SAMPLE_DURATION | 1002200022 |
| VOICEPRINT_NOT_FOUND | 1002200024 |
| LICENSE_FILE_UNREADABLE | 1002200030 |
| LICENSE_INVALID | 1002200031 |
| LICENSE_EXPIRED | 1002200032 |
| LICENSE_DEVICE_MISMATCH | 1002200033 |
| LICENSE_NOT_SET | 1002200034 |
| LICENSE_ACTIVATION_FAILED | 1002200035 |

## 2. 音频帧契约

1. 640 字节帧应被接受。
2. 320、960、1280 字节帧应通过 `onError(..., RECOGNITION_ERROR, ...)` 报错。
3. 1280 字节不得再作为合法 40ms 帧。

## 3. maxAudioDuration 增补

1. 未传 `maxAudioDuration` 时不启用单会话自动上限；连续写入超过 20000 ms 后仍须保持活动，直到显式 `finish` 或命中其他显式终止条件。
2. 显式传入有限数字、或非空且可解析为有限数字的字符串时启用；传 0、负数或小于 20000 的值时按 20000 ms。
3. 达到上限后应回调 `onResult(isFinal=true,isLast=true)` 和 `onComplete`，不得回调 `MAX_AUDIO_DURATION`。
4. 自动结束后 `isBusy()==false`，可立即再次 `startListening`。
5. `NaN`、正负无穷、空字符串、非法字符串及非数字类型均视为未配置，不得隐式启用 20000 ms 上限。
6. 大于 28800000 ms 时按 28800000 ms 处理。

## 4. vadBegin 与参数兼容

1. 未传 `vadBegin` 时禁用首段静音超时；只调用 `startListening` 而不写 PCM 不得超时。
2. 数字和数字字符串均应解析，并钳制到 500 到 10000 ms；非法值按未启用处理。
3. 持续写入静音 PCM 达到阈值后，必须依次回调空的 last final 和一次 `onComplete`，不得回调 speech 事件或错误。
4. 阈值边界同时检测到真实语音时，语音优先；VAD 或 ASR text/token 出现后，本会话不得再次触发 `vadBegin`。
5. `enablePartialResult=false` 不得影响真实 VAD 起音和 `vadBegin` 取消。
6. `recognitionMode` 缺省为 `STREAM=1`；传入 `RECORD=0` 应启动失败并明确提示不支持 SDK 内录音。
7. `recognizerMode` 只接受 `short` / `long`，两者均使用现有长语音流式实现。
8. `locate` 当前仅兼容接受 `CN`；`sessionGeneralLexicon` 明确为 V1 不支持，不得伪装生效。
9. 启用声纹校验或 Speaker VAD 时，纯静音仍按钳制后的 `vadBegin` 结束；初始等待窗内存在连续声学活动但 VAD/ASR 未决时，才增加一次默认 1500 ms 确认窗。
10. 组合回归必须交替覆盖实时/突发喂入和直接起音/前置静音；足够长语音在显式 `finish` 前不得出现 `isLast`，第一个非空 final 必须带分数；probe 可产生 non-last final，因此不能把总 final 数硬编码为 1。
11. 声学 backstop 必须与调用方分帧无关。低于 -40 dBFS 的噪声、被静音打断的短脉冲和零散变幅脉冲不能误判；稳态高能非语音只允许延时一次并最终结束；确认窗末只有近期连续活动兼具语音型能量变化和过零率范围时才能直接解除计时，旧活动必须由 ASR probe 确认，且声学证据不单独产生 speech 事件。
12. `voiceprint-vad-begin-idle` 必须交替验证纯静音约在 1000 ms 结束、稳态高能非语音约在 2500 ms 有界结束；均没有 speech 事件或非空文本，且只有一次 last final/complete。

## 5. 生命周期竞争窗口

1. 自动结束到 `onComplete` 之间继续写入少量帧，不得产生错误风暴或重复 `onComplete`。
2. 重复 `finish(sessionId)` 只允许一次 `onComplete`。
3. `cancel(sessionId)` 后不得再回 final result 或 `onComplete`。
4. `onComplete` 后迟到的底层 final 不得再透出给客户。
5. `shutdown()` 必须幂等。
6. `onStart` 回调表示 session 已可用；在该回调调用栈内同步写入 32/88 个 640 字节缓存帧，不得返回 `NOT_LISTENING`；分别验证继续写入后结束和回调内立即 `finish`，后者不得返回 `FINISH_FAILED`。
7. `onStart` 内立即 `cancel` 仍不得遗留 native stream、final 或 `onComplete`。
8. 首次冷加载及每轮 `shutdown -> unloadModel -> createEngine` 后必须重复第 6 条；底层 started 信号无论发生在 session 发布前还是发布后，对外都只能发送一次 `onStart`。
9. 所有底层回调必须绑定创建该 native session 时的 generation。旧 session 被 cancel/结束后，其迟到的 partial、event、final、error、started、stopped 均不得使用新 sessionId 对外发送，也不得结束新 session。
10. 在 `SPEECH_END` 或 last `onResult` 回调内执行 `cancel(old) -> startListening(new)` 后，旧回调处理栈恢复执行时必须重新校验 generation；新 session 写入首帧前不得出现 final 或 complete。
11. `writeAudio(old, frame)` 进入 Core 后若同步回调触发上述切换，Core 返回时不得把该帧累计到新 session，也不得据此触发新 session 的 `maxAudioDuration`。

主机可执行的初始静音、final 完成策略、session generation 和发布状态机测试由 Android CI 的
`Run cross-platform ASR lifecycle contracts` 步骤执行；Harmony 真机发布门禁仍按本节完整执行。

## 6. 声纹与 License

1. 声纹注册至少 1 条样本；0 条返回 `VOICEPRINT_SAMPLE_COUNT`。
2. 样本时长小于 3 秒或大于 8 秒返回 `VOICEPRINT_SAMPLE_DURATION`。
3. `VoiceprintRegisterResult.voiceprintId` 必须为 `Record<string,string>`，key 为声纹 ID，value 为原始样本文件名。
4. 删除不存在的声纹应返回或抛出 `VOICEPRINT_NOT_FOUND` 语义，不得静默成功。
5. `LicenseInfo` 必须包含 `status`、`expireTime`、`remainingDays`、`authorizedFeatures`。
6. `LicenseActivationResult` 必须包含 `errorCode`、`errorMessage`、`remainingDays`、`authorizedFeatures`。
