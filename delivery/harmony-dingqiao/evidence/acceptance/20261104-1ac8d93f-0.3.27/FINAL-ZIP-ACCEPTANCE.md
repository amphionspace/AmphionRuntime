# HarmonyOS ASR SDK 0.3.27 最终 ZIP 验收报告

> 本文件放在最终 ZIP 之外，绑定该 ZIP 自身的 SHA-256，不随包交付。
>
> 本文件**按设计记载测试机型号与序列号**：随包摘要里这两项被脱敏门禁拒绝，因此在摘要中写的是
> 「机型与序列号见外置最终报告」。包内文档的脱敏门禁不适用于本文件。

验收结论：**两处产品变更（角色归属改由声纹身份决定、静音不再被转写出"嗯"）、生命周期与资源通过；
`speaker-vad-turn` 模式沿用记录在案的豁免**（夹具在本机不可重建，本版未改动机主识别代码，详见「豁免与未覆盖」）。

## 交付身份

| 项目 | 冻结值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.27.zip` |
| SHA-256 | `0408b5577ebe4a8d94fbb3c76b8a3c1f092207b9fd24b0d0c5f8a399b59efd0c` |
| 字节数 | 1939583071 |
| SDK / Demo 版本 | 0.3.27 / 0.3.27（versionCode 327） |
| 源码提交 | `1ac8d93f95473a8b8c0b16e71151c57e1647fab9` |
| 交付分支 | `release/harmony-0.3.27`（自 `main` 的 #286 合并提交切出；组包时工作区干净） |
| 基线 | 客户实际收到的 0.3.26（源码 `927bda6e`，完整 ZIP `860d731f…`，带 speaker-vad-turn 豁免） |
| 能力及架构 | 中英 ZH_EN、ASR + 角色分离（Sortformer + 声纹身份）+ 机主识别、arm64-v8a，模型内置 |
| 真机 | HUAWEI VYG-AL30，HarmonyOS 7.0.0.109(SP6C00E105R5P4)，API 26，arm64-v8a，序列号 7GK0226326015655 |
| 签名与授权 | 本地 DevEco 自签证书（`signing-project`，叶证书有效期至 2049-03-16）；授权不绑设备（白名单文件为空），与 0.3.26 口径一致 |
| 原生库 | 与客户已收到的 0.3.26 逐字节相同：`libsherpa-onnx-c-api.so` `392ca65a…`（2026-10-29 含补丁 0036/0037 的构建）、`libonnxruntime.so` `57abce89…`、`libamphion_audio_processing.so` `f193d11d…` |

## 子包与产物哈希

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| `release-sdk/amphion-harmony-asr-sdk-v0.3.27-20261104.zip` | 390468432 | `9a136daa9e69543267971a1f7d1b1e81eaaf3af0b4b676abfd7a61da33a667c5` |
| `diagnostics-sdk/Amphion-ASR-Diagnostics-SDK.zip` | 773934394 | `7496f8ed0c6d3996a92e0c024ac0a36fcc6fb8c285c761210de144f50720f192` |
| 包内公开 HAR `har/amphion_dingqiao.har` | — | `36a273da4e359a32bd8dfabef640778416c653d58380a1ed72635c0603f939db` |
| 包内已签名 Diagnostics Demo HAP `diagnostics-demo/amphion_asr_demo-diagnostics-signed.hap` | — | `4c5f8798d069e276498c10e5df6d682ce6085946b8b58d993160f8482ee390ef` |
| 组包前验收摘要 `docs/ACCEPTANCE-SUMMARY.md` | — | `73526f76ca4d81b970a8c27d27afad7eec15261b5c7999b0e900695e7c49072a` |
| `docs/acceptance-manifest.json` | — | `0d1aeef94cd91c54df0f8061ec8744d3ccd1a0ea11f2f118f7014e37e001e31e` |
| 受检报告 `docs/reports/customer-ptt-report.json` | — | `ec92316a3957e6666d0cf77e167aa6640bb03b774103f17ceadf072f58216bcb` |
| 受检报告 `docs/reports/diarization-windows-dq4-report.json` | — | `5e482bf02b3fd710cce300eed93e727df813324e9b81aa644c36e12752433cdf` |
| 装回复测报告（不随包） `package-install-ptt-report.json` | — | `9ea0544b4185707391a83944d7abb7b44d16a71543073b5922031ffd492db44d` |

诊断构建身份：`build_mode=diagnostics`，`git_commit=1ac8d93f`，源码指纹 `f3e2785d…`；两个子包、两份受检报告与包内
`docs/build-identity.json` 同绑该身份。

## 已执行验证

| 验证 | 结果 | 证据及实际范围 |
|---|---|---|
| Release 子包（SDK-only）门禁 | PASS | 自包含 HAR 的警务资产 / ASR 与声纹模型 / 原生库 / 目标说话人模型策略与本地产物一致；在干净客户主机上安装并编译通过；HAR 版本 0.3.27；模型清单 v2（9 资产）与固定 ZH_EN ONNX MD5；脱敏门禁 16 文件 / 1 个 HAR；`validate_asr_sdk_delivery.py` 全部通过 |
| API 23（OpenHarmony 6.1）编译兼容 | PASS | 54 个公开 TypeScript 文件，独立 es2abc（sha256 `279d82ed…`，与 0.3.23~0.3.26 同一二进制） |
| ZIP 完整性与内容校验 | PASS | 固定外层 SHA-256 后解压，包内 `docs/checksums.txt` 全部 50 项逐条一致；包内 51 个文件，无评测探针/语料/内部路径（demo-source 仍带自 0.3.25 起随包的 demo 侧工具 `MindirProbe.ets`、`HotwordDeviceEval.ets` 等公开桩，见 0.3.26 报告，非 SDK 代码） |
| 包内身份一致性 | PASS | `docs/build-identity.json` 与 Diagnostics 子包逐字段一致（`created_at` 除外）；Release 子包 provenance 的源码提交与 Diagnostics 身份同为 `1ac8d93f` |
| 真机 `customer-ptt`（组包前，Diagnostics 构建） | PASS | 12/12 轮，空 final 率 0.000，原生流 0 泄漏，内存 PASS（RSS 390.4 → 398.6 MiB，增长 8.21 MiB，峰值 417.5 MiB，HWM 426.4 MiB），线程 52 → 48，CPU 单核等效均值 123.6% / p95 158.7% |
| 真机 `diarization-windows`（组包前，客户现场录音 4 条 ≥ 120 s，声纹身份默认开启） | PASS | 4/4 轮，角色生命周期 PASS，每条角色结果数 4/2/2/2，结束到最终角色结果 1114~2416 ms，推理 RTF 0.255~0.271；内存通用判定 PASS、角色分离资源评估 advisory（INCONCLUSIVE）：RSS 756.8 → 812.4 MiB，增长 55.61 MiB，峰值 878.2 MiB，HWM 915.4 MiB，斜率 4.1 MiB/min（15 分钟窗口）；CPU 均值 185.7% / p95 278.7% |
| 最终 ZIP 内 Diagnostics Demo 装机复测 | PASS | 从该 ZIP 解压、`hdc install -r` 包内 `-signed.hap`，`--installed-package` 取安装包身份（**versionName 0.3.27 / versionCode 327**，`com.amphion.asr.harmony.demo`，arm64-v8a）；`customer-ptt` 12/12 轮，空 final 率 0.000，原生流 0 泄漏，内存 PASS（增长 13.27 MiB、峰值 421.2 MiB），CPU 均值 120.6% / p95 155.8% |
| 角色归属改善（本版产品变更一） | 已在 0.3.27 冻结前测得 | 客户 4 条现网录音留一法标定 34/34（0.3.26 链路 28/34）；真机 6 例"依次发言"工单复现修复 4/6，余 2 例由说话人自身声纹相似度（0.546 / 0.523 > 0.50）解释；阈值 0.50 在 25 位真实会议说话人、300 个真实片段上合计错误率 0.346%（0.45 为 1.211%） |
| 静音"嗯"门禁（本版产品变更二） | 已在冻结前测得 | 客户 52.2 s 近静音复现文件被正确丢弃；客户现场远场 90 段 + 公开语料 500 条 0 误丢；真机 A/B 带/不带修复输出逐字相同（真机不复现该现象，只能证明无回归） |
| 发热 / 内存长跑 | 已在冻结前测得 | 同机 143.8 分钟（声纹开启）：净自发热 +2.2 °C、70 分钟后进入热平台、无降频；RSS 饱和型约 805 MB 平台、HWM 1044 MB。无 `'model'` 模式对照臂 |
| 主机回归 | PASS | 鸿蒙主机门禁 `asr/tools/tests/test_harmony*`（61 个模块）500 项通过；交付工具 `delivery/harmony-dingqiao/delivery` 270 项通过（含 `test_release_defaults` 版本一致性、`test_run_device_stress` 73、`test_validate_asr_sdk_delivery` 24）；仓库布局 / 可观测性 / 版本一致性检查通过 |

## 本轮过程中发现并处置的三个问题（均非产品缺陷）

1. **sherpa 派生源码树播种了旧库**（冻结 `316135a4` 的 Release 子包被自包含 HAR 校验拦下）：2026-11-02 新建的派生树
   `harmony-os/.../libs` 里是 2026-10-15 的 `630630c0…`（缺补丁 0036/0037），而 SDK 本地库、诊断/调试 HAP 与客户已收到
   的 0.3.26 内的库均为 `392ca65a…`。两棵派生树源码逐文件一致；旧库只进入 `sherpa_onnx.har`，HAP 打包时被同名库覆盖，
   **从未到过设备**。按 `asr/tools/05_package_har_libs.sh` 同步后 SDK 本地库字节不变。
2. **随包 CHANGELOG 缺交付边界声明**（`316135a4` → `b84bb51d`）：`validate_asr_sdk_delivery.py` 要求当前版本节含
   "目标说话人增强…不包含…不能启用"，0.3.27 节漏写；补一行后提交号变化，构建身份绑定提交，全部重做。
3. **演示工程版本号未随 0.3.27 同步**（`b84bb51d` → `1ac8d93f`）：从完整 ZIP 装回的 Demo HAP 报 versionName 0.3.26 /
   versionCode 326——`delivery/harmony-dingqiao/AppScope/app.json5`、根 `oh-package.json5`、entry 模块仍为 0.3.26
   （冻结时只改了 `asr/harmony` 下的 AppScope）。补齐三处后再次全链重做，装回复测确认 0.3.27 / 327。

三次冻结的 SDK 源码、构建输入与原生库完全相同；前两次的真机结果（`customer-ptt` 12/12、`diarization-windows` 4/4、
`b84bb51d` 的装回复测 12/12）与本轮一致，保留于各自暂存目录作过程证据，不随包。

## 豁免与未覆盖

- **`speaker-vad-turn` 豁免（理由与 0.3.26 不同）**：0.3.26 首次具备夹具并实跑（归属断言 6/6 通过，仅载体自设的
  1200 ms 收尾预算未达成，该预算此后已按实测放宽到 2000 ms）。本轮生成文本断言所需的主机 `sherpa-onnx` 二进制在本机
  不可用（旧构建缺 `libonnxruntime.1.24.4.dylib`，当前派生树无主机构建），夹具不可重建。本版未改动机主识别相关代码
  （`Runtime.ets` 的改动限于"嗯"门禁）。豁免理由在 `docs/acceptance-manifest.json` 与 `docs/ACCEPTANCE-SUMMARY.md`
  中均已披露。
- **角色分离的已知限制**（28 场公开真实会议 + 客户 4 条）：3 人会议多报成 4 人（3 人场 5 场中 3 场），1 秒级短发言
  误报与标签抖动上升，5 人以上超出标称范围，客户录音 `111223-816` 仍有约 22% 混淆。
- **声纹的增量发热代价未测**：143.8 分钟长跑只有声纹开启一臂，没有 `'model'` 模式对照臂。
- **内存峰值接近 1 GB 未归因**：长跑 HWM 1044 MB、本轮 15 分钟 HWM 915 MB，为饱和型而非无界增长，但高水位的持有者未定位。
- **"嗯"门禁的现场覆盖待确认**：客户提供的复现文件为立体声且左声道全零，SDK 实际收到的输入形态需客户侧转储确认；
  门禁挡不住普通房间噪声里的幻觉。
- **Android 端不在本次范围**：声纹身份接线在 Android 上尚未完成。
- **功耗**：USB 供电下电流读数为净充电电流，绝对功耗无法测量。

## 发布资格

本包为**未发布候选**（`published: false`）：`speaker-vad-turn` 受检报告按豁免处理，按交付流程不具备正式发布资格；
交付分支 `release/harmony-0.3.27` 尚未合入 main。与 0.3.26 相同，按用户明确授权可带披露豁免交付与归档。
状态记录见 `delivery/candidate-reports/harmony-0.3.27-20261104/`。
