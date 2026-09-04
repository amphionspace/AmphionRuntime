# HarmonyOS SDK 源码编译说明

本文说明如何从 AmphionRuntime 当前代码编译 Dingqiao v3 TTS HarmonyOS SDK HAR。目标产物是：

```text
tts/harmony/sdk/build/default/outputs/default/sdk.har
```

`sample/` 只用于本地验证 HAR 接入，不是最终 SDK 交付物。需要验证宿主 HAP 时，可额外构建：

```text
tts/harmony/sample/build/default/outputs/default/sample-default-unsigned.hap
```

## 1. 获取源码和 submodule

首次克隆建议直接带上 submodule：

```bash
git clone --recurse-submodules <AmphionRuntime-url>
cd AmphionRuntime
```

如果已经克隆过仓库，进入仓库根目录后执行：

```bash
git submodule update --init --recursive
```

必须存在以下 TN submodule：

```text
tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS/
```

HarmonyOS TN 可执行文件会从这个 submodule 编译；HAR 的 native 库 `liblitsttsnative.so` 也会使用仓库内的 TN/ICU 代码和静态库。

## 2. 准备本机环境

需要本机已有：

- DevEco Studio 6.x 或配套命令行工具
- HarmonyOS SDK
- OpenHarmony Native SDK
- Node.js / ohpm
- JDK 17，通常可使用 DevEco 自带 JBR

常用环境变量示例：

```bash
export DEVECO_SDK_HOME=/Applications/DevEco-Studio.app/Contents/sdk
export NODE_HOME=/Applications/DevEco-Studio.app/Contents/tools/node
export JAVA_HOME=/Applications/DevEco-Studio.app/Contents/jbr/Contents/Home
export OHOS_NATIVE_SDK=/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native
```

实际路径按本机 DevEco 安装位置调整。不要在构建脚本里临时下载 JDK、hvigor、ohpm 或 SDK。

## 3. 准备模型包

构建消费的是已经导出的模型包，不需要 checkpoint，也不需要重新导出 ONNX。把模型包放在仓库根目录下：

```text
tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
```

该目录是从 OBS 恢复的版本化只读输入。构建只会将其复制到生成目录，不会在原目录重建或覆盖词典。

至少应包含：

- `manifest.json`
- `lits_hidden_encoder.onnx`
- `lits_stream_condition_chunk.onnx`
- `lits_stream_decoder_step.onnx`
- `vocos_vocoder.onnx`
- `frontend_golden.json`
- `frontend_rules.json`
- `chinese_lexicon.txt`
- `cmudict.txt`
- `supplement_lexicon.json`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`
- `rules_v2/zh.full.json`
- `rules_v2/en.full.json`
- `rules_v2/zh_pinyin.json`

当 manifest 声明 `stream_final_zero_pad_with_chunk_condition=true` 时，不需要
`lits_stream_condition_final.onnx`；旧 manifest 未声明该字段时仍必须提供该文件。

HarmonyOS 构建会把模型包同步到：

```text
tts/harmony/sdk/src/main/resources/rawfile/amphion-dingqiao/
```

运行时如果宿主没有显式传入外部模型目录，SDK 会使用 HAR 内置资源。

## 4. 构建 HarmonyOS TN 可执行文件

如果模型包里没有可用的 `tn-bin/arm64-v8a/zh_tts`、`tn-bin/arm64-v8a/en_tts`，或需要从源码重建 HarmonyOS TN 文件，执行：

```bash
OHOS_NATIVE_SDK=/path/to/openharmony/native \
tts/tools/tn/build_dingqiao_harmony_tn.sh
```

脚本会使用当前仓库里的 TN submodule 和 HarmonyOS SDK 内置的 OHOS 编译器。默认输出：

```text
tts/harmony/build-ohos-tn/zh_tts
tts/harmony/build-ohos-tn/en_tts
```

`tts/harmony/hvigorfile.ts` 会优先使用 `build-ohos-tn/` 里的生成文件；如果未生成，则要求模型包里已有 `tn-bin/arm64-v8a/`。

## 5. 编译 HAR

进入 HarmonyOS 工程目录：

```bash
cd tts/harmony
```

安装 ohpm 依赖：

```bash
ohpm install --all
```

编译 SDK HAR：

```bash
/path/to/DevEco-Studio/tools/hvigor/bin/hvigorw \
  --mode module -p product=default -p module=sdk@default assembleHar --no-daemon
```

成功后产物在：

```text
sdk/build/default/outputs/default/sdk.har
```

## 6. 构建 sample HAP

如需验证 HAR 接入，再执行：

```bash
/path/to/DevEco-Studio/tools/hvigor/bin/hvigorw \
  --mode module -p product=default -p module=sample@default assembleHap --no-daemon
```

成功后产物在：

```text
sample/build/default/outputs/default/sample-default-unsigned.hap
```

`sample-default-unsigned.hap` 不能直接作为正式安装包交付。真机安装需要使用目标设备信任的 HarmonyOS 调试或发布签名。

## 7. 期望产物

HAR 应包含：

- `package/libs/arm64-v8a/liblitsttsnative.so`
- ONNX Runtime 相关 native 库
- `resources/rawfile/amphion-dingqiao/` 下的模型、前端资源和 TN 文件

HAR 不应包含：

- 个人签名材料
- `.p12` / `.cer` / `.csr` / `.p7b`
- 本地 DevEco 缓存
- 未经确认的 license 文件

## 8. 常见问题

- `submodule` 目录为空：执行 `git submodule update --init --recursive`。
- `ohpm` 或 `hvigorw` 找不到：确认 DevEco Studio 命令行工具路径，并设置 `NODE_HOME` / `DEVECO_SDK_HOME`。
- 找不到 OHOS 编译器：设置 `OHOS_NATIVE_SDK` 到 `openharmony/native`。
- 找不到 TN 文件：先运行 `tts/tools/tn/build_dingqiao_harmony_tn.sh`，或确认模型包里有 `tn-bin/arm64-v8a/zh_tts` 和 `en_tts`。
- 不要提交 `.signing-local/`、`build-ohos-tn/`、`build/`、个人签名文件、license 包或本机 DevEco 缓存。
