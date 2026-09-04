# HarmonyOS / OpenHarmony 工具链

纯血鸿蒙 SDK 需要使用 DevEco Studio 或 HarmonyOS Command Line Tools，不能复用 Android NDK。

## 需要的工具

- DevEco Studio 5.x 或 HarmonyOS Command Line Tools 5.x
- OHOS SDK Native 工具链，目录中应包含：
  - `build/cmake/ohos.toolchain.cmake`
  - `llvm/bin/aarch64-unknown-linux-ohos-clang`
  - `build-tools/cmake/bin/cmake`
- `bash`、`curl`、`unzip`、Meson 1.0+、Ninja

## 环境变量

优先设置：

```bash
export OHOS_SDK_NATIVE_DIR=/path/to/command-line-tools/sdk/default/openharmony/native
```

脚本也会尝试从以下路径自动查找：

- `$DEVECO_SDK_HOME/default/openharmony/native`
- `$HOME/Library/Huawei/Sdk/default/openharmony/native`
- `$HOME/Library/OpenHarmony/Sdk/default/openharmony/native`

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

- 中英：`asr/tools/demo-model/zhen`
- 粤英：`asr/tools/demo-model/yueen`
- 标点：`asr/tools/punct-model/...-int8`
- ITN：`asr/tools/weitn-fsts`
- VAD：`asr/tools/vad-model/silero_vad.onnx`

中英模型接受 `decoder.int8.onnx`，并兼容旧的 `decoder.onnx`。构建时会并行把中英
encoder / decoder / joiner 和标点图转换成 ORT FlatBuffer：

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
