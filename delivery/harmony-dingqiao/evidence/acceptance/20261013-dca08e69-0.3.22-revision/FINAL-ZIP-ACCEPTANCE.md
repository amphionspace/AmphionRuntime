# Amphion HarmonyOS ASR 0.3.22 修订包 — 最终 ZIP 专属验收

本文件绑定下列 ZIP 的 SHA-256，放在该 ZIP 之外。与同目录的 `ACCEPTANCE-SUMMARY.md`（组包前证据）互不替代。

## 被验收对象

| 项 | 值 |
|---|---|
| 文件 | `Amphion-Harmony-ASR-Complete-0.3.22.zip` |
| 字节数 | 1 717 525 283 |
| SHA-256 | `91840c4f85f332f4cd71ee191161c0865a18aeb28efe0dfdd383e9efebdfcd79` |
| 源码提交 | `dca08e694fd364162efe5257fca856d4ac107345` |
| 组包目录 | `delivery/harmony-dingqiao/build/complete-sdk-0.3.22-dca08e69/` |

## 输入核验

全部取值自解压出来的 ZIP，未使用仓库构建产物。

| 核验项 | 结果 |
|---|---|
| ZIP SHA-256 复算 | PASS，`91840c4f…`，与外置 `.sha256` 一致 |
| 包内 Demo HAP SHA-256 | PASS，`28e36e7cb1fb85e09f683266d9d172ff36a40b3398abdde0a6467388ece87122`，等于包内 `docs/build-identity.json` 记录值 |
| 包内 `docs/build-identity.json` | PASS，`git_commit=dca08e69…`，`build_mode=diagnostics` |
| 包内正式 SDK 构建模式 | PASS，自包含 HAR 内 `BUILD_MODE_NAME = 'debug'`，诊断模块未编入正式 SDK |
| 包内正式 SDK 溯源 | PASS，`release-sdk/.../docs/BUILD_PROVENANCE.json` 的 `git_commit` 同为 `dca08e69…` |
| 包内四类内容齐备 | PASS，正式 SDK 346 070 393 B、Diagnostics SDK 685 126 158 B、已签名 Diagnostics Demo HAP 432 007 238 B、Demo 源码 |

## 真机安装与复测

| 项 | 值 |
|---|---|
| 设备 | Kirin 9020，OpenHarmony-6.1.1.120，arm64-v8a，序列号 7GK0226326015655 |
| 安装来源 | 解压后的 `diagnostics-demo/amphion_asr_demo-diagnostics-signed.hap`（明确选择 `-signed.hap`） |
| 安装结果 | `install bundle successfully` |
| 复测身份来源 | `installed_package`（记录设备上该安装包的指纹，未让脚本重装仓库产物） |
| bundle / versionName / versionCode | `com.amphion.asr.harmony.demo` / `0.3.22` / `322` |
| 安装包指纹 | `C57C213EF4678ACDE07350C565EE08076B154C58C3C60A0D7489A93E2E4E6537` |

`customer-ptt` 复测，100 轮、24 个语料：

| 指标 | 结果 |
|---|---|
| `overall_status` | **PASS**，0 失败项，100 轮逐轮 PASS |
| 空 final | PASS，0 条，比例 0.000（阈值 0.05） |
| 内存 | PASS，RSS 增长 36.801 MB（阈值 64.0），观测窗口 429.635 秒，**增速 0.086 MB/s**；线程增长 1（阈值 2）；head 504.988 MB，tail 541.789 MB，peak 585.984 MB |

逐轮回调与资源采样见 `reports/final-zip-customer-ptt-report.json`。

## 与组包前验收的关系

组包前验收（`reports/customer-ptt-report.json`）跑在同一提交的 diagnostics 构建上，
其 `build_identity` 与 Diagnostics 子包的 `build-identity.json` 逐字段相等，这是完整包组装的门禁要求。
本次最终 ZIP 复测改用安装包身份，用于证明"从该 ZIP 装出来的东西能跑且结论一致"。
两轮结果一致（均 PASS、空 final 0.000、内存增速 0.083 / 0.086 MB/s）。

## 未验证项

组包前验收摘要的「未验证项」一节整体适用于本 ZIP，不因最终 ZIP 复测通过而改变。其中影响交付结论的两条：

- **问题一的熄屏症状未验证。** 仅验证 SDK 不再申请 background QoS，未验证熄屏后因此变快。需客户在其场景确认。
- **问题二的主要症状仍在。** 最大无输出空档由 105 s 降至 72.5 s，使用者仍会看到长时间无输出；残余归因待客户确认。

此外 `speaker-vad-turn` 模式延续豁免，本 ZIP 不含该模式的有效证据。
