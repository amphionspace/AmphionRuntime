# Android 主说话人换人切分：移植鸿蒙 clean-split 与主机验证（2026-10-29）

## 问题

机主识别 + 实时转写：机主停、非机主立刻接话且中间没有静音时，普通 VAD / endpoint 不切句，
两个人的语音在 ASR 里是同一个 utterance。Android 的主说话人 VAD 只做"连续低分后主动 endpoint"，
从换人到切句约 1.5~2 s（默认窗 1.5 s、步 0.5 s、连续 2 次），这段时间内非机主说的话已经被解码进
机主那句，final 级声纹打分以机主为主体通过，于是非机主的首句随机主 final 一起被录入。

鸿蒙自 `a49af8be`（2026-08-12）起已有 `SpeakerTurnFinalizer` + Runtime 的"干净前缀重解码 +
后缀重放"实现，并进入 0.3.25；Android 一直没有移植，这是两端行为差异的根因。

## 本次改动（Android）

- 新增 `asr/android/sdk/src/main/java/com/amphion/asr/internal/SpeakerTurnFinalizer.kt`：
  鸿蒙 `SpeakerTurnFinalizer.ts` 的 Kotlin 移植（状态机、有界 PCM 账本、声学/token 候选、
  左右声纹复核、保守包含前缀）。未移植 pyannote 换人分割辅助判定，Android 走鸿蒙
  "分割模型不可用"的同一路径。
- `SessionImpl`：
  - 声纹打分移到把切片喂给 speculative stream **之前**（与鸿蒙一致），确认离场的切片归重放所有，
    避免原生 endpoint 先把已污染的结果发出去。
  - 离场确认后调用 resolver；得到切点则：前缀在新 stream 重解码并作为 final 发出，
    换人点之后的音频重放到另一个新 stream，并保持 `svAwaitingTargetAfterDeparture`，
    直到声纹窗口重新确认目标人前所有 final 走 `onFinalRejected`。
  - 找不到可复核边界时沿用 Android 原先的立即 endpoint（鸿蒙在无分割模型时选择 fail-open 继续
    录；这里保留旧行为以免泄露变长，是有意的差异）。
  - 重解码失败按鸿蒙规则报 `DECODE_FAILED` 并关闭会话，不用已知污染结果兜底。

## 主机验证

- JVM 单测 `SpeakerTurnFinalizerTest`（8 个用例，移植自鸿蒙契约测试）；`:sdk` 全部 76 个单测通过；
  `:sdk-dingqiao`、`samples:dingqiao-demo` 编译通过。
- 真实音频：`asr/tools/speaker/16_eval_speaker_turn_split_aishell3.py`，aishell3_test_hotwords_500
  中相邻且说话人不同的 99 对录音无间隙拼成 target + other 会话，target 用自身音频注册，
  按 SDK 的固定打分节奏重放，离场确认后运行与 SDK 相同的 resolver（无 ASR，故没有 token 候选，
  设备上会更准）。模型 `shared/models/asr/dingqiao/eres2net.onnx`。

| 配置 | 对数 | 触发离场 | 得到切点 | 切点误差 p10/p50/p90 (s) | 平均泄露 仅endpoint→切分 (s) | 截断率 仅endpoint→切分 |
|---|---:|---:|---:|---|---|---|
| Android 默认 0.35/1.5/0.5/2 | 99 | 86.9% | 78.8% | −0.48 / −0.10 / +0.25 | 1.58 → 0.37 | 1.0% → 7.1% |
| 评测配置 0.40/1.0/0.3/2 | 99 | 100.0% | 89.9% | −0.59 / −0.37 / −0.04 | 0.84 → 0.10 | 2.0% → 51.5% |

- 默认参数下平均非目标泄露从 1.58 s 降到 0.37 s（−76.5%），每对会话多 4 次以内的声纹推理。
- "截断"按切点早于 target 结束超过一个 hop 计。aishell3 录音尾部带静音，切在尾静音里也被计入，
  故为上界；1.0 s 窗 / 0.3 s 步时切点系统性偏早（p50 −0.37 s），**不建议**随本改动同时收紧参数。
- 唯一一条 −5.4 s 的离群值是 target 自己中段连续低分造成的假离场，旧逻辑同样会在该处 endpoint。

## 未覆盖

- 没有安卓真机：本轮未在设备上验证重解码 / 重放路径的实时表现与回调时序。
- finish 时刻（用户停止时离场刚开始）的换人恢复未移植。
- pyannote 分割辅助判定未移植；Android 的 `DingqiaoSpeakerModelAssets` 已随包带
  `pyannote-segmentation-3.0.onnx`，可作为下一步。
