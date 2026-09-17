# Lits TTS Android Demo 3.1

## 包内内容

- `apk/lits-dingqiao-tts-demo-vocos24k-3.1.apk`：可安装的 Debug Demo。
- `android-demo/`：可独立编译的 Android Studio 工程，依赖 app/libs 中的 3.1 Release AAR。
- `tools/install_demo.py`：安装 APK、配置用户自有授权。
- `LICENSE`、`NOTICE`、`CHECKSUMS.txt`：使用条件、第三方声明和文件校验。

应用包名 `com.lits.tts.demo31`，显示名 `Lits TTS Demo 3.1`。支持 Android API 24+、arm64-v8a，沿用现有大屏/小屏界面。
本包不包含授权文件、私钥或设备 SN；模型及前端资源已内置于 AAR/APK；APK 安装后只需配置有效授权。首次创建引擎时自动解包，后续复用。

## 安装和配置

电脑准备 Python 3、Android platform-tools（adb），手机打开 USB 调试并授权连接。
使用已经签发、含 TTS 权限且覆盖目标手机 SN 的 license，在本包根目录执行：

```bash
python3 tools/install_demo.py --adb /path/to/adb --license /path/to/amphion-license.lic
```

脚本默认使用 ADB 设备序列号作为 Debug Demo 的 SN；必须与签发时登记的真实 SN 一致。若设备平台提供不同的正式 SN，显式传 `--sn <真实设备SN>`。多台手机连接时用 `--serial <ADB设备序列号>` 指定目标。

脚本安装本包 APK，清理该 Demo 工作目录中的旧模型，将授权和 SN 写入 Demo 私有目录，然后启动应用。清理是为了切换到内置模型；不需要再传输模型文件。
授权及 SN 只提供给 Demo 本地校验，不发送到网络；私钥无需提供。
手机已有 IMF / student 对比 App 使用不同包名，本 Demo 不覆盖它们。

应用会预热模型。完成后可切换中英、输入文本并选择“SDK 播放”或“仅合成”；页面显示运行内存，屏幕大小由 Android 自动选择布局。流式 chunkSize 留空用 50，正数覆盖不得低于 40，例如 100 可用。

内置模型与解包文件会各占一份磁盘空间，首次预热需要解包时间。资源未变更时，普通启动直接复用已解包文件。

## 从源码编译

用 Android Studio 打开 `android-demo/`，准备 JDK 17、Android SDK 34、Build Tools 和本机 SDK 路径。也可使用：

```bash
cd android-demo
./gradlew :app:assembleDebug
```

Windows 使用 `gradlew.bat :app:assembleDebug`。Gradle Wrapper 使用 Gradle 8.6；首次构建需获取 Gradle/Android 依赖，TTS 运行本身完全离线。
输出：`app/build/outputs/apk/debug/app-debug.apk`。独立源码直接使用本地 AAR，不需要 SDK 引擎源码、训练 checkpoint、NDK 或签发私钥。
重新编译后可用 `tools/install_demo.py --apk <新APK路径> --license <授权路径>` 安装配置。

本 APK 使用开发调试签名；源码在另一台电脑生成的调试签名可能不同。遇到 INSTALL_FAILED_UPDATE_INCOMPATIBLE 时需卸载旧 Demo 再安装，卸载会清除该 Demo 私有数据，之后重新配置授权。

这是演示接入工程，不是 SDK 引擎源码或模型训练源码。Debug 版本为现场配置支持 run-as 和 SN 文件；正式应用应使用自己的安全配置、设备 SN 获取方式和签名。

## 校验

在包根目录执行 `shasum -a 256 -c CHECKSUMS.txt`。
