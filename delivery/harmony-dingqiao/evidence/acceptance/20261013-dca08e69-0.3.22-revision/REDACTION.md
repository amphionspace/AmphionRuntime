# 本目录报告的脱敏说明

`reports/` 下的两份报告是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias`，
与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 |
|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` |
| 设备序列号 | 替换为化名 `device-9d33cec60055`（`sha256(serial)[:12]`，与 0.3.13 证据同一化名） |
| 本机仓库绝对路径 | 替换为 `<REPO_ROOT>` |

## 哈希对照

`acceptance-manifest.json` 钉定的是**随 ZIP 交付的那一份**（未脱敏）的 SHA-256，
因为该 manifest 本身也进了 ZIP，改动它会让仓库副本与已交付副本不一致。
因此 manifest 里的值与本目录文件的实测值**按设计不同**：

| 文件 | 交付副本（manifest 钉定） | 本目录脱敏副本 |
|---|---|---|
| `reports/customer-ptt-report.json` | `c66f34973ae669a20afb1f27d7d11985c16a8209a9a07c579b615814881d3302` | `f1f6959c743b9ec57b1e57d17d93072f92035bf5a18d47e89cabb7a81fcca0ae` |
| `reports/final-zip-customer-ptt-report.json` | `889741014d37a41608221773ae54b4fde24b7c04445c5c46c70d2d162dced856` | `b74db8e2f858b5f11aa49f4fc12a0e61a4f821cab201efd4d4fc7763aa935b08` |

`ACCEPTANCE-SUMMARY.md` 未脱敏改动，其 `summary_sha256` 与 manifest 一致，可直接校验。

脱敏只触及上表三类字段。判定结论所依赖的量（状态、失败项、逐轮计数、时延、内存采样、
构建身份与各产物哈希）均未改动，可据本目录副本独立复核。
