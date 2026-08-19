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
2. 显式传入正有限数字、或非空且可解析为正有限数字的字符串时启用并按调用值生效；
   `maxAudioDuration=8000` 必须在累计写入 8000 ms PCM（400 个 20 ms 帧）时结束。
   0、负数、非有限值和非法类型按未启用处理，不得回退到隐式 20000 ms。
3. 显式传入 `enableContinuousRecognition=true` 时，SDK 必须保持同一模型会话并忽略
   `maxAudioDuration` 自动上限；在调用方显式 `finish` 前不得产生 `isLast=true`。省略、`false`
   或字符串 `"true"` 不得改变既有最大时长语义。
4. 达到上限后应回调 `onResult(isFinal=true,isLast=true)` 和 `onComplete`，不得回调 `MAX_AUDIO_DURATION`。
5. 自动结束后 `isBusy()==false`，可立即再次 `startListening`。
6. `NaN`、正负无穷、空字符串、非法字符串及非数字类型均视为未配置，不得隐式启用 20000 ms 上限。
7. 大于 28800000 ms 时按 28800000 ms 处理。
8. `max-duration` 真机门禁必须分别覆盖 burst 与 20 ms paced 写入，两者都在第 400 帧结束；
   paced 场景墙钟时间不得明显早于 8 秒。结束后 80 个迟到帧不能新增 final、complete 或 error，
   下一轮必须能立即启动。
9. continuous 真机门禁必须至少有一个单 model session 实时写入超过 60 秒，并用两轮运行区分
   首次模型驻留与持续内存增长；另须组合声纹校验与 Speaker VAD，逐条核对非空 final 的
   `speakerSimilarity`、finish 前无 last、最终唯一 last/complete 和绑定源音频 SHA-256 的尾字。

## 3.1 endpointMaxUtteranceMs

1. 缺省、非正数、非有限值或非法类型使用 native rule3 默认值 20000 ms。
2. 正有限数字或可解析字符串按毫秒转换为 rule3 秒数；该参数改变单句 final 边界，不得产生
   `isLast=true` 或 `onComplete`。
3. recognizer 复用键必须包含生效后的 rule3 值；相邻 session 从 20000 ms 切到 60000 ms 时不得
   复用旧 recognizer 配置。
4. 鼎桥长语音、填单和会议纪要 profile 使用 60000 ms；PTT 和点击识别维持 20000 ms。

## 4. vadBegin 与参数兼容

1. 未传 `vadBegin` 时禁用首段静音超时；只调用 `startListening` 而不写 PCM 不得超时。
2. 数字和数字字符串均应解析，并钳制到 500 到 10000 ms；非法值按未启用处理。
3. 持续写入静音 PCM 达到阈值后，必须依次回调空的 last final 和一次 `onComplete`，不得回调 speech 事件或错误。
4. 阈值边界同时检测到真实语音时，语音优先；VAD 或 ASR text/token 出现后，本会话不得再次触发 `vadBegin`。
5. `enablePartialResult=false` 不得影响真实 VAD 起音和 `vadBegin` 取消。
   启用 Speaker VAD 时仍必须遵循该参数：为 `true` 时继续公开 speculative partial，为 `false`
   时不公开 partial。Speaker VAD 的目标说话人边界保证只适用于 final；partial 允许包含随后从
   final 中移除的非目标说话人文本。非目标片段被拒绝时必须在拒绝事件后回调空 final；non-last
   rejection 不得触发 `onComplete` 或结束 session，last rejection 仍只能产生一次 last/complete。
6. `recognitionMode` 缺省为 `STREAM=1`；传入 `RECORD=0` 应启动失败并明确提示不支持 SDK 内录音。
7. `recognizerMode` 只接受 `short` / `long`，两者均使用现有长语音流式实现。
8. `locate` 当前仅兼容接受 `CN`；`sessionGeneralLexicon` 明确为 V1 不支持，不得伪装生效。
9. 鼎桥声纹配置固定 `minSegSec=0`，不额外延长 `vadBegin`；纯静音或未被 VAD/ASR 确认的活动仍按钳制后的 `vadBegin` 结束。
10. 组合回归必须交替覆盖实时/突发喂入和直接起音/前置静音；足够长语音在显式 `finish` 前不得出现 `isLast`，第一个非空 final 必须带分数；probe 可产生 non-last final，因此不能把总 final 数硬编码为 1。
11. 声学 backstop 必须与调用方分帧无关。低于 -40 dBFS 的噪声、被静音打断的短脉冲和零散变幅脉冲不能误判；正数 `minSegSec` 下，稳态高能非语音只允许延时一次并最终结束；确认窗末只有近期连续活动兼具语音型能量变化和过零率范围时才能直接解除计时，旧活动必须由 ASR probe 确认，且声学证据不单独产生 speech 事件。鼎桥固定 `minSegSec=0`，因此不启用这段额外确认窗。
12. `voiceprint-vad-begin-idle` 必须交替验证纯静音和稳态高能非语音都约在 1000 ms 结束；二者均没有额外确认窗、speech 事件或非空文本，且只有一次 last final/complete。
13. 同时开启声纹校验和 Speaker VAD 时，token-only native endpoint 被抑制只能清理 Speaker VAD
    当前流窗口，不能清理尚未形成公开 final 的声纹回退 PCM。两个各约 800 ms 的 native segment
    合并成一条非空公开 final 时，回退候选必须达到约 1600 ms。

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
12. 在 `SPEECH_END` 回调内同步调用 `finish(sessionId)` 时，当前带文本 endpoint final 必须直接标记为
    本 session 唯一的 `isLast=true`，不得先发送带文本 non-last、再追加空 terminal final。
13. 已接受 `finish(sessionId)` 后，即使旧宿主因 `isBusy()==true` 立即调用 `shutdown()`，SDK 也必须先
    排空已接受 PCM，按序发送唯一 last 和 `onComplete`，随后再释放引擎；`isBusy()` 在 complete 前仍
    表示会话正在进行，不得提前发布虚假 idle。该门禁由真机 `finish-shutdown` 模式逐 session 验证。

主机可执行的初始静音、final 完成策略、session generation 和发布状态机测试由 Android CI 的
`Run cross-platform ASR lifecycle contracts` 步骤通过 `test_harmony_*.py` 自动发现并执行。
Harmony 发布前还必须执行 `delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py`，
用同一 commit、设备和 HAP/HAR 组合验证第 12、13 条。背景和证据规则见
`delivery/harmony-dingqiao/docs/FINISH_COMPATIBILITY_POSTMORTEM.md`。

## 6. 声纹与 License

1. 声纹注册至少 1 条样本；0 条返回 `VOICEPRINT_SAMPLE_COUNT`。
2. 样本时长小于 3 秒或大于 8 秒返回 `VOICEPRINT_SAMPLE_DURATION`。
3. `VoiceprintRegisterResult.voiceprintId` 必须为 `Record<string,string>`，key 为声纹 ID，value 为原始样本文件名。
4. 删除不存在的声纹应返回或抛出 `VOICEPRINT_NOT_FOUND` 语义，不得静默成功。
5. `LicenseInfo` 必须包含 `status`、`expireTime`、`remainingDays`、`authorizedFeatures`。
6. `LicenseActivationResult` 必须包含 `errorCode`、`errorMessage`、`remainingDays`、`authorizedFeatures`。
7. `enableVoiceprintVerification=true`、有效 `voiceprintIds` 且
   `enableSpeakerVad=false` 时仍必须执行 final 声纹评分；Speaker VAD 不是返回
   `speakerSimilarity` 的前置条件。
8. 鼎桥声纹配置固定 `minSegSec=0`。ASR 已产生非空 text/token 且当前句有真实 PCM 时，必须使用
   当前句 PCM 尝试计算真实分数，不得按 SDK 时长或质量门槛主动弃权；音频时长、阈值和接受策略由
   业务方判断。不得填充固定值、复制上一句分数或补静音。
9. ASR 没有 text/token 证据、当前句 PCM 为空、声纹能力未生效或 extractor 技术上无法产生
   embedding 时仍允许省略分数，
   但不得丢失识别结果或改变 final/last/complete 顺序。
10. `voiceprint-fallback` 使用两条固定顺序语料：`000_enroll.wav` 注册，
    `001_recognize.wav` 识别。第一条非空 endpoint final 必须带分数，显式 `finish` 前
    `isLast` 必须为 0；该模式不得配置短 `maxAudioDuration`，避免把两个终止条件混在一个断言中。
