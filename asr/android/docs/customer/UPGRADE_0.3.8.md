# Android ASR SDK 0.3.8 升级说明

相对 0.3.7，本版更新中英 Police 1.4.0 模型与警务后处理，修正活动 VAD endpoint 的待处理语音边界，并改进会议主要发言的角色归属及文字可读性。中英模型使用上游 encoder INT8、decoder/joiner FP32；具体模型哈希以交付包的 manifest 为准。

公共回调语义不变：`isFinal` 是当前句末，`isLast` 是 ASR session 的最后结果，角色 `isSessionFinal` 是角色末批。调用方继续按 `windowIndex` 累积角色结果，按 `sourceUtteranceId` 关联原句；临时角色允许修正，已提交窗口冻结。UNKNOWN、重叠与 `speakerInferred=true` 均须如实呈现；文字补全不代表声学身份确认。

正式业务使用 Release AAR。Diagnostics 会记录音频和文字，仅限获授权的问题定位。通用短插话、重叠身份精度以及 Android 后台/锁屏可靠性仍需正式验收；本说明不代替绑定最终 ZIP 的验收报告。SDK 保持离线运行，不包含目标说话人增强模型。
