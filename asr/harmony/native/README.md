# Native Probe

`asr/harmony/sdk/src/main/cpp/napi_init.cpp` 暴露了首个 Amphion NAPI 探针：

```ts
import { probe, nativeVersion } from 'libamphion_asr.so';
```

当前 NAPI 入口用于验证 HAR 能加载 `libamphion_asr.so`，并在链接阶段依赖：

- `libsherpa-onnx-c-api.so`
- `libonnxruntime.so`

完整 wav 解码探针由 `amphion_asr` ArkTS 层通过 `sherpa_onnx` HAR 完成：把模型同步到 rawfile 后，HAP demo 可以直接实时识别。后续如需绕过 `sherpa_onnx` HAR，可在这里扩展自研 NAPI 封装。

## 验证步骤

1. `bash asr/tools/04_build_harmony_so.sh`
2. `bash asr/tools/05_package_har_libs.sh`
3. `bash asr/tools/08_pack_harmony_assets.sh`
4. 用 DevEco 打开 `asr/harmony` 构建 `amphion_asr` 验证 native 加载；端到端 demo 见 `delivery/harmony-dingqiao/`（`samples/dingqiao-demo`）。
