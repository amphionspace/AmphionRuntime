# TTS 工具入口

当前 Dingqiao TTS 的构建输入、模型清单与平台命令统一见 [Android 构建](../android/docs/BUILD_FROM_SOURCE.md)和 [Harmony 构建](../harmony/docs/BUILD_FROM_SOURCE.md)。不要沿用早期 Transsion v2 或 16 kHz HiFi-GAN 的文件清单。

| 目录/工具 | 用途 |
| --- | --- |
| `android/` | 前端资源生成、批测工具；旧 pack/verify 脚本只适配历史内置模型包 |
| `onnx-export/` | 模型导出、量化与研发验证 |
| `tn/` | Android/Harmony TN 构建、ICU 裁剪和发音回归 |
| `verify_transsion_vocos24k_package.py` | 历史 Transsion 模型格式校验，不能作为当前资源清单 |
| `verify_lits_delivery_16k_package.py` | 历史 16 kHz 包排查 |
| [统一授权工具](../../tools/license/README.md) | 签发、验证和登记；本目录 license 入口仅保留兼容 |

当前受控模型位于 `tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/`。Android 构建生成外置资源，Harmony 构建复制进 HAR，具体边界见各平台构建说明。

普通构建不改写受控源资产。发音修订需在独立候选副本中修改词典/规则并重建对应 `.bin`，经前端与实际 SDK 发音回归后形成新的版本化资产；不要直接改 generated/assets 目录或只改文本词典而沿用旧二进制词典。

Android 的 `stageSdkDelivery` 可暂存 AAR、外置资源和接入文档，不含完整 Demo/源码、最终验收及归档。使用范围见 [Android 交付说明](../android/docs/DELIVERY.md)。
