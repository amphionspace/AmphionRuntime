# Lits TTS HarmonyOS SDK

当前工程位于 `tts/harmony/`。SDK 版本以 [sdk/oh-package.json5](sdk/oh-package.json5) 为准（当前 `3.0.0`）；模型资源版本 `0.1.0` 与 SDK 版本独立。
当前模型支持 `zh-en` / `en-US`，输出为 24000 Hz、16-bit、单声道 PCM。

| 目录 | 用途 |
| --- | --- |
| `sdk/` | HAR 源码，产物为 `sdk/build/default/outputs/default/sdk.har` |
| `sample/` | 验证 HAR 接入、合成和播放的 HAP 载体 |
| `docs/` | 构建、API 与资产交接说明 |

首次构建直接按[源码编译说明](docs/BUILD_FROM_SOURCE.md)准备独立 CLT、JDK、模型和 TN 依赖，再使用 DevEco CLI。模型输入位于仓库 `tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/`，构建将其复制进 HAR；不再使用早期 `LitsTtsSdk/HarmonyOS/AmphionRuntime` 布局。

- [构建与验证范围](docs/BUILD.md)
- [公开 API](docs/API.md)
- [源码与模型交接](docs/DELIVERY.md)

`sample` 构建成功不等于真机验收通过。安装需使用目标设备信任的签名，结论必须记录实际提交、产物和设备。单次 native 推理不可被 `stop()` 中断；停止排队及播放的行为见 API。
