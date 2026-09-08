# 鸿蒙 ASR 默认交付规范

默认交付沿用 0.3.13：完整 ZIP、外置 ZIP SHA-256 文件、中文交付邮件和最终 ZIP 专属验收报告。用户明确要求调整时，以本次要求为准。

## 固定目录结构

```text
Amphion-Harmony-ASR-Complete-<version>.zip
└── Amphion-Harmony-ASR-Complete-<version>/
    ├── README.md
    ├── release-sdk/
    │   └── amphion-harmony-asr-sdk-v<version>-<date>.zip
    ├── diagnostics-sdk/
    │   └── Amphion-ASR-Diagnostics-SDK.zip
    ├── diagnostics-demo/
    │   └── amphion_asr_demo-diagnostics-signed.hap
    ├── demo-source/
    │   ├── libs/amphion_dingqiao.har
    │   ├── AppScope/
    │   ├── samples/dingqiao-demo/
    │   ├── hvigor/hvigor-config.json5
    │   ├── build-profile.json5
    │   ├── hvigorfile.ts
    │   ├── oh-package.json5
    │   └── TRANSFORMATIONS.md
    └── docs/
        ├── ACCEPTANCE-SUMMARY.md
        ├── acceptance-manifest.json
        ├── build-identity.json
        ├── checksums.txt
        └── <acceptance-manifest 引用的相对报告路径>
Amphion-Harmony-ASR-Complete-<version>.zip.sha256
```

正式 SDK、Debug/Diagnostics SDK、已签名 Diagnostics Demo 和独立 Demo 源码为默认四类交付内容。源码只依赖包内公开 HAR；不包含客户授权、签名配置或私钥。单独提供 Demo 源码 ZIP、普通 Demo HAP 可作为补充，不替代以上内容。

## 生成与冻结

1. 确定上一交付版本及其源码提交，逐项核对至本次构建提交的 PR。更新受控 CHANGELOG 和升级说明，特别检查回调语义变化；不要把旧版本已有能力重复列为新增。
2. 冻结代码、版本、授权、签名及组包规则，构建 Release 和 Diagnostics，使用现有 build identity 门禁绑定四个组件 HAR、HAP 和源码。复用对应二进制的有效真机证据。
3. 用 `pack_dingqiao_harmony_customer_delivery.sh` 和 `pack_diagnostics_sdk.sh` 准备子包；生成 `ACCEPTANCE-SUMMARY.md` 和 `acceptance-manifest.json`。完整包默认要求 Diagnostics 的 `speaker-vad-turn`、`customer-ptt` 报告与其构建身份匹配。
4. 运行 `delivery/pack_complete_asr_delivery.sh [output-root]`。非默认输入通过 `RELEASE_SDK_ZIP`、`DIAGNOSTICS_SDK_ZIP`、`ACCEPTANCE_SUMMARY`、`ACCEPTANCE_MANIFEST` 指定；版本和日期使用现有 `AMPHION_RUNTIME_VERSION`、`AMPHION_BUILD_DATE`。包内摘要属于组包前证据，不能写成尚未执行的 ZIP 验收。
5. 完成 ZIP 解包验收后，以[邮件模板](customer/DELIVERY_EMAIL_TEMPLATE.md)生成独立邮件草稿。模板不是可直接发送的版本结论；替换占位内容并根据实际 PR、交付输入和报告填写，不自动发送。

## 最终 ZIP 验收

- 固定最终 ZIP SHA-256，从该 ZIP 解压，直接安装包内 Diagnostics Demo；核对 Debug HAR/HAP 与包内 identity。
- 使用解压的 Demo 源码及正式 HAR 独立构建，仅补入本地授权和签名。验证依赖来自 ZIP，安装必须明确选择 `-signed.hap`（`*signed.hap` 会误匹配 unsigned），确认成功后才启动测试。记录输入、构建产物哈希及安装结果。
- SDK 用例使用当前安装包身份，不得让测试脚本重新安装仓库产物。新增或变更能力补充相应专项；角色分离分窗至少覆盖 120 秒目标后的明确句末、中间批和终结批，并检查冻结、降级和回调顺序。
- 源码版移除了内部探针，`liveStreams=0` 不可当作实测资源回收证据。保留短用例内存 INCONCLUSIVE；生命周期验收不能代替精度、长稳或断网网络观测。
- 归档根报告、逐轮回调、内存、hilog、输入映射及哈希，脱敏且不提交 PCM、授权或签名材料。首轮未覆盖前置条件仍保留原始 FAIL，解释原因，不覆写为 PASS；产品失败不能改称未覆盖条件。
- 最终 ZIP 专属报告、邮件放在 ZIP 外，绑定其 SHA-256，避免把报告回填 ZIP 后改变已验收输入。更改任何 ZIP 内容须生成新的身份记录并判断相关验证是否失效；仅邮件/外置说明变化不重跑真机。

合入遵守仓库 PR 门禁：当前 HEAD 检查通过，拉取全部 review threads 并处理有效问题。二进制未改变的模板、文档和组包调整使用小型组包测试验证，复用已冻结二进制证据，不重新生成大型交付包。
