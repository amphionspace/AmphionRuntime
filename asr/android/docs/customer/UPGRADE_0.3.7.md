# Android ASR SDK 0.3.7 升级说明

本版在 0.3.6 上修正 Android 与鸿蒙的时间及角色展示差异。正式业务使用 Release AAR，Diagnostics 仅用于获授权的问题定位。中英离线能力与现有授权方案保持不变。

- `beginTime/endTime` 的秒转毫秒采用四舍五入，与角色 token 和鸿蒙一致；旧版截断值最多相差 1 ms，调用方不应依赖旧版向下截断。
- Demo 按 `sourceUtteranceId` 合成完整原句，保留所有原始片段供查看；多位角色显示“多位说话人”，未知显示“部分待确认”，推断及重叠分别标记。
- `speakerInferred=true` 仍表示有限邻接推断，`confidence=0`，原始 `speakerTurns` 保留。不得把原句段落强行归给多数角色。
- 按 `windowIndex` 累积结果、冻结已提交窗口；`isFinal` 表示句末，`isLast` 表示 ASR session 末条，`isSessionFinal` 表示角色末批。

本版未改变角色模型、身份阈值或 UNKNOWN 补全边界。已知短插话、重叠及部分身份误认继续阻断通用角色能力；Android 后台/锁屏可靠性未通过验收。原句展示改善不代表身份精度已经修复。最终范围以绑定完整 ZIP 的外置验收报告为准。
