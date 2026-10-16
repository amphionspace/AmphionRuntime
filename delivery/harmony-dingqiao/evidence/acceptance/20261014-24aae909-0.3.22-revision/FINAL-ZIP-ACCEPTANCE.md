# Amphion HarmonyOS ASR 0.3.22 修订包（24aae909）— 最终 ZIP 专属验收

本文件绑定下列 ZIP 的 SHA-256，放在该 ZIP 之外。与同目录的 `ACCEPTANCE-SUMMARY.md`
（组包前证据）互不替代。

## 被验收对象

| 项 | 值 |
|---|---|
| 文件 | `Amphion-Harmony-ASR-Complete-0.3.22.zip` |
| 字节数 | 1 717 550 985 |
| SHA-256 | `8da5167d12d062e1d800ad8df358f4d8c75e7adbb560fb399a29c5f471a38172` |
| 源码提交 | `24aae909b1765edcd99dc8554771b7bdaac25c9c` |
| 组包目录 | `delivery/harmony-dingqiao/build/complete-sdk-0.3.22-24aae909/` |

## 输入核验

全部取值自解压出来的 ZIP，未使用仓库构建产物。

| 核验项 | 结果 |
|---|---|
| ZIP SHA-256 复算 | PASS，`8da5167d…`，与外置 `.sha256` 一致 |
| 包内 Demo HAP SHA-256 | PASS，`4cb4cab0aff1e12a74e4c987fa20c0f64292a7e7a82b881ba2050d62b42df8e7`，等于包内 `docs/build-identity.json` 记录值 |
| 包内 `docs/build-identity.json` | PASS，`git_commit=24aae909…`，`build_mode=diagnostics` |
| **包内正式 SDK 构建模式** | **PASS，自包含 HAR 内 `BUILD_MODE_NAME = 'debug'`** —— 诊断模块未编入正式 SDK，这是本轮相对 10-13 包的关键修正 |
| 包内正式 SDK 溯源 | PASS，`release-sdk/.../docs/BUILD_PROVENANCE.json` 的 `git_commit` 同为 `24aae909…` |
| 包内四类内容齐备 | PASS，正式 SDK 340 MB、Diagnostics SDK 666 MB、已签名 Diagnostics Demo 425 MB、Demo 源码 334 MB、docs 260 KB |

## 真机安装与复测

| 项 | 值 |
|---|---|
| 设备 | Kirin 9020，OpenHarmony-6.1.1.120，arm64-v8a |
| 安装来源 | 解压后的 `diagnostics-demo/amphion_asr_demo-diagnostics-signed.hap`（明确选择 `-signed.hap`） |
| 安装结果 | `install bundle successfully` |
| 复测身份来源 | `installed_package`（记录设备上该安装包的指纹，未让脚本重装仓库产物） |
| bundle / versionName | `com.amphion.asr.harmony.demo` / `0.3.22` |
| 安装包指纹 | `C57C213EF4678ACDE07350C565EE08076B154C58C3C60A0D7489A93E2E4E6537` |

`customer-ptt` 复测，100 轮、24 个语料：

| 指标 | 结果 |
|---|---|
| `overall_status` | **PASS**，0 失败项，100 轮逐轮 PASS |
| 空 final | PASS，0 条，比例 0.000（阈值 0.05） |
| 内存 | PASS，RSS 增长 49.174 MB（阈值 64.0），观测窗口 430.073 秒，增速 **0.114 MB/s**；线程增长 **0**（阈值 2）；head 506.486 MB，tail 555.660 MB，peak 593.871 MB |

逐轮回调与资源采样见 `reports/final-zip-customer-ptt-report.json`。

## 与组包前验收的关系

组包前验收（`reports/customer-ptt-report.json`）跑在同一提交的 diagnostics 构建上，其
`build_identity` 与 Diagnostics 子包的 `build-identity.json` 逐字段相等，这是完整包组装的门禁要求。
本次最终 ZIP 复测改用安装包身份，用于证明「从该 ZIP 装出来的东西能跑且结论一致」。两轮均 PASS、
空 final 均 0.000，内存增速 0.083 / 0.114 MB/s。

## 未验证项

组包前验收摘要的「未验证项」一节（共 12 条）整体适用于本 ZIP，不因最终 ZIP 复测通过而改变。
其中影响交付结论的三条：

- **问题一（锁屏变慢）未解决。** 根因是进程级 cpuset；`cpuIds` 与 `scheduling.qos` 两条入口均已
  实测排除；角色分离链全部开销 0.180× 补不上 0.20× 缺口。
- **问题二的主要症状仍在。** 最大无输出空档由 105 s 降至 72.5 s。
- **问题三的现场效果未验证。** 三臂为我方构造场景，客户现场的 21.6 s 未用本版复测。

此外 `speaker-vad-turn` 模式延续豁免，本 ZIP 不含该模式的有效证据。
