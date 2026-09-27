# Android ASR SDK 0.3.5 升级说明

本版接续 0.3.4 预览基线；上一正式 Android 交付为 0.3.3。正式验收范围、产物身份和限制以本包外置报告为准。

## 需要调整的接入

- `AsrResult.timestamps`（秒）和鼎桥结果 `beginTime/endTime`（毫秒）统一为 session 输入音频时间轴，跨句不归零。如果业务侧自行叠加过前句时长，须移除补偿。
- 角色最终结果按窗口多批回调。按 `windowIndex` 累积保存，不要覆盖全文；`sourceUtteranceId` 关联原转写，`isSessionFinal` 标识角色末批。ASR `isFinal/isLast` 不表示角色已经定稿。
- 不可靠的角色返回 `speakerIndex=-1`。中间归属可被修正；已定稿窗口保持不变。

## 更新

- 同步端侧离线角色分离、short/long 识别模式、编译期隔离的 Diagnostics SDK、LAC 人名后处理及共同参数契约；这些能力已进入 0.3.4 预览基线。
- 修复跨句时间轴倒退和等待角色尾窗时真实末句被空兜底覆盖的问题。
- 同步短片段身份建档、历史混合上下文、重叠身份依据及文本边界修复。
- Demo 标注角色中间/最终阶段，保留 SDK 编号，增加固定 WAV 输入；会议 vadEnd 使用 800ms。
- 保留口语填充词，修复起音、冷启动回灌和 finish 后资源回收边界。

## 保持的契约与限制

`onStart` 后可立即写入/结束/取消；`isFinal` 是一句话定稿，`isLast` 是整个 session 的末条。正常结束唯一 last 后唯一 complete；cancel 不补 final 或 complete。只支持 OFFLINE，推理不需要服务 URL。

默认最多 4 个角色。多人重叠发言精度尚未通过，短暂新人可能保持未知。Diagnostics SDK 用于问题定位，可记录 PCM、转写和运行信息；业务正式发布使用 Release SDK。目标说话人增强为预留接口，不包含所需模型。
