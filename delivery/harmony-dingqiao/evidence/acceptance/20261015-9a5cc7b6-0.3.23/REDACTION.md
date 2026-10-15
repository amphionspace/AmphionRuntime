# 本目录报告的脱敏说明

`reports/` 下的两份报告是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias`，
与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 |
|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` |
| 设备序列号 | 替换为化名 `device-9d33cec60055`（`sha256(serial)[:12]`） |
| 本机仓库绝对路径 | 替换为 `<REPO_ROOT>` |

## 哈希对照

`acceptance-manifest.json` 钉定的是**随 ZIP 交付的那一份**（未脱敏）的 SHA-256，因为该 manifest
本身也进了 ZIP，改动它会让仓库副本与已交付副本不一致。故 manifest 里的值与本目录文件的实测值
**按设计不同**：

| 文件 | 交付副本（manifest 钉定） | 本目录脱敏副本 |
|---|---|---|
| `reports/customer-ptt-report.json` | `8ac7dfaf0ee2b5fd811887ee78b75d11a895487d8a200ffe01b711270176d02e` | `e2d97ddc312020e88b1db3063d1caaeb1a23c4c961981784087140683f05be3a` |
| `reports/final-zip-customer-ptt-report.json` | `30ddc692e195575a4609d1ce942ea035129a0d12769d5a894c650dbb676a116d` | `6b40c0e53e843c013cca40ccc57858a7ca62a6ee8db03dcb78b4381ce33ac9aa` |

`ACCEPTANCE-SUMMARY.md` 未脱敏改动，其 `summary_sha256` 与 manifest 一致，可直接校验。

脱敏只触及上表三类字段。判定结论所依赖的量（状态、失败项、逐轮计数、时延、内存采样、构建身份
与各产物哈希）均未改动，可据本目录副本独立复核。
