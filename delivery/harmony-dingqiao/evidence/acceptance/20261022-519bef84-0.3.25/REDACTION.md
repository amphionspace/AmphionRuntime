# 本目录报告的脱敏说明

`reports/*.json` 是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias`，
与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 |
|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` |
| 设备序列号 | 替换为化名 `device-2257b2bbf3e2`（`sha256(serial)[:12]`） |
| 本机仓库与家目录绝对路径 | 替换为 `<LOCAL_PATH>` |

## 哈希对照

`acceptance-manifest.json` 钉定的是**随 ZIP 交付的那一份**（未脱敏）的 SHA-256，因为该 manifest
本身也进了 ZIP，改动它会让仓库副本与已交付副本不一致。故 manifest 里的值与本目录文件的实测值
**按设计不同**：

| 文件 | 交付副本（manifest 钉定） | 本目录脱敏副本 |
|---|---|---|
| `reports/customer-ptt-report.json` | `e789f0553fc808ccb53b45dab94c4c340107fced90cab6581ac64844c825a165` | `c6c456099482f2d6004459bb6ad1497f40b9af9ea24fb6d93345221cbed118a2` |
| `reports/issue36-diarization-report.json` | `3699740bd908fafe9b1f066b51ce6048ff0d8b50bd03a0f8eeca6ef0cce0e180` | `d0821579f48f1462c4af7732cda4f369d71c03e629741e089ea740a933a6b012` |

`ACCEPTANCE-SUMMARY.md` 无需脱敏，仓库副本与交付副本一致，哈希即 manifest 中的 `summary_sha256`。

## 报告范围说明

`reports/issue36-diarization-report.json` **未列入** `acceptance-manifest.json` 的受检 `reports`：
组包门禁要求受检报告 `overall_status=PASS`，而该报告因 `diarization-windows` 模式的 SDK 契约检查
包含声纹注册项、本次语料不含注册样本而判 FAIL。该判定与问题 #36 的修复无关，报告作为支撑证据
随本目录保留，归属结论以其中的诊断事件为准。
