# Lits TTS HarmonyOS SDK

本文面向第一次接手这份 HarmonyOS 源码工程的协作者，目标是只靠文档就能知道三件事：

1. SDK 源码入口在哪里
2. 模型文件应该放在哪里
3. 怎样从 0 构建出 `sdk.har`，以及怎样用宿主 HAP 做本地验证

最终 SDK 交付物是：

```text
sdk/build/default/outputs/default/sdk.har
```

下面统一用 `LitsTtsSdk 根目录` 指代你把这份源码放到本机后的那个目录，例如：

```text
D:\work\LitsTtsSdk
```

## 当前版本

| 项 | 值 |
| --- | --- |
| SDK 版本 | `0.1.0` |
| 模型 ID | `transsion_lits_en_zh_vocos24k_streaming_proto_external_loop` |
| 模型版本 | `0.1.0` |
| 支持语种 | `zh-en`, `en-US` |
| 输出格式 | `pcm`, 24000 Hz, 16-bit, mono |
| HarmonyOS SDK | `6.0.2.130` |
| API | `22` |
| ABI | `arm64-v8a` |

## 目录说明

- `sdk/`
  - 真正的 HarmonyOS HAR 模块
  - 对外 SDK 代码在这里
  - 最终产物是 `sdk.har`

- `sample/`
  - 仅用于本地验证 SDK 的 sample HAP
  - 它不是最终 SDK 交付物
  - 作用是验证模型路径、真实 ONNX 推理、PCM 输出和播放链路

- `docs/`
  - 构建、API、交付说明

- `AppScope/`、`hvigor/`、`build-profile.json5`、`hvigorfile.ts`、`oh-package.json5`
  - HarmonyOS 工程元数据和构建配置

## 文档导航

- 构建与验证：[docs/BUILD.md](docs/BUILD.md)
- API 说明：[docs/API.md](docs/API.md)
- Git 上传与模型交接：[docs/DELIVERY.md](docs/DELIVERY.md)

## 从 0 开始的最短路径

如果你只关心“怎么最快构建出 SDK”，按下面做：

1. 把完整模型包放到：

```text
LitsTtsSdk\tools\trial-export\transsion_lits_en_zh_vocos24k_streaming_proto_external_loop\0.1.0\
```

2. 进入：

```text
LitsTtsSdk\HarmonyOS\AmphionRuntime
```

3. 先执行宿主侧预检：

```powershell
node ..\..\tools\verify_lits_harmony_package.mjs --model-dir ..\..\tools\trial-export\transsion_lits_en_zh_vocos24k_streaming_proto_external_loop\0.1.0 --out-dir .\verification\out --text "Hello world." --mode en-US
```

4. 设置构建环境：

```powershell
$env:DEVECO_SDK_HOME="C:\Program Files\Huawei\DevEco Studio\sdk"
$env:JAVA_HOME="C:\Program Files\Huawei\DevEco Studio\jbr"
```

5. 构建 HAR：

```powershell
& "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=sdk@default assembleHar --analyze=normal --parallel --incremental --no-daemon
```

成功后产物在：

```text
sdk/build/default/outputs/default/sdk.har
```

## 模型文件放哪里

源码仓库不存真实模型文件。构建前，你需要把完整模型包放到固定目录：

```text
LitsTtsSdk\tools\trial-export\transsion_lits_en_zh_vocos24k_streaming_proto_external_loop\0.1.0\
```

最少需要以下文件：

- `manifest.json`
- `lits_hidden_encoder.onnx`
- `lits_stream_condition_chunk.onnx`
- `lits_stream_condition_final.onnx`
- `lits_stream_decoder_step.onnx`
- `vocos_vocoder.onnx`
- `frontend_golden.json`
- `frontend_rules.json`
- `chinese_lexicon.txt`
- `chinese_lexicon.bin`
- `cmudict.txt`
- `cmudict.bin`
- `supplement_lexicon.json`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`
- `tn-bin/arm64-v8a/zh_tts`
- `tn-bin/arm64-v8a/en_tts`
- `rules/zh.json`
- `rules/en.json`
- `rules/zh_pinyin.json`
- `rules_v2/zh.full.json`
- `rules_v2/en.full.json`

构建时，HarmonyOS SDK 会把这份模型包同步到 `sdk/src/main/resources/rawfile/...` 并打进 HAR。运行时如果宿主没有显式传入模型目录，SDK 会先把 HAR 内置模型自动解包到可写目录；如需覆盖默认行为，仍可通过以下任一方式指定外部模型目录：

- `CreateEngineParams.extraParams.modelPackageDir`
- `TextToSpeechSdk.setWorkPath(...)`

## 当前实现状态

当前 HarmonyOS SDK 已经完成：

- 真实 OHOS native ONNX Runtime 接入
- hidden encoder + streaming decoder + vocos vocoder 真实 ONNX 推理
- 24 kHz PCM 输出
- HarmonyOS `AudioRenderer` 播放
- 一个可构建的宿主 HAP 验证工程

当前已知限制：

- ONNX 推理当前是同步调用；`stop()` 可以停止排队任务和播放，但不能中断已经开始的单次 native 推理
- `sample/` 只是验证 HAP，不是最终 SDK 交付物
- 如果你在消费者 HarmonyOS 真机上安装 `sample`，需要设备信任的调试签名；仓库不会提交任何个人签名材料

更具体的构建命令、签名说明和已验证结果见 [docs/BUILD.md](docs/BUILD.md)。
