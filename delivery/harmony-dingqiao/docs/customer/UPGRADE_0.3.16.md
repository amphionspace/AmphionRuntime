# HarmonyOS ASR SDK 0.3.16 升级说明

与 Android 0.3.7 绑定同一最终源码提交重新构建。鸿蒙识别、角色身份算法和公开回调语义沿用 0.3.15；Android 已修正时间舍入并对齐鸿蒙原句展示。

继续按 `windowIndex` 累积角色结果，以 `sourceUtteranceId` 关联完整原句，并保留角色区间详情。混合、UNKNOWN、推断及重叠须如实显示；`speakerInferred=true`、`confidence=0` 的文字归属不等于声学身份确认。ASR 的 `isFinal/isLast` 不能代替角色 `isSessionFinal`。

本版没有新增鸿蒙身份精度修复。已知短插话、重叠和部分身份误认仍阻断通用角色能力。轻声／背景 UNKNOWN 的取舍仅限已约定的主要发言范围，不能外推到所有环境。最终范围以绑定完整 ZIP 的外置验收报告为准。

正式业务使用 Release HAR。Diagnostics 会记录音频和文字，仅用于获授权的问题定位。授权、签名及离线边界保持不变；本包不含 TTS 或目标说话人增强模型。
