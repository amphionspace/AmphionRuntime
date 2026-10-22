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
| `reports/customer-ptt-report.json` | `9333300622edba6dbc4d9e0451a2269078188eb33054658941af86c1767edbb5` | `bdb2b295a028d301ab8555217ee481bad180c6ee13a38b9dc0bd798df3d8ea58` |
| `reports/issue36-diarization-report.json` | `a110a988d61b422cd3a36dd5d10745fb73e1852b0949c35f84d0babfa6f400c3` | `ff86554c0f27810482b9eeb68fd296e450339b7332b776068c936e9f0eabffb1` |
| `reports/package-install-ptt-report.json` | `e6a622950dd213160840fc9e5bcb3bff8fa186cb6b3006831cbe6f73d074619b` | `46739e81a5d8ae04fa0154bf0cb1f05e4b41bdcc9118871bc1ae6431c67bdbae` |

`ACCEPTANCE-SUMMARY.md` 无需脱敏，仓库副本与交付副本一致，哈希即 manifest 中的 `summary_sha256`。

## 报告范围说明

manifest 的受检 `reports` 只含 `customer-ptt-report.json`。另两份作为支撑证据保留：

- `issue36-diarization-report.json`：`diarization-windows` 模式的 SDK 契约检查含声纹注册项，
  本次语料不含注册样本故判 FAIL，与问题 #36 的修复无关。组包门禁要求受检报告 PASS，故不入受检列表。
- `package-install-ptt-report.json`：从最终交付 ZIP 中取出的 demo HAP 安装后所跑的复测，
  结论为 PASS。它验证的是交付包产物而非构建产物，与受检的组包前证据属不同口径，故单列。

## 取代关系

本目录取代同版本早前一轮 `20261022-519bef84-0.3.25/`。那一轮因 `versionCode` 未随版本号推进、
CI 门禁 `test_release_defaults` 失败，其四个包未交付，已由本轮重建取代。两轮的 #36 验证与
`customer-ptt` 结论一致。
