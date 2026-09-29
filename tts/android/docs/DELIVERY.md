# Android TTS 交付说明

当前 SDK AAR 与模型资源分开交付。AAR 包含代码、native TN 与 ONNX Runtime JNI；模型和前端资源不在 AAR 内。当前输出为 24000 Hz、16-bit、单声道 PCM，调用方仍应读取 `onStart` 的格式字段。

## 交付清单

| 内容 | 要求 |
| --- | --- |
| Release AAR | 由本次冻结源码构建；名称和版本在交付清单中明确 |
| `external-resources/tts/<model>/<version>/` | 与 AAR 同批构建的完整模型、词典、规则和 manifest |
| 授权 | 按本批声明受控提供，不嵌入公开源码或 AAR |
| 接入文档 | 本目录 `INTEGRATION.md`、`API.md`、`PSEUDOCODE.md`、`LICENSE.md` 与第三方声明 |
| Demo 与源码 | 若本批包含，明确签名、资源放置、构建依赖和运行入口；不得只给缺少依赖的源码快照 |

宿主需将 `external-resources/tts/` 复制到 `<workPath>/tts/`，设置工作目录、完成授权后再创建引擎。具体顺序见 [INTEGRATION.md](INTEGRATION.md)。

## 仓库构建入口

在 AmphionRuntime 仓库使用 `tts/android/docs/BUILD_FROM_SOURCE.md`；它包含 TN/ICU 依赖、受控模型输入和 AAR/外置资源输出。该文档是仓库开发入口，不是接入 AAR 必须依赖的外部文件。

`tts/tools/android/pack_lits_tts_android_delivery.sh` 与 `verify_lits_tts_android_delivery.sh` 是旧 Transsion 包布局的工具，仍假设模型内置于 AAR，且源码快照路径不同，不能用于当前 Dingqiao 外置资源交付。当前 Gradle 提供 `stageSdkDelivery`，可生成 AAR、外置资源和接入文档的暂存目录，但不含完整 Demo/源码、最终验证或发布登记。按本批范围补齐后逐项验收，不将该任务称为完整交付自动化。

仓库构建环境准备完成后，从 `tts/android` 执行：

```bash
./gradlew --no-daemon stageSdkDelivery
```

默认输出 `tts/android/build/delivery/lits-dingqiao-tts-android-sdk-vocos24k-3.0/`，属于可重建构建输出。最终交付包转入统一暂存目录，再生成本次哈希和验收记录；历史 `CHECKSUMS.txt` 不随新产物复制。

## 验收与归档

记录源码提交、SDK/模型版本、全部交付文件的 SHA-256。检查 AAR 内代码与 native 库、外置资源完整性，并从最终包验证宿主接入、授权、合成回调及播放；包含源码时验证其独立构建。

构建成功不能替代真机验证。历史 16 kHz HiFi-GAN 或旧目录结构的测试结果不适用于当前产物。归档与清理按仓库 `delivery/PUBLISHED_ARTIFACT_ARCHIVE.md` 执行，不在仓库父目录长期保存 ZIP。
