# 不说话时反复转写出"嗯"（客户 #92 第二轮，2026-11-18）：门禁没在普通转写里生效 + 填充词需 VAD 证据

状态：已修（两端），鸿蒙 Mate 80 与鼎桥安卓机 BRA-AL00 真机复现并复测通过。接 11-02 的
`SILENCE_FILLER_HALLUCINATION_20261102.md`。

## 一、客户这次的证据

- 录屏 `问题合计 3/离线/问题92/SVID_20261117_155317_1.mp4`：小乔「通话」文本转写，一通广告来电，双方
  说了两句（"喂喂。""喂。嗯。"）后静音，之后每 6～8 s 出一条"嗯。"，持续到 64 s，共 7 条。
- `audio.wav`（62.8 s，16 kHz **双声道**，SHA-256 `244c449c…ddf2`）：右声道 0～5 s 真人声，之后
  −92 dBFS 量化残渣；左声道 0～2 s 有声，之后逐位数字零。与 11-02 的客户文件同一形态，**仍不是 SDK
  的单声道输入**。右声道单声道化后在我方鸿蒙机上回放（0.3.29，transcription 档，vadEnd=1600）只转出
  "喂。嗯。"，57 s 静音段 0 字——这份文件本身复现不出客户现象。

## 二、用普通电平底噪复现（修复前，0.3.29，Mate 80）

取客户右声道前 5.5 s 真人声，后接 57 s 粉噪，四档电平；transcription 档实时喂入：

| 尾段电平 | 发布文本 | 多出的填充词 |
| --- | --- | --- |
| −40 dBFS | 喂。嗯。呃。 | 1 |
| −50 dBFS | 喂。嗯。呃。嗯。 | 2 |
| −60 dBFS | 喂。嗯。嗯。嗯。嗯。呃。 | 4 |
| −70 dBFS | 喂。嗯。呃。 | 1 |

多出的全部是 `source=native`（rule2）端点、`textChars=1`、VAD 全程没有语音段的单字 final。这就是客户
录屏里"每隔几秒一个嗯"的形态：通话静音时的底噪是普通电平，不是数字零。

## 三、根因（两处，两端相同）

1. **发布门禁在普通转写场景根本没在跑。** `EffectiveSpeechBuffer.observe(rawSamples)` 只在
   `targetSpeakerEnabled || speakerVadEnabled` 时调用，不开机主识别时 `processedWindows` 恒为 0，
   `resolveFinal` 走"没喂过窗 → 放行"的分支，11-02 加的门禁对客户的通话转写无效。
2. **门禁的声学分支挡不住普通底噪**（11-02 已写明的已知限制）：−74 dBFS 的发布阈值远低于房间/通话底噪，
   粉噪的包络起伏也能满足 3 倍比值。

## 四、修复

- 两端 `observe()` 改为无条件调用（保留 PCM 仍受 `UTT_MAX_SAMPLES` 上限约束）。
- 新规则：去掉标点后**只由填充词构成**（`嗯呃额啊哦噢喔唔诶欸哎唉呀哼嘶`，≤4 字，或 um/uh/hmm 等）
  且本句**原生 VAD 从未判出语音**的 final 不发布，`RESULT_SUPPRESSED reason=filler-without-vad`。
  有实词的文本不受影响，不设统一字数/时长门槛；真人说的"嗯"由 VAD 判出语音后照常发布
  （客户同一录音 3～5 s 的真人"嗯"走 vad-active 端点，修后两端都保留）。
- 被门禁拦下的非空 final 现在会清空这一句保留的 run，避免长时间底噪里 run 累到上限后证据冻结、
  早先的 VAD 证据被下一句继承。
- 鸿蒙 `Runtime.ets` 的 `RESULT_SUPPRESSED` 指标带上具体 reason；安卓 `SessionImpl` 新增同名指标。

## 五、复测

| 平台 / 构建 | 四档粉噪 | 客户右声道 | 回归 |
| --- | --- | --- | --- |
| 鸿蒙 Mate 80，本次源码构建（`HARMONY_SIGNING_CONFIG=.secure/harmony-signing-signing-project.json`） | 四档均只剩"喂。嗯。"，8 次 `filler-without-vad` | "喂。嗯。"不变 | #98 录音 speaker-vad-turn：发布文本、10 条 gate 判定、拒绝数与修前逐条相同 |
| 安卓 BRA-AL00，`dingqiao-demo-debug.apk` SHA-256 `0b62f44f…8869e` | 五个文件 7 s 后 0 条填充词（修前 −70 dB 收尾漏出 1 条"嗯。"），真人"喂/嗯"保留 | 同左 | #100 回放仍通过（机主两句发布、非机主 11 句拒绝）；`:sdk:testDebugUnitTest` 134/134 |

主机单测：安卓 `EffectiveSpeechBufferTest` 17 例（新增 5），鸿蒙 `test_harmony_effective_speech_buffer.py` 27 例（新增 6）。

## 六、仍要说明的边界

- 规则只拦"填充词 + 无 VAD 语音"。底噪里幻听出实词（11-02 主机上见过"是"）仍会发布；真机四档粉噪里
  没有出现这种情况，但不能据此宣称已覆盖。
- 一句话内若连续 25 s 以上都是通过 ZCR 判据的窗且没有任何 final，缓冲达到上限后不再记录新证据，
  其后到来的真人"嗯"可能被拦；有实词的句子不受影响。
- 客户 App 的 SDK 输入转储仍然没有拿到；本次复现用的是合成粉噪。建议让鼎桥用 Diagnostics SDK 导出
  一次通话静音期的输入，确认底噪形态。

## 七、证据

`~/amphion-evidence/20261118-issue92/`：`noise/`（四档合成文件）、`right/`、`mix/`、`sha256.txt`、
`device-runs/`（修前 `20261118-010517`、修后 `20261118-013735` 与 `20261118-014415`，含 hilog）。
安卓证据在本机 scratchpad `run92`/`run92b`（evidence.jsonl、logcat）。
