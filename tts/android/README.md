# Lits TTS Android SDK

当前入口用于构建 Dingqiao v3 离线 TTS AAR。SDK 与模型分开交付：AAR 包含代码和 native 库，模型与前端资源位于构建生成的 `external-resources/`。以 [源码编译说明](docs/BUILD_FROM_SOURCE.md) 为准，不要沿用旧 16 kHz HiFi-GAN 包的目录和文件清单。

以下命令从 AmphionRuntime 仓库根目录执行；Windows 请把 `./gradlew` 替换为 `gradlew.bat`。

```text
AmphionRuntime/tts/android/
```

## 当前版本

| 项 | 值 |
| --- | --- |
| SDK 构建版本 | `3.1`，见 [build.gradle.kts](build.gradle.kts) 的 `sdkVersion` |
| 模型 ID | `dingqiao_imf_step00170000_streaming_vocos24k` |
| 模型资源版本 | `0.1.0`（不是 SDK 版本） |
| 支持语种 | `zh-en`, `en-US` |
| 输出格式 | `pcm`, 24000 Hz, 16-bit, mono |
| Android minSdk | 24 |
| ABI | `arm64-v8a` |

## 文档导航

- **固定交付清单：[打包交付 README](docs/delivery/README.md)**（SDK 包、Demo 包的内容、命名和核对要求）

- Dingqiao v3 源码编译说明：[docs/BUILD_FROM_SOURCE.md](docs/BUILD_FROM_SOURCE.md)
- Dingqiao v3 批测说明：[docs/BATCH_TESTING.md](docs/BATCH_TESTING.md)
- 从源码构建 SDK：[docs/DELIVERY.md](docs/DELIVERY.md)
- 宿主 App 接入 AAR：[docs/INTEGRATION.md](docs/INTEGRATION.md)
- 公开接口说明：[docs/API.md](docs/API.md)
- 伪代码与调用顺序：[docs/PSEUDOCODE.md](docs/PSEUDOCODE.md)

## 源码构建快速开始

1. 克隆本仓库（已包含 TN 源码），并按仓库[资产同步说明](../../tools/assets/README.md)恢复构建依赖；本次 IMF 模型使用 3.1 交付包的 `external-resources/tts/dingqiao_imf_step00170000_streaming_vocos24k/0.1.0/`。
2. 放到下面这个固定目录：

```text
tts/tools/trial-export/dingqiao_imf_step00170000_streaming_vocos24k/0.1.0/
```

3. 让 Gradle 能找到本机 Android SDK：

- 在 `local.properties` 写 `sdk.dir=...`
- 或设置 `ANDROID_HOME` / `ANDROID_SDK_ROOT`

4. 准备 JDK、NDK 和 ICU 等 native 依赖（详见源码编译说明），执行：

```bash
cd tts/android
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease \
  -PLITS_TTS_MODEL_ID=dingqiao_imf_step00170000_streaming_vocos24k \
  -PLITS_TTS_MODEL_DIR=/absolute/path/to/0.1.0
```

5. 构建输出位于：

```text
sdk/build/outputs/aar/sdk-release.aar
```

注意：模型文件只需要放到 `tts/tools/trial-export/...`，不要手动放到 `sdk/src/main/assets/...`；OBS 模型包已包含校验过的前端 `.bin`，Gradle 会在 `preBuild` 阶段以只读方式同步资源。`tts/android/external-resources/` 是构建输出，不是第二份源资产，不得提交到 Git。只有显式执行 `syncLitsTnAssets` 时才会在 `build/generated/` 生成候选词典，不会改写源包。

完整步骤、输入文件清单、自检方式与常见报错见 [docs/BUILD_FROM_SOURCE.md](docs/BUILD_FROM_SOURCE.md)。

## 模型包说明

源码构建直接消费已经导出的 ONNX 模型包，不要求 checkpoint，也不要求重新导出。主要模型文件为：

- `manifest.json`
- `lits_hidden_encoder.onnx`
- `lits_stream_condition_chunk.onnx`
- `lits_stream_decoder_cache_init.onnx`
- `lits_stream_decoder_cache_step.onnx`
- `vocos_vocoder.onnx`

完整清单还包括前端词典与 `rules_v2`，见源码编译说明。Gradle 在 `preBuild` 阶段同步到：

```text
tts/android/external-resources/tts/dingqiao_imf_step00170000_streaming_vocos24k/0.1.0/
```

该目录是可重建输出。运行时把 `external-resources/tts/` 放在调用方 `workPath` 下的 `tts/` 目录，先激活有效 TTS license，再创建引擎；不要将 `workPath` 指向具体模型版本目录。

## 运行时说明

- `createEngine(params, callback)` 和 `listVoices(params, callback)` 是异步接口；Android 环境下 callback 回到主线程
- 同步版 `createEngine(params)` 会在当前线程完成模型加载，调用方应自行放到后台线程
- `SpeakListener` 的 `onStart/onData/onComplete/onStop/onError` 为 SDK 内部异步派发；更新 UI 时需要切回主线程

## SDK-only 交付打包

在已配置模型目录和授权公钥的构建环境中执行 `./gradlew stageSdkDelivery`，模型参数与上面的构建命令一致。任务调用 `tts/tools/android/pack_sdk_only.py`，输出 `build/delivery/lits-dingqiao-tts-android-sdk-vocos24k-3.1/` 及同名 ZIP。

客户包使用 [SDK_README.md](docs/SDK_README.md) 作为根 README，保留 API、INTEGRATION、PSEUDOCODE、当前版本 CHANGELOG 和 LICENSE / NOTICE。源码构建历史、内部验收报告不随包发放。CHECKSUMS.txt 在组包时生成，不再使用仓库内的旧校验表。


## 验证状态

2026-09-03 [股票代码逐位读法修复](reports/stock-code-20260903/README.md)已通过本机、原生前端及 Release AAR 公开 SDK 真机回归。完整 675 条前后对照仅目标句 token 改变，其余 674 条完全一致；目标句仍含另一处历史音调标注差异，严格匹配总数仍为 380/675，不能视为全量发音验收通过。

2026-09-03 [完整 675 条前端语料基线](reports/pronunciation-corpus-20260903/README.md)已采集：380 条音素序列完全一致、295 条有差异、0 条执行错误，**完整发音对照尚未通过**。其中混有旧 golden 与已确认契约冲突、变调及其他前端差异，不能直接当作 295 个已确认 SDK 缺陷。已补报告门禁，防止仅凭 instrumentation 的 `OK` 误放行；未修改运行代码或 golden。

2026-09-03 已补齐 [Release AAR 独立宿主最小接入门禁](reports/release-aar-host-20260903/README.md)：vivo V2505A / Android 16 上，正式授权、外置模型加载及公开 API 合成通过；21 个非空 PCM 回调连续有序，唯一 start/complete，shutdown 返回。宿主使用 Debug 签名，SDK 依赖为校验过的 Release AAR。运行方式见[批测说明](docs/BATCH_TESTING.md#当前-release-aar-最小接入门禁)。

主要批测入口 `AarStability1000DeviceTest` / `AarRtfAuditDeviceTest` 已完成[授权与外置资源迁移](reports/batch-external-resources-20260903/README.md)，不再清空调用方目录。真机完成旧版红灯→同条件绿灯、2 个共享引擎相邻用例、20 次纯合成 RTF 及缺参检查；25 个模型文件校验值保持一致。这是入口迁移回归，不是全量 100/424/1000 条、播放、后台冻结恢复或长稳压验收；其他历史 probe 仍未迁移。

审查后补齐[批测路径检查](reports/batch-path-review-20260903/README.md)：6 种不存在、类型错误或不可读路径在执行用例前被明确拒绝，正常冷启动复验通过；SDK AAR 未变。

2026-09-03 前端修复已完成本轮 Android 真机门禁：7 项负温度、4 项日期、URL 分段及公共 SDK PCM 合成通过；审查后新增的 PCM 连续序号断言也已[真机复验](reports/frontend-review-20260903/README.md)。默认 JVM 套件 104 项中 101 项通过、3 项原有跳过；Release AAR 和测试 APK 构建通过。根因与完整回归见[真机回归记录](reports/frontend-device-20260903/README.md)。这不是完整发音语料、后台冻结场景或长稳压的发布验收；[此前本机记录](reports/frontend-contracts-20260903/README.md)和[负温度记录](reports/negative-temperature-20260903/README.md)仅作为历史证据保留。
