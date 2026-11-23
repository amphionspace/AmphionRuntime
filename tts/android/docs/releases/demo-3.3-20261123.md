# Android TTS Demo 3.3 交付记录

2026-11-23 随 SDK 3.3 的 Demo 包。SHA-256 见 [JSON](demo-3.3-20261123.json)。仅本地打包，未上传。

独立 ZIP 包含 Debug APK、可编译 Demo 源码（依赖 app/libs 中与 SDK 包逐字节相同的 3.3 Release AAR）、安装脚本和说明；
不含授权文件、私钥、SN、构建缓存或测试 APK。包名 `com.lits.tts.demo33`，显示名 `Lits TTS Demo 3.3`；界面与默认文本沿用 3.2。

验证：内部测试机用随包安装脚本安装与授权配置通过；`TtsLifecycleDeviceTest` 与 `PronunciationFix33DeviceTest`（3/3 PCM 逐字节相同，3.2 Demo 同用例失败）在该 Demo 上通过；Demo 工程独立构建未跑。详见 [SDK 记录](3.3-20261123.md)。
