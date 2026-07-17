# 声纹分数缺失与最大音频时长语义复盘

日期：2026-07-17
影响：Harmony 鼎桥 ASR SDK 0.2.6 的声纹结果与 `maxAudioDuration`

## 1. 结论

这次客户反馈包含两个独立问题：

1. **声纹分数缺失**：ASR 已产生长句非空 final，但严格声纹窗口被能量、ZCR 和连续性筛选后
   不足默认 1.5 秒，SDK 直接省略 `speakerSimilarity`。这不是声纹 ID 缺失，也不是
   `enableSpeakerVad` 未开启。
2. **8 秒参数未生效**：Harmony 0.2.6 把所有显式 `maxAudioDuration < 20000` 钳制为
   20000 ms，所以客户传入 8000 并不会在 8 秒 PCM 后结束。

两者在同一会话中出现，但根因和终止条件不同，必须分开修复和验收。

## 2. 客户证据

客户日志确认启动参数包含：

- `enableVoiceprintVerification=true`
- 一个有效 `voiceprintId`
- `maxAudioDuration=8000`
- `vadBegin=5000`
- `vadEnd=1600`

2026-07-17 13:21 和 13:23 两轮中，`SPEECH_BEGIN` 到 `SPEECH_END` 分别约 3.7 秒和
3.9 秒，final 文本非空，但 `speakerSimilarity=undefined`。同一组注册语料和相近文本又有概率
返回分数，说明问题位于“当前句可用于评分的样本选择”，不是注册是否成功。

客户附件包含三条 8 秒、16 kHz、mono、PCM16 注册 WAV，但没有识别阶段原始 PCM。因此无法对客户
现场输入做逐字节复播；诊断使用客户日志约束参数和回调时序，并用可稳定触发同一状态的本地语料建立
红灯。

## 3. 代码历史

`MIN_MAX_AUDIO_DURATION_MS=20000` 与 `EffectiveSpeechBuffer` 都在提交 `1c51656` 中首次引入。
20 秒下限不是长期历史行为，也不是 PR #73 引入；PR #73 只处理 endpoint 回调内 `finish()` 的
terminal final 生命周期。

引入 20 秒下限时，测试也明确断言负数和短正数钳制到 20 秒。实现和测试彼此一致，但没有接口契约
依据。这是把历史测试当成产品语义，而不是从参数名称和调用方预期推导行为。

## 4. 声纹根因

严格路径用 `EffectiveSpeechBuffer` 选择语音型窗口。该路径适合提高声纹分数质量，但它把 ZCR、
能量和连续窗口条件同时作为“是否允许评分”的硬门槛。真实长句在以下情况下可能被筛掉大部分窗口：

- 低音量或距离变化；
- 手机降噪、削波或频谱变化；
- VAD/ASR 已确认语音，但局部 ZCR 超出严格范围；
- 短异常间隔把连续 run 切开。

旧实现只把严格样本交给 extractor。严格样本不足 `TargetSpeakerConfig.minSegSec` 时，
`applyTargetSpeaker()` 正确地不计算分数，但没有第二条有证据的真实音频路径，因此出现
“ASR 明确识别出长句，声纹字段却完全缺失”。

## 5. 最终修复

声纹样本选择按以下顺序执行：

1. 严格有效语音达到 `minSegSec`：继续使用严格样本。
2. 严格样本不足，但 ASR 当前 final 有非空 text/token，且当前句实际 PCM 达到门槛：
   使用当前句真实 PCM 计算分数。
3. 没有 ASR 语音证据、实际 PCM 仍不足或为空 terminal final：保留识别结果并省略分数。

回退仍调用真实 speaker extractor 和 cosine similarity，不填固定分数、不复制上一句结果、不补静音。
代价是回退分数可能比严格路径噪声更大；这是“分数可用性优先于严格质量筛选”的明确选择，精度阈值
仍由带身份标注的评测集决定。

`enableSpeakerVad` 不需要开启。`enableVoiceprintVerification` 控制 final 评分；
`enableSpeakerVad` 额外控制流式目标说话人门禁和拒绝行为，两者不能混作一个开关。

两者同时开启时存在两套不同边界：Speaker VAD 窗口随 native stream 重置，声纹回退 PCM 只能在
公开 final、明确拒绝或 session 关闭时重置。实现将两者拆成独立且各自最多 25 秒的有界缓存，避免
token-only endpoint 被抑制后误删尚未发布句子的回退 PCM。

`maxAudioDuration` 修复为：

- 缺省、非正数、非有限或非法值：不启用；
- 正有限值：按调用值转换为 PCM 字节；
- 最大值：28800000 ms；
- 受 20 ms/640 字节公共帧约束，实际结束精度为一帧。

因此 8000 ms 对应 400 个 20 ms 帧。该参数按**累计写入 PCM 时长**计数，不按 ASR 是否说完一句，
也不按 burst 写入时的墙钟时间计数。第 400 帧后 SDK 停止接受该 session 的后续音频并开始 flush；
last final / `onComplete` 还包含解码和回调延迟，不承诺在 8 秒墙钟时刻同步到达。burst 回放可在
更短墙钟时间内写满同等 PCM 并触发结束。

## 6. 被否决的方案

### 给 `undefined` 填 0 或默认分数

这会把“没有计算”伪装成“计算结果很低”，破坏业务阈值语义，也无法区分短句和非目标说话人。

### 复用上一句分数

分数会跨 utterance 污染，且多人连续讲话时会把前一人的身份带到下一人。

### 放宽所有严格 ZCR/VAD 阈值

这会改变主路径质量和 Speaker VAD 行为，影响面大于客户问题。最终方案保留严格路径，只在有 ASR
证据和真实时长门槛时回退。

### 强制要求 `enableSpeakerVad=true`

客户只需要 final 校验，不需要流式拒绝。强制开启会改变识别结果可见性，不能作为修复。

### 保留 20 秒下限并修改文档

`maxAudioDuration` 的字面和接口用途都是调用方指定的最大音频时长。无外部能力限制支持 20 秒下限，
继续钳制只会让参数失真。

## 7. 为什么原测试没有拦截

1. 常规 `voiceprint` 只证明短句省略、普通长句有分数，没有稳定命中“长句 ASR 有文本但严格样本
   不足”的状态。
2. 声纹测试曾把“任意 final 有分数”作为通过条件，无法证明第一条非空 endpoint final 有分数。
3. `max-duration` 旧门禁直接使用 20000 ms，与错误实现同源，没有 8000 ms 的外部契约用例。
4. 只测 burst 无法直观看到“8 秒 PCM”和“8 秒墙钟”的区别。
5. 回退复现模式最初同时配置 8000 ms，并仍断言显式 `finish` 前无 `isLast`。修复时长语义后，
   该测试会正确自动结束，暴露了测试把两个独立终止条件混在一起。
6. `CONTRACT_TESTS.md` 仍保留“小于 20 秒钳制到 20 秒”，说明文档、实现和测试没有单一外部契约源。
7. 多句用例只断言整轮至少出现一次分数，且 `voiceprint-fallback` 明确关闭 Speaker VAD，未覆盖
   token-only native endpoint 在双开模式下跨流保留回退 PCM。

## 8. 永久门禁

- 主机单测覆盖严格优先、恰好门槛回退、实际 PCM 不足、无 ASR 证据、双开模式的跨 native stream
  缓存边界、非法和极小正时长。
- `voiceprint-fallback` 使用 `000_enroll.wav` 和 `001_recognize.wav`，要求第一条非空 endpoint
  final 带真实分数，显式 `finish` 前无 `isLast`，并分别覆盖 cold/warm extractor。
- `max-duration` 交替 burst/paced，均必须在第 400 帧结束；只有一次 last/complete，80 个迟到帧
  不改变计数，下一轮可启动。
- 常规 `voiceprint` 继续保护短句无分数、门槛、长句、前置静音、低音量、多句和非注册语料；多句
  必须逐条检查每个非空 final，而不是只看整轮分数总数。
- 完整发布矩阵继续保护 cancel、重入、初始静音、冷加载、跨 session 和资源回收。

详细命令、停止条件和 artifact 要求见
[`VOICEPRINT_DURATION_RELEASE_GATE.md`](./VOICEPRINT_DURATION_RELEASE_GATE.md)。
本次完整执行结果见
[`VOICEPRINT_DURATION_REGRESSION_EVIDENCE_20260717.md`](./VOICEPRINT_DURATION_REGRESSION_EVIDENCE_20260717.md)。

## 9. 剩余风险

- 回退分数的目标/非目标区分精度尚未由客户身份标注识别 PCM 评测；当前门禁只证明真实计算和接口
  可用性。
- 客户现场识别 PCM 缺失，不能证明本地语料覆盖其全部前处理特征。后续再次出现异常必须要求保存
  原始识别 PCM、最终生效参数和完整 callback trace。
- 当前修改只改变 Harmony。Android 已直接使用当前句 PCM 评分，但其
  `maxAudioDuration` 历史语义与 Harmony 不同，应单独立项统一，不能在本修复中顺带改变。
