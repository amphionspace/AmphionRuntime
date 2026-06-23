# HarmonyOS / OpenHarmony 工具链

纯血鸿蒙 SDK 需要使用 DevEco Studio 或 HarmonyOS Command Line Tools，不能复用 Android NDK。

## 需要的工具

- DevEco Studio 5.x 或 HarmonyOS Command Line Tools 5.x
- OHOS SDK Native 工具链，目录中应包含：
  - `build/cmake/ohos.toolchain.cmake`
  - `llvm/bin/aarch64-unknown-linux-ohos-clang`
  - `build-tools/cmake/bin/cmake`
- `bash`、`curl`、`unzip`

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
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
```

产物：

```text
third_party/sherpa-onnx/build-ohos-arm64-v8a/install/lib/libsherpa-onnx-c-api.so
third_party/sherpa-onnx/build-ohos-arm64-v8a/install/lib/libonnxruntime.so
asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/
third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/arm64-v8a/
```

## 资源同步

```bash
bash asr/tools/08_pack_harmony_assets.sh
```

该脚本把 Android AAR 的 `amphion-models` 资源布局复制到 Harmony `rawfile` 下。模型二进制可复用，但路径和打包格式不同。
