# 声纹首句提前结束复盘

日期：2026-07-15
影响：Harmony/Android 鼎桥 SDK 的 `vadBegin` 与声纹组合会话

## 用户症状

调用方传入 `vadBegin=1000` 后，首句概率返回
`speakerSimilarity=undefined, isFinal=true, isLast=true`，随后立即 `onComplete`。
截图中的启动参数只包含 `enablePartialResult`、`maxAudioDuration`、`vadBegin` 和 `vadEnd`，
没有 `enableVoiceprintVerification` 与 `voiceprintIds`。如果日志完整，这会独立导致
`speakerSimilarity=undefined`；但它不能解释“真实语音被提前 `isLast`”，后者是 SDK 缺陷。

## 根因

`vadBegin` 按 SDK 已处理的 PCM 时长计时，不按墙钟时间计时。突发写入可以在约 563 ms 墙钟时间内
喂满 1000 ms PCM。达到阈值时存在三个不同步的事实：

1. 辅助 VAD 可能尚未报告 speech onset。
2. 流式 ASR 可能尚未产生 partial text/token。
3. 同一缓冲在 `stop()` 强制刷新后却能产生非空 final。

旧状态机只看前两项就发出 `onInitialSilenceTimeout`。适配层随即把 session 标记为结束并调用
`stop()`；第三项产生文本时，`isLast` 已经无法撤销。短段同时可能未达到声纹默认 1.5 秒有效语音门槛，
因此形成用户看到的组合症状。

真机红灯中，静态延长到 2500 ms 后仍有 8/40 提前结束，其中 4 轮在错误的 last final 中已有文本
“提。”：`20260715-154224-voiceprint-vad-begin-24feed45`。

## 被否决的方案

### 无条件把 `vadBegin` 加 1.5 秒

这混淆了“起音前允许静音”和“起音后声纹打分所需语音”两个时间基准。它改变纯静音公共语义，
且真机仍有 8/40 失败，所以不是根因修复。

### 任意持续高能永久解除超时

该方案能让真实语音门禁变绿，但空调、车内噪声、音乐或 DC 偏置也可能永久关闭 `vadBegin`，
把“提前结束”换成“无人说话也拖到 maxAudioDuration”。首版实现还依赖调用方分帧大小，review 后淘汰。

## 最终方案

1. `vadBegin` 保持原语义。纯静音仍在钳制后的 500-10000 ms 阈值结束。
2. VAD speech 或 ASR 非空 text/token 仍会永久解除本 session 的初始静音计时。
3. 声纹/Speaker VAD 会话在初始等待窗内有连续声学活动、但前两路未决时，只获得一次默认 1500 ms
   的有界确认窗。
4. 声学分析固定使用 20 ms 窗，因此同一 PCM 不因调用方分帧不同而改变结果。只有连续活动满足
   语音型能量变化和过零率范围，且确认窗末仍在近期窗口内，才作为保守 backstop 解除计时；零散脉冲
   或已经过去的旧活动只能进入 ASR probe，不能直接解除计时。声学证据不产生 `SPEECH_BEGIN`。
5. 确认窗结束仍未得到语音型证据时强制刷新 ASR。有 text/token 就作为 non-last final 保留并继续
   session；仍为空才确认初始静音超时。
6. 稳态高能非语音只能消耗一次确认窗，不能永久延长会话。

## 验证结果

| 门禁 | 结果 | Artifact |
| --- | --- | --- |
| 短句多源，burst/paced，直接起音/800 ms 前置静音 | 40/40 PASS；finish 前 last 0 | `20260715-164326-voiceprint-vad-begin-bc146fc6` |
| `$HOME/Downloads/testdata` 长稳压 | 100/100 PASS；RSS -4.305 MiB | `20260715-170619-voiceprint-vad-begin-46ef77ac` |
| 纯静音/稳态高能非语音交替 | 100/100 PASS；均恰好一次 last/complete | `20260715-171246-voiceprint-vad-begin-idle-ca698bb3` |
| 最终分帧无关版本，短句多源组合回归 | 40/40 PASS；首个非空 final 带分数；finish 前 last 0 | `20260715-182307-voiceprint-vad-begin-27989eec` |
| 最终分帧无关版本，纯静音/稳态高能非语音 | 40/40 PASS；无 phantom final/SPEECH_BEGIN；均有界结束 | `20260715-182522-voiceprint-vad-begin-idle-c251101f` |

测试载体直接调用 SDK，不以 UI 是否正常或文本准确率决定 PASS。语音场景在调用 `finish` 前快照
`isLast`，空闲场景则不调用 `finish`，等待 SDK 自动结束。

## Review 拦截的问题

- 首版语音型窗口跨静音累计，三个零散变幅脉冲也可能被误判。最终改为只在连续窗口内累计；旧活动
  最多触发有界 probe，不能在确认窗末直接解除计时。
- Core SDK 接受任意长度 PCM；首版先处理整个调用块再判断 deadline，会让 deadline 之后的语音回看
  并改变之前的超时决定。最终在初始计时 armed 时按固定 20 ms slice 顺序推进，单个大块与多个小块
  输入得到相同决策。
- Harmony 的 probe 换流后最初未重置 VAD/Speaker VAD 门控，可能污染下一段。最终与 Android 对齐，
  换流后同步重置 carry、speech 状态和 speaker gate，probe 本身不伪造 endpoint 回调。
- 初版真机门禁只要求“任意 final 有分数”，可能漏掉首个 final 缺分数。最终语音用例要求第一个
  非空 final 带分数，但允许 probe 的 non-last final 后继续产生最后结果；空闲用例则要求恰好一个空
  last final、无 `SPEECH_BEGIN`，防止 phantom final。
- 新确认窗参数最终在 core 层按 target speaker 能力和 `minSegSec` 钳制，并在 Harmony/Android 都校验
  非法输入，避免普通 ASR 或任意超长确认窗绕过公共生命周期边界。

## 防止复发

- 发布前必跑 `voiceprint-vad-begin` 与 `voiceprint-vad-begin-idle`，并保留逐 session callback trace。
- 前置静音用例必须保证“载体注入静音 + 源文件自身静音”小于 `vadBegin`；否则失败是错误测试预期。
- 排查相似度缺失时必须同时记录声纹开关、voiceprint ID 数量、有效语音时长和 requested/effective
  `vadBegin`，先区分调用参数、短语音可选字段和生命周期缺陷。
- 生命周期门禁不使用文本正确率；声纹精度使用有身份标注的数据集单独评测。
- 合入前检查全部 PR review threads，包括 Copilot suggestion；有效问题补回归，误报记录理由。

## 剩余风险

声学 backstop 是保守的误杀保护，不是新的通用 VAD。非稳态音乐、多人背景讲话等具有语音型特征的
输入可能使 `vadBegin` 不结束，但它们本来也不属于纯静音。最终仍由显式 `finish` 或
`maxAudioDuration` 兜底。当前真机语料未稳定命中“probe 先产生 non-last final、随后 finish 再产生
last final”的成功分支；后续应使用可控 fake recognizer/VAD 做跨端 pipeline 集成测试，强制覆盖该
回调序列。物理断连、系统杀进程、多进程争用和真正多线程并发调用仍需独立故障注入。
