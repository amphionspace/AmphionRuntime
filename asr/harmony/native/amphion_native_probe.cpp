// 预留的 native wav 探针入口。当前首版通过 HAR NAPI 与 HAP demo 验证实时链路。
// 若后续需要命令行式 wav 解码，可在 OHOS native test runner 中链接 sherpa-onnx C-API 后实现。

#include <string>

std::string AmphionNativeProbeVersion() {
  return "amphion-harmony-native-probe-0.1.0";
}
