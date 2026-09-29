# Android 鼎桥完整交付

执行顺序统一见[双端交付流程](../ASR_DELIVERY_WORKFLOW.md)。本文只定义 Android 输入和完整包边界，核心 `:sdk` AAR 指南不能代替鼎桥完整交付。

## 输入及结构

- Release 子包入口：`asr/tools/delivery/pack_dingqiao_customer_delivery.sh --stage-release <packages/release-sdk> <version>`。其待验收标记及发布登记规则见[版本跟踪](../ASR_SDK_RELEASE_TRACKING.md)。
- Diagnostics 构建使用 `asr/android/sdk-dingqiao/build.gradle.kts` 的 diagnostics 配置及 `asr/tools/delivery/dingqiao_build_provenance.sh` 的身份/资源校验。
- Demo 必须使用对应 SDK 构建并签名；Demo 源码只依赖包内公开 AAR，排除授权、签名私钥、构建缓存和内部评测上传功能。

完整外层至少包含以下五个目录及 README；Release Demo 可在 Release 子包内，但必须在清单说明入口：

```text
Amphion-Android-ASR-Complete-<version>/
  README.md
  release-sdk/       # Release 子包，含对应 Demo
  diagnostics-sdk/   # Diagnostics AAR
  diagnostics-demo/  # 已签名 Diagnostics APK
  demo-source/       # 独立工程和公开 AAR
  docs/             # 接入、升级、构建身份与逐文件校验
```

Android 尚无与 Harmony 对等的统一外层组包脚本；以上是固定组装清单，不能宣称已一键自动化。组装时保存各输入的构建提交和哈希，校验 ZIP CRC、成员清单和每个文件哈希。外层完整包与 Release 子包是不同身份，分别记录。

## 平台验证

从完整包安装签名 APK；从包内 Demo 源码独立构建并安装，确认只依赖公开 AAR。检查模型资源、native 库、授权配置及源码/二进制身份。SDK 用例遵循[统一验证矩阵](../../docs/engineering/ASR_VALIDATION.md)，不得把 APK 安装成功当作接口或角色精度通过。

归档和本地清理使用[统一归档入口](../PUBLISHED_ARTIFACT_ARCHIVE.md)，不维护 Android 独立归档流程。
