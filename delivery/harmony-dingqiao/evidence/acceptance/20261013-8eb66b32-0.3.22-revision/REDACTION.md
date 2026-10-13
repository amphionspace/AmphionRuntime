# 本目录报告的脱敏说明

`reports/customer-ptt-report.json` 是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias`，
与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 |
|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` |
| 设备序列号 | 替换为化名 `device-9d33cec60055`（`sha256(serial)[:12]`） |
| 本机仓库绝对路径 | 替换为 `<REPO_ROOT>` |

## 哈希对照

| 文件 | 原始副本（`acceptance-manifest.json` 钉定） | 本目录脱敏副本 |
|---|---|---|
| `reports/customer-ptt-report.json` | `b66724d3efb8423342e16e6ec2f7f5406f47f5d1e75d5744df2bd39cf80506d9` | `3ea51e927a58712b23ff392b1fc2499dbec0eeb34f8a8acad1b512edcf66eaa9` |

`ACCEPTANCE-SUMMARY.md` 未脱敏改动，其 `summary_sha256` 与 manifest 一致。

## 本目录的状态

本轮（`8eb66b32`）**不是最终交付**。它的完整包正式 SDK 误用了 diagnostics 构建的 HAR，
已被 `20261013-dca08e69-0.3.22-revision/` 取代。保留本目录是为了记录该缺陷的来源与当时的实测数据
（问题二修前修后的那组对照即在本轮测得）。详见取代目录中 `ACCEPTANCE-SUMMARY.md` 的
「组包顺序缺陷」一节。
