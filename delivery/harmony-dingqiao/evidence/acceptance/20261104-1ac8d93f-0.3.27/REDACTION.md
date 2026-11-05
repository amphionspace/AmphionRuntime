# 本目录报告的脱敏说明

`reports/*.json` 是**脱敏副本**，不是逐字节的原始产物。脱敏用
`tools/delivery/release_gate_archive_artifacts.py` 的 `redact_json` / `device_alias`，
与 `tools/check_repository_observability.py` 的入库要求一致：

| 字段 | 处理 |
|---|---|
| `resultHex`（逐轮识别文本的十六进制） | 替换为 `<redacted>` |
| 设备序列号 | 替换为化名 `device-9d33cec60055`（`sha256(serial)[:12]`，与 0.3.26 同一台设备） |
| 本机家目录绝对路径 | 替换为 `<LOCAL_PATH>` |

## 哈希对照

`acceptance-manifest.json` 钉定的是**随 ZIP 交付的那一份**（未脱敏）的 SHA-256，因为该 manifest
本身也进了 ZIP。故 manifest 里的值与本目录文件的实测值**按设计不同**：

| 文件 | 交付副本（manifest 钉定） | 本目录脱敏副本 |
|---|---|---|
| `reports/customer-ptt-report.json` | `ec92316a3957e6666d0cf77e167aa6640bb03b774103f17ceadf072f58216bcb` | `a7a91c9d7a71cf0a935e36a7fa2184a96ff96a175936e21a0bbba1498367b582` |
| `reports/diarization-windows-dq4-report.json` | `5e482bf02b3fd710cce300eed93e727df813324e9b81aa644c36e12752433cdf` | `7737c4456c1ffc7bec631350f9af32879fd2b3cf24df7da3a61fed523fc9117b` |
| `reports/package-install-ptt-report.json` | `9ea0544b4185707391a83944d7abb7b44d16a71543073b5922031ffd492db44d`（不在 manifest 内） | `7241a776bec135718b846d420ab5cc8ddef59ae528823e7e9439d1ca88644a3f` |

`ACCEPTANCE-SUMMARY.md` 与 `acceptance-manifest.json` 无需脱敏，仓库副本与交付副本一致：摘要哈希即 manifest 中的
`summary_sha256`（`73526f76ca4d81b970a8c27d27afad7eec15261b5c7999b0e900695e7c49072a`），manifest 哈希
`0d1aeef94cd91c54df0f8061ec8744d3ccd1a0ea11f2f118f7014e37e001e31e`。

## 报告范围说明

manifest 的受检 `reports` 为 `customer-ptt-report.json`（必需模式）与 `diarization-windows-dq4-report.json`
（角色归属改由声纹身份决定的直接证据，4 条 ≥ 120 s 的丁桥现场录音，与 Diagnostics 构建同身份）。
`package-install-ptt-report.json` 是从最终交付 ZIP 取出的 Diagnostics Demo HAP 安装后所跑的复测
（`--installed-package`，取安装包身份：versionName 0.3.27 / versionCode 327），结论 PASS，验证的是交付包产物
而非构建产物，故单列、不入受检列表。

`speaker-vad-turn` 本轮按豁免登记：目标说话人夹具在本机不可重建（主机 `sherpa-onnx` 二进制不可用），本版未改动
机主识别代码；0.3.26 曾实跑该模式、归属断言 6/6 通过。豁免理由在 manifest 与摘要中均已披露。

## 取代关系

本目录取代同版本早前两轮未交付的冻结：

| 提交 | 未交付原因 |
|---|---|
| `316135a4` | Release 子包被自包含 HAR 校验与交付校验先后拦下：sherpa 派生树播种了旧库（已同步，库未到过设备）；随包 CHANGELOG 当前版本节缺交付边界声明 |
| `b84bb51d` | 从完整 ZIP 装回的 Demo HAP 报 versionName 0.3.26 / versionCode 326（演示工程三处版本号未随 0.3.27 同步） |

三轮的 SDK 源码、构建输入与原生库完全相同；`customer-ptt`（12/12）与 `diarization-windows`（4/4，角色结果数 4/2/2/2）
结论一致。前两轮的产物与报告保留于各自暂存目录
`~/.cache/amphion-runtime/delivery-staging/asr/harmony/0.3.27/<commit>/`，不随包、不入库。
