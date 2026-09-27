# 四人短会话建档候选修复验证（2026-09-27）

状态：**候选修复在固定参数下通过原始 19.58 秒 Mate80 回放；未改变模型、窗口、hop、定稿周期或 timeout。**

## 根因和最小改动

原始 19.58 秒录音的首个窗口中，第一人的干净声学 run 只有 68 帧，低于现有 run embedding 建档条件（`0.2 * 589`），因此没有独立训练向量。随后 VBx 在仅有合格 run 的情况下把多个身份合并。该问题发生在角色建档／聚类层，ASR、声学分割、调度吞吐和 SDK 文本对齐均不是首个错误状态。

本分支只在以下条件同时满足时增加一条训练候选：run 是单声道、无 overlap 的短 clean run；该声道在当前窗口只有这一条 clean run；已有的 masked full-window embedding 有限且非零。候选只有在 AHC 组数恰好增加一组、且仍未超过 `maxSpeakers` 时才加入。若 VBx 在此受限候选场景下仍少于 AHC 组数，使用同一批训练向量的 AHC cluster mean 做受限回退。混合／overlap／无声学支持的 run 继续 UNKNOWN；没有按人数强制建组、复制 embedding、改阈值或隐藏 UNKNOWN。

诊断字段 `shortRunTrainingCount` 和 `usedAhcFallback` 只写入 native diagnostic JSON，不改变公共 API。

## 证据

- 原始输入：19.58 秒、16 kHz、PCM16、mono，WAV SHA-256 `f13ad95b225a88c64161ff9a01770d07718f547c97445b7b6bb61ae146f739e7`。私有原音和前序状态在 `~/.cache/amphion-runtime/diagnostics/four-speaker-collapse-20260927-165102/`，不提交仓库。
- 原有状态机／SDK 回归：`test_harmony_community_native`、`test_harmony_community_diarization`、`test_harmony_community_public_contract` 共 47 项通过。
- 新增白盒回归：合成 3 个已有组、一个孤立短 clean run 和一个超过 cap 的短 run；断言只接纳一个短候选、使用 AHC 回退、第四个角色可见，超过 cap 的候选仍 UNKNOWN。通过。
- Mate80 真机：构建身份指纹 `D6CE6F943F7D8AF4C0121C1842BB46F9225F1AF6657D1B088734B0B10A97250D`；会议模式 artifact 为 `/tmp/amphion-short-session-device-meeting/20260927-210635-customer-meeting-minutes-b45d4023/`。

真机公开结果为四个按出场顺序的 speaker turns：

| 时间（秒） | 公共 speakerIndex | overlap |
|---:|---:|---|
| 1.145–2.292 | 0 | false |
| 4.925–7.321 | 1 | false |
| 10.038–12.215 | 2 | false |
| 14.645–16.737 | 3 | false |

该回放的 `speakerCount=4`、`degraded=false`、无 error、无 live native stream；`finish → last → complete` 为约 1470 / 1475 ms，推理 RTF 0.349。ASR 文本仍按原始结果返回，未用文本启发式修正。

为保护长会话行为，复用 canonical 123.8 秒四人 WAV 在同一 Mate80、同一参数回放：当前 artifact `/tmp/amphion-long-session-device-current-123/20260927-211350-diarization-windows-64e63141/`。与既有 canonical 结果逐项相同：23 个 final、40 个 speaker turns、speakerCount=4、degraded=false、overlap／UNKNOWN 时间段一致；当前 RTF 0.522（既有 0.529），finish 到 complete 1072 ms（既有 905 ms），native stream 归零，RSS 无增长红灯。

## 边界和未解决范围

真机 `diarization-windows` 对短于两个逻辑窗口的输入有额外的“至少两个窗口结果”载体门槛；19.58 秒样例因此在该模式被载体判红。使用同一 HAP、同一输入的 `customer-meeting-minutes` 会议契约复核通过，避免改动门禁。102.38 秒复用样例的四人 speaker turns 也正确，但其载体只产生一个终端窗口，不能替代 123.8 秒 canonical 长会话对照。

本候选没有证明所有短句、混合轨道或低音量背景都能可靠建档；遇到不满足 clean-run 条件的声音仍应保留 UNKNOWN。下一步合入前必须检查当前 HEAD CI、Harmony 构建和 review threads；若新增语料出现身份误认，应回到最早建档状态定位，不能继续堆叠参数补丁。
