# Android 鼎桥交付脚本

执行顺序见[统一交付流程](../../../delivery/ASR_DELIVERY_WORKFLOW.md)，完整包边界见[Android 默认交付](../../../delivery/android-dingqiao/DEFAULT_DELIVERY.md)。以下脚本生成 Release 子包或内部变体，不能单独代表五目录完整交付。

| 脚本 | 范围 |
| --- | --- |
| `pack_dingqiao_customer_delivery.sh` | Release 子包，含 fat AAR、签名 Demo 和客户文档 |
| `pack_dingqiao_customer_delivery.sh --sdk-only` | 仅在明确要求时使用的中英 SDK 子包 |
| `pack_dingqiao_delivery_scheme_a_aligned.sh` | 内部 scheme A aligned |
| `pack_dingqiao_delivery.sh` | 内部 scheme A（含 LICENSING） |
| `pack_dingqiao_delivery_scheme_b.sh` | 内部 scheme B 三 AAR |
| `merge_dingqiao_fat_aar.sh` | 仅合并 fat AAR |
| `verify_dingqiao_delivery.sh` | 子包身份、native 库、ZIP 编码及 NOTICE 检查 |
| `dingqiao_zip_utf8.py` | Windows 中文文件名兼容打包 |
| `dingqiao_build_provenance.sh` | 共用库，不直接执行 |

在仓库根目录按统一流程设置 `DELIVERY_STAGE`、冻结版本和源码后，新版本使用尚不存在的暂存子目录：

```bash
bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh   --stage-release "${DELIVERY_STAGE:?请先设置本次暂存目录}/packages/release-sdk"
```

版本参数省略时读取 `asr/android/gradle.properties`。`--stage-release` 允许先构建新版本再对最终包验收与登记，不授予发布资格；开发预览使用 `--preview` 并保留全部预览标记。
Diagnostics、Demo 源码及外层完整包按默认交付清单补齐。更新日志、证据和发布登记见[版本跟踪](../../../delivery/ASR_SDK_RELEASE_TRACKING.md)。
