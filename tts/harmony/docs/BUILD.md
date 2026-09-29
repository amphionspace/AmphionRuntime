# Harmony TTS 构建与验证入口

当前模型清单、TN 编译、HAR 与 sample HAP 命令统一维护在 [BUILD_FROM_SOURCE.md](BUILD_FROM_SOURCE.md)，不在本页重复。工具链使用 DevEco CLI、独立 CLT 与 JDK。

- HAR：`tts/harmony/sdk/build/default/outputs/default/sdk.har`。
- 测试载体：`tts/harmony/sample/build/default/outputs/default/sample-default-unsigned.hap`；安装前须使用目标设备信任的签名。
- 资产与源码边界：[DELIVERY.md](DELIVERY.md)。

构建通过只说明代码和资源可以打包。设备验证还应检查授权、模型加载、公开回调、PCM 格式、合成和播放，并将结果绑定实际提交、HAR/HAP 哈希及设备。

早期记录曾使用 `verify_lits_harmony_package.mjs`，该脚本不在当前仓库；不能继续执行或将其旧通过结果作为当前验收。早期 sample 安装曾返回 `9568257 / fail to verify pkcs7 file`，属于当时设备的签名信任失败，不能据此推断当前设备状态。
