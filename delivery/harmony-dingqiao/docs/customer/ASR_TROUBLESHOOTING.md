# HarmonyOS 离线 ASR SDK 故障排查

## 1. 先记录完整调用轨迹

每次问题都按 `sessionId` 保存：

- `startListening` 参数和调用时间。
- `onStart`、`onEvent`、`onResult`、`onComplete`、`onError` 的时间、顺序和错误码。
- `finish`、`cancel`、`shutdown`、`unloadModel`、`unloadRuntime` 的调用时间。
- 实际写入 PCM 的字节数、采样率和对应时长。
- 脱敏后的系统版本、SDK ZIP checksum 和 HAR checksum。

不要记录 License 原文、设备标识、私钥、原始业务语音路径或客户敏感文本。

## 2. `startListening` 失败

检查顺序是否为：

1. `init` 和 `setWorkPath` 已完成。
2. `setLicense` 已成功回调。
3. `prepareRuntime` 已回调 `onReady`。
4. `createEngine` 或 `createEngineAsync` 已成功。
5. 上一 session 已正常结束或取消。

不要在 `onStart` 前写音频。收到 `onStart` 后可以在同一调用栈内同步写入缓存帧，无需人为延时。

## 3. 意外提前结束

先核对：

- 调用方是否已经执行 `finish`。
- 是否显式设置 `vadBegin` 或 `maxAudioDuration`。
- 写入 PCM 时长是否已命中配置值。
- 前置静音是否已经达到 `vadBegin`。
- 提前结果究竟是 `isFinal=true`，还是同时存在 `isLast=true`。

一句话 endpoint 的 `isFinal=true` 不表示 session 结束。只有 `isLast=true` 后才应出现 `onComplete`。

## 4. `speakerSimilarity` 缺失

同时记录：

- `enableVoiceprintVerification`、`enableSpeakerVad`。
- 有效 `voiceprintIds` 数量。
- `TargetSpeakerConfig.minSegSec`。
- 实际写入 PCM 时长和 final 的有效语音时长。
- 是否存在前置/尾部静音或低音量。

严格筛选后的有效语音达到 `minSegSec` 时优先使用严格样本。严格样本不足但 ASR 已产生非空
text/token 时，SDK 使用当前句非空真实 PCM 尝试评分，不因短句质量判断主动省略。没有 ASR 语音
证据、没有真实 PCM、声纹能力未生效或 extractor 技术上无法产生 embedding 时可以省略分数。
SDK 负责出分；短句精度、业务阈值和接受策略由调用方承担，必须使用带身份标注的目标/非目标语料
评测，不能只用生命周期日志判断。

## 5. cancel 或重启异常

- 每次启动使用唯一 `sessionId`。
- cancel 生效后检查是否仍新增 final/complete。
- 回调内重启时保存旧、新 session 的独立有序轨迹。
- 对旧 session 的迟到 `writeAudio/finish/cancel` 应只返回错误或被拒绝，不得影响当前 session。

## 6. 授权错误

确认授权文件可读、未被修改、授权能力包含 ASR 且仍在四个月有效期内。本体验授权不绑定包名、证书、设备、SDK 主版本或维护期。完整说明见 [LICENSE.md](LICENSE.md)。

## 7. 提交问题材料

提供以下脱敏材料：回调轨迹、启动参数、输入 PCM 的安全样本或可复现替代样本、错误码、系统版本、[checksum.txt](checksum.txt) 和复现步骤。生命周期闭环与结论边界见 [ASR_LIFECYCLE_ASSURANCE_20260716.md](ASR_LIFECYCLE_ASSURANCE_20260716.md)。
