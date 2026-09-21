# HarmonyOS / OpenHarmony 工具链

本仓库使用 **DevEco CLI + 独立 Command Line Tools（CLT）**，构建和设备测试不再依赖 DevEco Studio 的安装目录。

## 安装

- 系统 Node.js 22+，用于运行 DevEco CLI。
- `@deveco/deveco-cli@1.3.0-stable`（本次迁移固定版本）。
- 官方 [Command Line Tools](https://developer.huawei.com/consumer/cn/download/command-line-tools-for-hmos) 26.0.0+，按本机系统和 CPU 架构下载、解压。
- 独立 JDK 17；CLT 不提供 Studio 的 JBR。
- native 构建还需要 `bash`、`curl`、`unzip`、Meson 1.0+、Ninja，不能使用 Android NDK 代替 OHOS 编译器。

```bash
npm install -g @deveco/deveco-cli@1.3.0-stable
```

需要账号能力时，在自己的终端运行下面的命令。登录页过期后重新运行 `auth login` 即可打开新的页面，无需等待他人重开：

```bash
devecocli auth login
devecocli auth status
```

CLT 下载使用开发者网站的网页登录。macOS 可随时重开固定下载入口：

```bash
open 'https://developer.huawei.com/consumer/cn/download/command-line-tools-for-hmos'
```

官方下载可能需要登录华为开发者账号。CLT 根目录应包含 `version.txt`、`tool/node/`、`ohpm/`、`hvigor/` 和 `sdk/`。推荐解压到 `~/.local/share/harmony/command-line-tools/`；其他位置通过下面的变量指定。CLI 的要求与工具路径依据 [官方包说明](https://www.npmjs.com/package/@deveco/deveco-cli)。

## 环境变量

在仓库根目录执行（路径换成本机实际位置）：

```bash
export DEVECO_CLI_CLT_PATH="$HOME/.local/share/harmony/command-line-tools"
export JAVA_HOME=/path/to/jdk-17
source asr/tools/harmony_env.sh
bash asr/tools/deveco_cli.sh --version
bash asr/tools/deveco_cli.sh device list
```

macOS 使用 Homebrew 安装独立 JDK 的示例：

```bash
brew install openjdk@17
export JAVA_HOME="$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home"
```

`harmony_env.sh` 为构建、签名和设备脚本统一设置 CLT 路径，并清除优先级更高的 `DEVECO_CLI_STUDIO_PATH`，防止 CLI 被旧配置切回 Studio。仓库入口关闭 CLI 遥测。`JAVA_HOME` 使用独立 JDK；本地证书、授权及签名口令仍按原流程从 `.secure/` 读取，不提交到仓库。

可显式覆盖 `DEVECO_SDK_HOME`、`OHOS_SDK_NATIVE_DIR`、`HDC`、`LLVM_NM` 和 `HAP_SIGN_TOOL_JAR`。默认 SDK 为 `$DEVECO_CLI_CLT_PATH/sdk`，native 为其 `default/openharmony/native`。Python 设备脚本也直接读取 `DEVECO_CLI_CLT_PATH`，无需依赖当前终端是否已经 source。

## 日常编译

先完成下文的 native 与模型准备，再在对应 Harmony 工程目录调用 CLI。CLI 会执行依赖安装和 Hvigor 构建：

```bash
cd delivery/harmony-dingqiao
../../asr/tools/deveco_cli.sh build --product default --modules amphion_asr_demo@default --build-mode debug
../../asr/tools/deveco_cli.sh build --product default --modules sherpa_onnx@default amphion_asr@default amphion_police@default amphion_dingqiao@default --build-mode release
```

TTS 工程使用 `cd tts/harmony`，再执行 `../../asr/tools/deveco_cli.sh build --modules sdk@default --build-mode release`；宿主模块是 `sample@default`。

正式 USB 验收继续使用 `delivery/harmony-dingqiao/delivery/build_install_smoke.sh`。该脚本及打包门禁直接调用 **CLT 中的 Hvigor、ohpm、hdc 和签名工具**，保留原有 `--no-daemon`、隔离签名、构建身份核对及 SDK 生命周期断言。CLI 的 `run` 冒烟检查不能代替 SDK 验收。

迁移工具链不修改工程的 `compatibleSdkVersion`、`targetSdkVersion`、模型、签名或交付范围。更换 SDK 后新生成的 HAP/HAR 必须按现有规则重新绑定构建身份和相关验收证据，旧二进制的通过结果不能自动用于新产物。

### 已验证的工具组合（2026-09-20）

macOS ARM64：DevEco CLI `1.3.0-stable`、CLT `26.0.0.821`、Hvigor `6.26.4`、ohpm `26.0.0.630`、CLT Node.js `24.14.1`、独立 JDK `17.0.20.1`。

在隔离工程内执行 `devecocli build --product default --modules amphion_asr_demo@default --build-mode debug`，成功生成中英 signed HAP，并通过现有签名、证书链、授权、模型身份与 native ABI 预检。`devecocli device list` 能识别连接的真机。该记录只证明工具链迁移和构建预检，不代替 SDK 生命周期、识别精度或发布真机矩阵。

## 构建 native

```bash
bash asr/tools/03_build_agc_native.sh ohos-arm64-v8a
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
```

产物：

```text
third_party/.derived/sherpa-onnx/build-ohos-arm64-v8a/install/lib/libsherpa-onnx-c-api.so
third_party/.derived/sherpa-onnx/build-ohos-arm64-v8a/install/lib/libonnxruntime.so
asr/native/audio-processing/build-ohos-arm64-v8a/libamphion_audio_processing.so
asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/
third_party/.derived/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/arm64-v8a/
```

## 模型预优化与资源打包

```bash
bash asr/tools/08_pack_harmony_assets.sh
```

该脚本不依赖 Android assets，会直接从以下默认目录组装五类模型：

- 中英：`asr/tools/demo-model/amphion-zh-en-police-179m-1.4.0-chunk32-lc256-transducer-fp32`（[恢复说明](demo-model/README.md)）
- 粤英：`asr/tools/demo-model/yueen`
- 标点：`asr/tools/punct-model/...-int8`
- ITN：`asr/tools/weitn-fsts-v2`（保留“啊、呃”）
- VAD：`asr/tools/vad-model/silero_vad.onnx`

当前中英模型使用 FP32 `encoder.onnx`、`decoder.onnx` 和 `joiner.onnx`。构建时会并行把
三张图和标点图转换成 ORT FlatBuffer；运行期沿用历史文件名，名称中的 `int8` 不代表当前模型精度：

```text
zh-en/v1/{encoder.int8.ort,decoder.ort,joiner.int8.ort}
punct-zhen/v1/model.int8.ort
```

转换器固定使用 `onnxruntime==1.16.3`、`onnx==1.15.0`、`numpy==1.26.4`、CPU EP、ARM target 和 Fixed
全图优化；ARM target 会禁用 `NchwcTransformer`。脚本会覆盖外部同名环境变量，
防止转换级别被意外降级。首次执行自动创建
`.venv-harmony-ort-1.16.3`，转换结果按源文件 SHA-256 缓存在
`.cache/harmony-ort-1.16.3`。后续模型未变化时直接命中缓存。

粤英、ITN 与 VAD 保持原格式。脚本先在临时目录构建并校验 manifest v2（包含源/输出
SHA-256、格式和转换器信息），通过后才原子替换 Harmony `rawfile` 目录。

自定义模型或复用已有转换环境：

```bash
ZH_EN_DIR=/path/to/zhen \
HARMONY_ORT_PYTHON=/path/to/venv/bin/python \
bash asr/tools/08_pack_harmony_assets.sh
```
