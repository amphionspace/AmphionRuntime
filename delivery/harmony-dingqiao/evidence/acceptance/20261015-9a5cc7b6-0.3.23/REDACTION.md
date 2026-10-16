# 本目录报告的脱敏说明

`reports/customer-ptt-report.json` 是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias`，
与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 |
|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` |
| 设备序列号 | 替换为化名 `device-9d33cec60055`（`sha256(serial)[:12]`） |
| 本机仓库绝对路径 | 替换为 `<LOCAL_PATH>` |

## 哈希对照

`acceptance-manifest.json` 钉定的是**随 ZIP 交付的那一份**（未脱敏）的 SHA-256，因为该 manifest
本身也进了 ZIP，改动它会让仓库副本与已交付副本不一致。故 manifest 里的值与本目录文件的实测值
**按设计不同**：

| 文件 | 交付副本（manifest 钉定） | 本目录脱敏副本 |
|---|---|---|
| `reports/customer-ptt-report.json` | `9ecf3519b8f8b58dc73b387926c3435f2cf11636488907c2c73f8c3b290fb6b8` | `298d4b43a57e23e8df10995f433c1b950a49a4e1abfa1d79522cb7b878e1dd53` |

`delivery/candidate-reports/harmony-0.3.23-20261015/harmony.json` 的
`customer_ptt_report_sha256` 记的同样是交付副本的值。

`ACCEPTANCE-SUMMARY.md` 未脱敏改动，其 `summary_sha256` 与 manifest 一致，可直接校验。

脱敏只触及上表三类字段。判定结论所依赖的量（状态、失败项、逐轮计数、时延、内存采样、构建身份
与各产物哈希）均未改动，可据本目录副本独立复核。

> 本版修正：本文件此前整份沿用 0.3.22 修订版的同名说明，引用了那一批的哈希、并列出本目录
> 并不存在的 `final-zip-customer-ptt-report.json`，而报告本身也尚未实际脱敏。现已按上表
> 真正执行脱敏并更正记述。
