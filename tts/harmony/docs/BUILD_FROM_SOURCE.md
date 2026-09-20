# HarmonyOS SDK 源码编译说明

本文说明如何从 AmphionRuntime 当前代码编译 Dingqiao v3 TTS HarmonyOS SDK HAR。目标产物是：

```text
tts/harmony/sdk/build/default/outputs/default/sdk.har
```

`sample/` 只用于本地验证 HAR 接入，不是最终 SDK 交付物。需要验证宿主 HAP 时，可额外构建：

```text
tts/harmony/sample/build/default/outputs/default/sample-default-unsigned.hap
```

## 1. 获取源码

TN（文本归一化）源码、规则和测试已直接纳入本仓库，普通克隆即可获取：

```bash
git clone <AmphionRuntime-url>
cd AmphionRuntime
```

协作者无需原 TN 私有仓库权限；来源版本见
[TN_SOURCE.md](../../training/TN_SOURCE.md)。源码目录为：

```text
tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS/
```

HarmonyOS TN 可执行文件会从这个目录编译；HAR 的 native 库 `liblitsttsnative.so` 也会使用仓库内的 TN/ICU 代码和静态库。

## 2. 准备本机环境

按 [命令行工具链说明](../../../asr/tools/HARMONY_TOOLCHAIN.md) 安装 DevEco CLI `1.3.0-stable`、独立 Command Line Tools 26.0.0+、系统 Node.js 22+ 和 JDK 17。保留工程声明的 API 版本。

在仓库根目录设置环境：

```bash
export DEVECO_CLI_CLT_PATH="$HOME/.local/share/harmony/command-line-tools"
export JAVA_HOME=/path/to/jdk-17
source asr/tools/harmony_env.sh
export OHOS_NATIVE_SDK="$OHOS_SDK_NATIVE_DIR"
```

实际路径按本机 CLT 安装位置调整。构建脚本不会临时下载工具链。

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

脚本会使用当前仓库里的 TN 源码目录 和 HarmonyOS SDK 内置的 OHOS 编译器。默认输出：

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
../../asr/tools/deveco_cli.sh build --product default --modules sdk@default --build-mode debug
```

成功后产物在：

```text
sdk/build/default/outputs/default/sdk.har
```

## 6. 构建 sample HAP

如需验证 HAR 接入，再执行：

```bash
../../asr/tools/deveco_cli.sh build --product default --modules sample@default --build-mode debug
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

- TN 源码目录为空：确认已检出包含 TN 源码迁入的版本；该目录由本仓库直接跟踪。
- `ohpm` 或 `hvigorw` 找不到：确认 `DEVECO_CLI_CLT_PATH` 并加载 `asr/tools/harmony_env.sh`。
- 找不到 OHOS 编译器：设置 `OHOS_NATIVE_SDK` 到 `openharmony/native`。
- 找不到 TN 文件：先运行 `tts/tools/tn/build_dingqiao_harmony_tn.sh`，或确认模型包里有 `tn-bin/arm64-v8a/zh_tts` 和 `en_tts`。
- 不要提交 `.signing-local/`、`build-ohos-tn/`、`build/`、个人签名文件、license 包或本机 DevEco 缓存。
