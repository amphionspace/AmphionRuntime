# Android TTS Demo 3.1 交付记录

2026-09-17 资源内置修订。SHA-256 和历史包见 [JSON](demo-3.1-20260917.json)。仅本地打包，未上传。

独立 ZIP 包含 Debug APK、可编译 Demo 源码、相同版本的内置资源 Release AAR、安装脚本和说明。不再附 external-resources，不含授权文件、私钥、SN、构建缓存或测试 APK。

包名 `com.lits.tts.demo31`，显示名 `Lits TTS Demo 3.1`；默认中英哲学文本和大小屏页面不变。默认分块仍为 50；100 仅在测试中临时输入。安装脚本配置用户授权/SN，清理旧 Demo 模型目录后由 SDK 从 APK 自动解包。

最终 APK 使用随包 main 源码构建；与仓库 sample 一致。Release AAR 与 SDK 包逐字节一致，APK/AAR 内资源逐文件一致。无外置模型的预热、100 帧播放、默认文本和两种布局通过；页面重建因熄屏首次失败，唤醒后补测通过。ZIP CRC 和逐文件 SHA-256 校验通过。

证据在本地 `outputs/tts31-embedded-validation-20260917`。不宣称执行完整语料、长期压力或生产签名验收。详见 [SDK 记录](3.1-20260917.md) 与 [固定交付清单](../delivery/README.md)。
