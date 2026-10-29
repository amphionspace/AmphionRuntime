# 本目录报告的脱敏说明

`reports/*.json` 是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias`，
与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 |
|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` |
| 设备序列号 | 替换为化名 `device-9d33cec60055`（`sha256(serial)[:12]`） |
| 本机家目录绝对路径 | 替换为 `<LOCAL_PATH>` |

## 哈希对照

`acceptance-manifest.json` 钉定的是**随 ZIP 交付的那一份**（未脱敏）的 SHA-256，因为该 manifest
本身也进了 ZIP。故 manifest 里的值与本目录文件的实测值**按设计不同**：

| 文件 | 交付副本（manifest 钉定） | 本目录脱敏副本 |
|---|---|---|
| `reports/customer-ptt-report.json` | `5b1666c40555576117867f63105b8752114c47d7f67920ecaae3e68c465a7b3d` | `d20065465760b7842b088f50629a2d95414a488f69ee8eefe7272ace5228b172` |
| `reports/diarization-windows-dq4-report.json` | `88f1f68cebc94d62f4a9b9a80a84eb2f18f564a03a9e9b0a966b27c28db75922` | `439acf18bbe1cfee8c27037c5a0e08beb8949dc8820a972cd8fbc1538d3728e5` |
| `reports/package-install-ptt-report.json` | `d5396beaab15ba151bb52500a5c6bd64c8ddbdeddc3df9aed8ca6d216c7e6c4b`（不在 manifest 内） | `a5cfa6d5e418c2ef4d00f1ef373b25ffe1ea7860cdf9980e8fbaf86382e88f91` |

`ACCEPTANCE-SUMMARY.md` 无需脱敏，仓库副本与交付副本一致，哈希即 manifest 中的 `summary_sha256`。

## 报告范围说明

manifest 的受检 `reports` 为 `customer-ptt-report.json`（必需模式）与
`diarization-windows-dq4-report.json`（本版角色分离链路更换的直接证据，4 条 ≥ 120 s 的丁桥现场
录音，与 Diagnostics 构建同身份）。`package-install-ptt-report.json` 是从最终交付 ZIP 取出的 Demo HAP
安装后所跑的复测（`--installed-package`，取安装包身份），结论 PASS，验证的是交付包产物而非构建产物，
故单列、不入受检列表。

`speaker-vad-turn` 按 0.3.20–0.3.25 同一口径豁免（缺客户目标说话人夹具），manifest 与摘要均已披露。

## 取代关系

本目录取代同版本早前两轮未交付的构建（`719f34ee`：变更日志含测试机型号，被脱敏门禁拒绝；
`2a9f9cf3`：在组包完成后追加了「相邻同人句子合并」产品改动）。两轮的 `customer-ptt` 与
`diarization-windows` 结论与本轮一致（PASS，DER 12.10%）。
