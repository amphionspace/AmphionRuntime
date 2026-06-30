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

1. 未传 `maxAudioDuration` 时按 20000 ms。
2. 传 0、负数或小于 20000 的值时按 20000 ms。
3. 达到上限后应回调 `onResult(isFinal=true,isLast=true)` 和 `onComplete`，不得回调 `MAX_AUDIO_DURATION`。
4. 自动结束后 `isBusy()==false`，可立即再次 `startListening`。

## 4. 生命周期竞争窗口

1. 自动结束到 `onComplete` 之间继续写入少量帧，不得产生错误风暴或重复 `onComplete`。
2. 重复 `finish(sessionId)` 只允许一次 `onComplete`。
3. `cancel(sessionId)` 后不得再回 final result 或 `onComplete`。
4. `onComplete` 后迟到的底层 final 不得再透出给客户。
5. `shutdown()` 必须幂等。

## 5. 声纹与 License

1. 声纹注册至少 1 条样本；0 条返回 `VOICEPRINT_SAMPLE_COUNT`。
2. 样本时长小于 3 秒或大于 8 秒返回 `VOICEPRINT_SAMPLE_DURATION`。
3. `VoiceprintRegisterResult.voiceprintId` 必须为 `Record<string,string>`，key 为声纹 ID，value 为原始样本文件名。
4. 删除不存在的声纹应返回或抛出 `VOICEPRINT_NOT_FOUND` 语义，不得静默成功。
5. `LicenseInfo` 必须包含 `status`、`expireTime`、`remainingDays`、`authorizedFeatures`。
6. `LicenseActivationResult` 必须包含 `errorCode`、`errorMessage`、`remainingDays`、`authorizedFeatures`。
