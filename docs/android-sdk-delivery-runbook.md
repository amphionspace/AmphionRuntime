# Android 交付入口

ASR、TTS 和授权按实际交付范围选择，不默认三件套，也不共用同一套验收脚本。

| 任务 | 当前入口 |
| --- | --- |
| 双端 ASR 构建、验收、发布与归档 | [统一流程](../delivery/ASR_DELIVERY_WORKFLOW.md) |
| Android ASR 完整包结构 | [默认交付](../delivery/android-dingqiao/DEFAULT_DELIVERY.md) |
| ASR 调用方变化与邮件 | [变化核对清单](../delivery/CALLER_CHANGE_CHECKLIST.md)、[邮件模板](../delivery/harmony-dingqiao/docs/customer/DELIVERY_EMAIL_TEMPLATE.md) |
| Android TTS 源码构建 | [BUILD_FROM_SOURCE](../tts/android/docs/BUILD_FROM_SOURCE.md) |
| Android TTS 交付与接入 | [DELIVERY](../tts/android/docs/DELIVERY.md)、[INTEGRATION](../tts/android/docs/INTEGRATION.md) |
| 授权申请、签发及登记 | [统一授权工具](../tools/license/README.md) |
| 最终包对象存储归档 | [归档规则](../delivery/PUBLISHED_ARTIFACT_ARCHIVE.md) |

交付结论绑定最终 ZIP 的 SHA-256、构建提交和实际验证报告。旧版本命令与测试结果不能作为当前产物通过的依据。
ASR 子包验证器仅支持其声明的结构；TTS 的外置资源和源码依赖需按 TTS 文档单独核对。

不再在 `delivery/current`、`delivery/archive` 等本地目录长期保留交付包。暂存路径、远端归档和清理条件只在归档规则维护。
