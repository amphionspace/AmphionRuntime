# HarmonyOS ASR SDK 0.3.14 升级说明

相对上一正式交付 0.3.13，本版修复角色身份稳定性、语音结束事件和长会话结束回收问题。模型与默认角色上限 4 人保持不变。最终验收结论以完整 ZIP 对应的外置报告为准。

## 接入重点

- `onSpeakerDiarizationResult` 继续按窗口多批返回。按 `windowIndex` 累积保存，不能每次覆盖全文；`sourceUtteranceId` 关联原转写，`isSessionFinal` 表示角色处理的末批。此契约已在 0.3.13 引入，本版继续沿用。
- ASR `isFinal/isLast` 不等于角色已最终确认。Demo 分别标注角色“中间结果”和“最终结果”；中间归属可能修正，已提交窗口不回写。
- 无法可靠区分的短句或重叠发言返回 `speakerIndex=-1`，页面显示“未能区分说话人”。未知不等于识别出一个新角色。
- 会议 Demo 的 `vadEnd` 保留 800ms。对照实验未证明统一降低停顿能改善多人身份精度；SDK 最低生效值仍为 500ms。

## 本版修复

1. 避免将同一人的短片段反复登记为不同角色，避免历史混合语音占用真实新人的名额；保留重叠通道的身份依据。真实新人只有很短的发言时仍可能返回未知。
2. 修复标点和中文 token 边界影响按角色拆分文本的问题，保持原始转写完整、窗口不重复发文。
3. Speaker VAD 结束后的后台角色处理不再拖延 `SPEECH_END`；按 generation 归属处理迟到结果，保持 final、last、complete 顺序。
4. 保留真实冷启动时 `onStart` 内同步回放 PCM 的能力，修复初始等待与声纹/Speaker VAD 组合以及 finish 后 Runtime 重建的边界问题。
5. ITN 保留“嗯、呃”等口语填充词，减少原始内容被无意删除。授权信任配置支持已有受控客户授权，沿用本次交付授权范围。

## 生命周期

`onStart` 表示 session 已可用，可立即调用 `writeAudio`、`finish`、`cancel`。`isFinal` 表示一句话定稿；`isLast` 只表示整个 session 的末条结果。普通连续识别在调用方 `finish` 前不得提前产生 last；正常结束为唯一 last 后唯一 complete。`cancel` 不补发 final 或 complete。

## 已知边界

四人重叠会议仍存在误认与未知，不宣称多人精度问题已解决。短时资源验收不能证明长会议无泄漏；快速喂入和长会议资源另行跟踪。目标说话人增强仍只保留接口，不包含所需模型，不能启用。Diagnostics SDK 用于定位问题，可记录音频与文本；正式 SDK 不开启该采集。
