# Android TTS Demo 3.1 交付记录

独立交付包：lits-dingqiao-tts-android-demo-vocos24k-3.1.zip。SHA-256 和构建信息见 [JSON](demo-3.1-20260917.json)。

包含 Debug APK、可独立打开编译的 Android Studio 工程、同 SDK 3.1 的 AAR 和外置 IMF 170000 资源、安装配置脚本、说明及校验文件。不包含授权文件、私钥、SN、Gradle 缓存、构建目录或测试 APK。

Demo main 源码原样来自当前 sample，保留大小屏界面、ViewModel 生命周期和 RSS 显示。独立工程仅调整 Gradle 依赖为本地 Release AAR、包名/应用名/版本号及 ABI；不需要 SDK 引擎或训练源码。

包名 com.lits.tts.demo31，显示名 Lits TTS Demo 3.1；使用调试签名，不覆盖已有 IMF/student 对比 App。用户提供自己的 license 和真实设备 SN，安装脚本写入 Demo 私有目录后启动。用于当前手机验证的测试授权未进入交付包。

已通过独立工程构建；分发源码与实际编译 main 源码一致，AAR 与 SDK 3.1 相同。TECNO KI8 / Android 13：两种布局控件、页面重建保留合成请求及结果、界面 SDK 流式播放 3 项测试通过。模型信息确认 IMF 170000。原始证据位于本地 outputs/tts-demo31-validation-20260917，不随包交付。最终 ZIP 已做 CRC 和逐文件 SHA-256 校验。

未把 Debug 演示工程宣称为生产签名 APK；未新增完整语料或长期压力验收。
