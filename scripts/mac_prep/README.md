# Mac 等待模型期间的准备工作

在 **AmphionRuntime 仓库根** 执行（`cd AmphionRuntime`）。

| 步骤 | 脚本 | 对应 |
| --- | --- | --- |
| ① 环境自检 | `bash scripts/mac_prep/01_check_env.sh` | JDK / SDK / adb / submodule |
| ② 拉 submodule | `bash scripts/mac_prep/02_init_submodule.sh` | sherpa-onnx |
| ③ demo 编 APK + 单测 | `bash scripts/mac_prep/03_build_demo.sh` | QUICKSTART 精简链 |

## Android Studio / SDK 路径（Homebrew 装完后）

| 项 | 路径 |
| --- | --- |
| Android Studio | `/Applications/Android Studio.app` |
| SDK（首次打开 Studio 向导后生成） | `~/Library/Android/sdk` |
| NDK（需在 SDK Manager 安装） | `~/Library/Android/sdk/ndk/26.3.11579264` |
| adb（platform-tools cask） | `/opt/homebrew/bin/adb` |

项目里已写好 `android/AmphionRuntime/local.properties` → `sdk.dir=.../Library/Android/sdk`。

每次开终端加载环境：

```bash
source /Users/amphion/Desktop/work/projects/鼎桥/AmphionRuntime/scripts/mac_prep/00_android_env.sh
```

**第一次**：打开 Android Studio → 完成 Setup Wizard → **SDK Manager**：

- **SDK Platforms**：Android 14 (API **34**) ✓（你已有可跳过）
- **SDK Tools**（必勾）：
  - **Android SDK Command-line Tools (latest)**
  - **NDK (Side by side)** → 展开勾选 **26.3.11579264**

装完终端执行：

```bash
source scripts/mac_prep/00_android_env.sh
bash scripts/mac_prep/01_check_env.sh
# 若仍 WARN NDK，且已装 Command-line Tools：
bash scripts/mac_prep/01b_install_ndk.sh
```

若 `01_check_env` 仍报 SDK MISS，但 Studio 已装好：先 `source 00_android_env.sh` 再检查（路径应为 `~/Library/Android/sdk`）。

## 缺依赖时（常见）

```bash
brew install --cask temurin@17
brew install --cask android-studio
brew install --cask android-platform-tools
```

装完 JDK 后：

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
```

## 测评子集（冀R/辽B 各 20 句）

在 `test_data` 目录：

```bash
python3 generate_eval_subset.py
```

产出见 `test_data/generated/plate_eval_subset_*.txt`。

## 编 sample APK / 装手机（注意目录）

`gradlew` 在 **`android/AmphionRuntime`**，不在仓库根目录：

```bash
cd /Users/amphion/Desktop/work/projects/鼎桥/AmphionRuntime/android/AmphionRuntime
./gradlew :sample:assembleDebug
adb devices   # 必须先看到一台 device
adb install -r sample/build/outputs/apk/debug/sample-debug.apk
```

`adb: no devices`：USB 连真机 → 开启「开发者选项 / USB 调试」→ 手机上点「允许」→ 再 `adb devices`。
