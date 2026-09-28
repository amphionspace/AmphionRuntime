# Harmony ASR Native 接入

`asr/harmony/sdk/src/main/cpp/napi_init.cpp` 是 `libamphion_asr.so` 的 NAPI 注册入口，包含：

- `probe` / `nativeVersion`：加载与版本探针。
- 目标说话人增强、角色区间分割和离线角色分离推理绑定。
- AGC 输入电平处理和 LAC 人名处理绑定。

ASR/VAD/标点等通用能力继续通过 `sherpa_onnx` HAR 接入。上述注册项说明代码边界，不能代替各能力的公共 SDK 和真机验收结论。

构建、库同步和模型资源准备使用仓库根目录的 `asr/tools/04_build_harmony_so.sh`、`05_package_har_libs.sh`、`08_pack_harmony_assets.sh`。AGC 库构建见[模块 README](../README.md)。

使用独立 CLT 和 DevEco CLI，见[工具链说明](../../tools/HARMONY_TOOLCHAIN.md)。端到端测试载体及交付入口见[鼎桥交付工程](../../../delivery/harmony-dingqiao/README.md)。
