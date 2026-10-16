# 本目录证据的脱敏说明

`绑核矩阵-20261014/` 下的运行产物是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias` /
`redact_text`，与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 | 影响文件 |
|---|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` | `build-mode/*/report-summary.json` 等 9 个 JSON |
| 设备序列号 | 替换为化名 `device-9d33cec60055`（`sha256(serial)[:12]`） | 同上 |
| 本机仓库绝对路径 | 去掉仓库前缀改为仓库相对路径；其余家目录路径替换为 `<home>/` | 40 个 `scenario.json` / `metrics.json` / `orchestrator.log` |

脱敏只触及上述三类字段。三篇报告所依赖的量——分阶段实时率、滞后分布、队列积压、回调节奏、
单窗耗时、CPU 与线程掩码快照、温度与电池采样、cpuset 迁移时间线——均未改动，可据本目录副本
独立复核。

原始的 hilog 全量、`events.full.ndjson`（每场约 5 万条）、设备侧 `report.json` 与资源采样
留在本机 `.cache/core-domain-matrix-20261014/`，按既有口径不入库。
