# Harmony 真机发布矩阵（2026-08-05）

本目录保存提交 `9d276554c686aea31db17354b7f5ece74ea35077` 在 Huawei Mate 80
（设备 `7GK0226326015655`）上的合入前验证证据。测试载体为同一份 `ZH_EN` 正式签名 HAP，
SHA-256 为 `9dd070743ff1dba597631446e15fb5a5c062a999077bdc02c8c8097dd4aa611f`。

以下 21 个通用发布模式全部为 `overall_status=PASS`：

- 基础识别与结束：`burst`、`paced`、`vad-begin`、`vad-begin-silence`、`max-duration`。
- 取消与非法调用：`cancel`、`cancel-full`、`edge`、`numeric-edge`。
- 会话发布与重入：`reentrant`、`start-cancel`、`start-write`、`start-write-reload`、
  `user-sequence`、`callback-api-reentrant`、`endpoint-reentrant`。
- 声纹与 Speaker VAD：`voiceprint`、`voiceprint-fallback`、`voiceprint-vad-begin`、
  `voiceprint-vad-begin-idle`、`speaker-vad-onstart`。

每个模式目录均保留 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、
`inventory.json` 和 `payload/corpus.json`。短用例的资源结论可能是 `INCONCLUSIVE`，原因是
观察时间不足 15 秒；这不影响其生命周期断言。资源结论由超过 60 秒的目标说话人实时用例和声纹
回退 cold/warm 用例单独覆盖，二者均为 `PASS`。

目标说话人增强的 C1/C2/C3、`onStart` 和取消恢复证据保存在
`../../target-speaker-enhancement/20260805/`，同样绑定上述提交和 HAP。
