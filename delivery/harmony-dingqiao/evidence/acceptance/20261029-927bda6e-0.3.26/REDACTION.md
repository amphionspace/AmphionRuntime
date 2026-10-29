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
| `reports/customer-ptt-report.json` | `07174aa08f4abc1c6e4fc85de5bbe8b46850fbee33e0988ac032100a61082027` | `be24b828cf4adc9689d97720483ee22aeb5f7e129ad75af485a95434f7763ca1` |
| `reports/diarization-windows-dq4-report.json` | `d0bc9f7a2d2278e4c8e0f010d18438da3a116a3113d58623f4fd3442747d7112` | `7a962db4f84d018f4ba3a03e9996502b802c4263f13143430afce8a693f5a631` |
| `reports/package-install-ptt-report.json` | `05297d3e22bdaada4278b23ec618ca44794a5e3b5cf0bbfbd1864c8f82f6e322`（不在 manifest 内） | `cc8b122038ff97cb8b1a2bec9bfc9025b9f73ff18a06c1197dab82a6e6b02bd4` |

`ACCEPTANCE-SUMMARY.md` 无需脱敏，仓库副本与交付副本一致，哈希即 manifest 中的 `summary_sha256`
（`ef634d129aab80441cd5b04e66ded4419df8c3047988c1efec93081720bf83e7`）。

## 报告范围说明

manifest 的受检 `reports` 为 `customer-ptt-report.json`（必需模式）与
`diarization-windows-dq4-report.json`（角色分离链路更换的直接证据，4 条 ≥ 120 s 的丁桥现场录音，
与 Diagnostics 构建同身份）。`package-install-ptt-report.json` 是从最终交付 ZIP 取出的 Demo HAP
安装后所跑的复测（`--installed-package`，取安装包身份），结论 PASS，验证的是交付包产物而非构建
产物，故单列、不入受检列表。

`speaker-vad-turn` 本轮**首次具备夹具**并实际执行：6 例归属断言全部通过，但单轮判定仍为 FAIL，
因为载体自设的「收尾补救 finish 到非空 final ≤ 1200 ms」预算未达成（实测 1652~1732 ms，修复前
后基本不变）。受检报告只收 PASS 的模式，故该模式仍按豁免处理，豁免理由与证据在 manifest 与
摘要中均已披露。该模式与热词 7 例夹具的逐例产物属支撑证据，未随包，留存于
`~/.cache/amphion-runtime/delivery-staging/asr/harmony/0.3.26/927bda6e/scratch/`。

## 取代关系

本目录取代同版本早前三轮未交付的构建：

| 提交 | 未交付原因 |
|---|---|
| `719f34ee` | 变更日志含测试机型号，被脱敏门禁拒绝 |
| `2a9f9cf3` | 组包完成后追加了「相邻同人句子合并」产品改动 |
| `2d49bec5` | 组包完成后追加了热词（补丁 0036 / 0037）与机主识别两组修复 |

四轮的 `customer-ptt` 与 `diarization-windows` 结论一致（PASS，DER 12.10%）。
