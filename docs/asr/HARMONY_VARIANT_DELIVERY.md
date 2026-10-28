# 鸿蒙变体交付链路

变体包 = 换 ASR 模型、（可选）不随包发行警务后处理、独立 bundleName 的交付包。
四川话包是第一个用例。

## 为什么独立成一条链路

既有打包脚本把基线的模型身份、完整警务资产、版本号序列都写死为不变量 —— 那些断言
对基线是对的。变体若去放宽它们，等于**让基线从此不再断言自己的身份**：比如把源包名
校验从「写死比对 `…-1.4.0.tar.gz`」改成形状正则，基线也就跟着失去了这项保护。

所以变体自带工作区、自带校验。**既有脚本一行不改** —— 打基线包或其他系统的包，
走的代码路径与 main 完全相同。

## 怎么出包（两阶段）

验收证据必须在**组包前**、在**受测产物**上跑出来，再作为组包的必需输入 —— 与基线
流程一致。所以链路是两阶段的，不能一步到底。

### 阶段一：出受测产物

```bash
<同下方环境变量> bash delivery/harmony-dingqiao/delivery/pack_harmony_variant_delivery.sh \
  --artifacts-only <输出目录>
```

产出 `<输出目录>/artifacts/dingqiao-demo.hap` 及其 sha256。

### 阶段二：跑验收，再组包

在该 HAP 上跑验收（真机），把 `ACCEPTANCE-SUMMARY.md` + `acceptance-manifest.json` +
`reports/` 放进一个目录，然后：

```bash
AMPHION_VARIANT_ACCEPTANCE_DIR=<证据目录> <同下方环境变量> \
  bash delivery/harmony-dingqiao/delivery/pack_harmony_variant_delivery.sh <输出目录>
```

组包会强校验：证据与出包**同一提交**、摘要与各报告指纹、每份报告判定为 PASS/MEASURED、
豁免项必须写原因。校验通过后证据被纳入包内 `docs/acceptance/`。

**证据绑定源码提交，不绑定最终 ZIP 哈希** —— 验收在组包前跑完，用 ZIP 哈希绑定会形成
循环。基线摘要同样写明「最终 ZIP 的验收报告绑定其自身 SHA-256，另行外置」。

## 环境变量

```bash
AMPHION_VARIANT_NAME=chuan-179m-tsx-v1 \
AMPHION_VARIANT_MODEL_DIR=$PWD/asr/tools/demo-model/amphion-chuan-179m-tsx-v1-1.0.0-chunk32-lc256-edge-transducer \
AMPHION_VARIANT_MODEL_POLICY=$PWD/delivery/harmony-dingqiao/delivery/dingqiao_chuan_model_md5.json \
AMPHION_VARIANT_POLICE_POSTPROCESS=off \
AMPHION_VARIANT_BUNDLE_NAME=com.amphion.asr.harmony.repro \
AMPHION_VARIANT_APP_LABEL="Amphion 四川话识别" \
HARMONY_SIGNING_CONFIG=$PWD/.secure/harmony-signing-repro.json \
HARMONY_API23_ES2ABC=$PWD/.cache/harmony-api23-sdk-6.1-release/ets/build-tools/ets-loader/bin/ark/build-mac/bin/es2abc \
NODE_ADDON_API_PREPATCHED=$PWD/.cache/speaker-screen-repro-acf477c2/node-addon-api \
  bash delivery/harmony-dingqiao/delivery/pack_harmony_variant_delivery.sh
```

`--prepare-only` 只准备工作区（秒级验证隔离逻辑），`--keep-workspace` 失败后保留现场。

## 产出

```
Amphion-Harmony-ASR-<变体>-<日期>/
├── release-sdk/       自包含 amphion_dingqiao.har + 客户文档
├── diagnostics-sdk/   四个 diagnostics HAR + 采集工具 + 诊断文档
├── diagnostics-demo/  签名 demo HAP
├── demo-source/       demo 源码（git archive 按提交固定，已剥离内部模块依赖）
└── docs/              溯源、变体校验报告、API 23 兼容报告、校验清单
```

## 新增脚本

| 脚本 | 作用 |
|---|---|
| `pack_harmony_variant_delivery.sh` | 主链路 |
| `verify_variant_delivery.py` | 变体专属校验：模型身份、警务资产裁剪态、bundleName / 显示名 |
| `prepare_variant_demo_source.py` | 交付源码依赖自洽：逐个裸模块导入核查 |
| `install_variant_signing.py` | 把签名材料写进工作区构建配置 |
| `write_variant_provenance.py` | 溯源跟随本次实际使用的模型策略 |
| `point_fetchcontent_at_local_source.py` | CMake 探不到 git 时指向本地 node-addon-api |
| `trim_police_postprocessing.py` | 裁掉后处理资产，只留解码期热词表 |
| `rebrand_demo_app.py` | 改写 bundleName / 显示名 / 版本名 |

复用既有只读校验（与变体无关）：API 23 编译器兼容性、交付脱敏、打包模型资产。

## 隔离的四个要点

1. **工作区是仓库的本地克隆**，不是手搭目录树。既有脚本要读 git 索引
   （`rev-parse :third_party/sherpa-onnx`），手搭的树没有 git 就只能重写一份。
2. **资产打包与自包含 HAR 组装一律调工作区副本** —— 这两个脚本按自身位置推导仓库根，
   用真实仓库的副本会把变体资产写进真实仓库，下一次基线出包会悄悄用上变体模型。
3. **`.derived/sherpa-onnx` 必须实体化为真实目录**。`prepare_sherpa_source.sh` 产出的是
   generation 目录 + 符号链接，而 hvigor 不跟随符号链接，报 `00303149 Path not found`
   —— 错误发生在配置阶段，离根因隔了一层。
4. **构建前 `ohpm install --all`**。工作区不带被忽略的 `oh_modules`，否则会意外用上
   开发机已装的包。

## 已知限制：裁剪态包上的 selftest 诊断入口

`--ps selftest true` 这个内部诊断入口在**不随包发行警务后处理**的变体包上会在警务用例处
抛错 —— `SdkSelfTest.ets` 无条件构造 `PoliceEnhancePipeline`，而该变体没有后处理资产。

**不去改 `SdkSelfTest.ets` 来适配**：`pack_complete_asr_delivery.sh` 对它做**精确文本改写**
（剥掉引用内部模块 `amphion_police` 的那段，0.3.24「修复三」加的保护）。改动它的 import 行或
`police.close();` 都会让改写匹配不到，`test_complete_delivery_package` 立刻报
「expected one SdkSelfTest police import rewrite, found 0」—— 即**破坏基线交付打包**。

selftest 是内部诊断，不在任何门禁或交付流程里，故接受该限制。变体包的端侧验证走
`run_device_stress.py`（需在仓库外用脚本副本改 `BUNDLE`，见下文排错留档）。

## 变体身份靠什么承载

版本号序列属于发布治理（`asr_release_tracker.py`），变体不去动它。身份由三处承载：

- **包名**：`Amphion-Harmony-ASR-<变体>-<日期>`
- **bundleName**：独立 bundle，可与基线包在同一台设备上共存、互不覆盖
- **溯源**：`docs/BUILD_PROVENANCE.json` 的 `variant` / `model_id` / `model_md5_policy` /
  `package_identity.police_postprocess`

## 四川话包的实测

设备 SN `7GK0226326015655`（OpenHarmony 7.0），语料 `aishell3_test_hotwords_500` 取 60 条，
20 ms 实时节奏喂入，用**交付包内的 HAP** 装机实测：

| 项 | 结果 |
|---|---|
| 会话 | 60/60 完成，错误 0，空 final 率 0.000 |
| 字准确率 | 93.34% |
| 整句全对 | 65.00% |
| 峰值 RSS | 522.7 MB，内存门禁 PASS |

与基线同批对照（同设备同语料）：基线 94.25% / 68.33%，本变体 −0.91pp 字准、−3.33pp 整句。

**排错留档**：第一次复测得到的是基线的数字（94.25%，逐条文本与基线 60/60 完全相同）。
原因是 `run_device_stress.py` 的 `BUNDLE` 写死为 `…demo`，而该文件按隔离要求还原到了
main、不再有环境变量开关，于是压测打到的是仍装在机上的基线包。驱动变体包需要在仓库外
用脚本副本改 `BUNDLE` 并设 `PYTHONPATH` 指向仓库根。**只看聚合指标不会发现这个错误 ——
是逐条文本比对暴露的。**
