# 阶段 B 前置：Android 工具链精确版本与安装步骤

本节说的所有工具，安装顺序就是下面列出的顺序。整个工具链一旦装好，阶段 B 的 .so 编译、阶段 C 的 SDK Gradle 工程、阶段 D 的 Sample App 都能跑。

如果你只想"零基础一气呵成跑通 demo"，看 `QUICKSTART.md`；本文是组件参考手册，按组件维度组织，便于回查。

## 0. 锁定的版本表

| 工具 | 锁定版本 | 必要性 |
| --- | --- | --- |
| Android Studio | Koala 2024.1.1 Patch 2 或更高（2024.1.x / 2024.2.x 都行） | 必须 |
| Android SDK Platform | API 34（compileSdk / targetSdk） | 必须 |
| Android SDK Platform | API 24（minSdk） | 必须（SDK manager 自动按需装） |
| Android SDK Build-Tools | 34.0.0 | 必须 |
| Android SDK Platform-Tools | 35.0.x | 必须 |
| Android Gradle Plugin | 8.4.0 | 由工程 libs.versions.toml 自动拉 |
| Gradle Wrapper | 8.6 | 由 gradle/wrapper/gradle-wrapper.properties 自动拉 |
| Kotlin | 1.9.22 | 由工程自动拉 |
| Android NDK | 26.3.11579264（r26d） | 必须；用于编 .so |
| CMake | 3.22.1 | 必须；用于编 .so |
| JDK | 17（OpenJDK 或 Temurin 17） | 必须；AGP 8.x 要求 JDK 17 |
| Dokka | 1.9.20 | 必须；API 文档生成 |

注：Android Studio 自带 OpenJDK 17，如果你机器上没有 JDK，最省事的方式是直接让 Studio 用它内置的 JDK（在 Studio 设置里 Gradle JDK 选 `Embedded JDK 17`）。

## 0.5. 基础工具：Homebrew + cmake

Android Studio 装的 CMake 3.22.1 是 NDK build 用的内嵌副本，跟你 PATH 上的 cmake 是两码事。但 sherpa-onnx 上游的 `build-android-arm64-v8a.sh` 在 macOS 主机上需要主机 PATH 上有 cmake（用来跑 cmake configure）。所以宿主机也要装一份。

```bash
# 还没装 brew 就装一下
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# brew 装完不会自动进当前 shell PATH，需要 eval 一下
eval "$(/opt/homebrew/bin/brew shellenv)"

# 写到 ~/.zprofile，下次开 shell 自动生效
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile

brew install cmake
# 上游脚本历史上还会用到 wget；我们的 04_build_android_so.sh 已经替换为 curl，不强求
# 想稳妥就一起装：brew install cmake wget
```

验证：

```bash
which cmake && cmake --version | head -1   # /opt/homebrew/bin/cmake，版本 ≥ 3.22
which curl                                 # macOS 自带，无需 brew install
```

注意，新装完 brew 后必须先 `eval "$(/opt/homebrew/bin/brew shellenv)"`，否则当前终端找不到 brew 命令；这是新手最常踩的一脚。

## 1. 安装 Android Studio

macOS（你的机器）：

```bash
# 用 Homebrew Cask（推荐）
brew install --cask android-studio

# 或者直接到官网下载
# https://developer.android.com/studio
# 下 Mac with Apple silicon 版（dmg）
```

装完后第一次启动会询问"导入设置"，选 `Do not import settings`。

进入 Welcome 界面后：

1. 在右下角的 `More Actions` -> `SDK Manager` 打开 SDK 管理器。
2. 在 `SDK Platforms` 标签页里勾选：
   - `Android 14.0 (API 34)`（必勾）
   - `Android 7.0 (API 24)`（最小 SDK，AGP 也需要）
3. 在 `SDK Tools` 标签页里把 `Show Package Details` 打勾（重要，不勾选不到具体版本号），然后勾选：
   - `Android SDK Build-Tools 34.0.0`
   - `Android SDK Platform-Tools`（任意最新，35.0.x）
   - `NDK (Side by side)` -> `26.3.11579264`（默认不会装，必须手动勾，否则后面编 .so 会报"NDK 不存在"）
   - `CMake` -> `3.22.1`
4. 点 `Apply`，让它装完（NDK 单项约 2 GB，慢；CMake 30 MB）。

装完后，把环境变量一次性写到 `~/.zprofile`（macOS Catalina+ 默认是 zsh）：

```bash
cat >> ~/.zprofile <<'EOF'

# Android SDK
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_NDK="$ANDROID_HOME/ndk/26.3.11579264"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/build-tools/34.0.0:$PATH"
EOF

source ~/.zprofile
```

为什么是 `~/.zprofile` 而不是 `~/.zshrc`？前者只在登录 shell 加载一次，后者每开 tab 都加载。Android 这种 PATH 类配置放 zprofile 性能更好。

注意：

- AGP 8.4 build 时还会从 工程目录的 `local.properties` 读 `sdk.dir`。即使 `ANDROID_HOME` 已经 export 了，如果工程没有 `local.properties` 也可能报"SDK location not found"。最稳妥是两边都配。
- 后续 `./gradlew :sample:installDebug` 会调 `adb install`，所以 `platform-tools` 必须在 PATH。

## 2. JDK 17

AGP 8.4 必须用 JDK 17（JDK 21 会报 `Unsupported class file major version 65`，JDK 11 会报 `Unsupported class file major version 55` 反向不兼容）。三种来源任选其一：

A. 用 Android Studio 内置（最省事，推荐）

不用装。Studio 启动一次后，自带的 JBR 就是 17：

```bash
ls "/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/java"
"/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/java" -version
# 应该看到 openjdk version "17.x.x"
```

`./gradlew` 会优先看工程根的 `gradle.properties`（我们没设）、再看 `JAVA_HOME`，最后用 PATH 里第一个 java。所以即使你的 PATH 里 java 是 21，只要把 `JAVA_HOME` 指向 Studio 内置 17 即可：

```bash
echo 'export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"' >> ~/.zprofile
source ~/.zprofile
```

B. 用 Homebrew Temurin

```bash
brew install --cask temurin@17
/usr/libexec/java_home -V                     # 应该看到 17
echo 'export JAVA_HOME=$(/usr/libexec/java_home -v 17)' >> ~/.zprofile
source ~/.zprofile
java -version                                 # openjdk version "17.x.x"
```

C. 完全不管 JAVA_HOME（适合机器上只有这一个 JDK 的场景）

只要 `java -version` 输出 17 就行。Gradle 自己会找。

## 3. 验证整套环境

```bash
echo "ANDROID_SDK_ROOT=$ANDROID_SDK_ROOT"
echo "ANDROID_NDK=$ANDROID_NDK"
echo "JAVA_HOME=$JAVA_HOME"

# 应该都能列出来
ls "$ANDROID_NDK"/build/cmake/android.toolchain.cmake
ls "$ANDROID_SDK_ROOT"/build-tools/34.0.0/aapt2
ls "$ANDROID_SDK_ROOT"/platform-tools/adb

# 看一下 NDK 版本
cat "$ANDROID_NDK"/source.properties
# 应该是 Pkg.Revision = 26.3.11579264
```

如果上面 4 条命令任何一条失败，先回到第 1 步把缺的组件补齐。

## 4. 第一次跑 Gradle 同步会下载的东西

阶段 C 的工程第一次执行 `./gradlew` 会自动联网下载：

- Gradle 8.6 distribution（约 130 MB）
- Android Gradle Plugin 8.4.0 + 一系列 androidx 依赖（约 200 MB，用 mavenCentral / google）
- Kotlin 1.9.22 编译器与标准库
- Dokka 1.9.20 plugin

注意墙的问题，建议提前在 `~/.gradle/init.d/repos.gradle` 里加一份镜像（可选）：

```groovy
allprojects {
    repositories {
        // 国内镜像，按需打开
        // maven { url 'https://maven.aliyun.com/repository/google' }
        // maven { url 'https://maven.aliyun.com/repository/public' }
        google()
        mavenCentral()
    }
}
```

## 5. 与 sherpa-onnx 官方工具链的差异

| 项 | sherpa-onnx 官方 SherpaOnnxAar | 我们 AmphionRuntime | 原因 |
| --- | --- | --- | --- |
| Kotlin | 1.7.20 | 1.9.22 | Dokka 1.9 + 较新的 KDoc 渲染需要 |
| compileSdk | 34 | 34 | 一致 |
| minSdk | 21 | 24 | 你的目标；24 起可以用更多新 API |
| AGP | 8.4.0 | 8.4.0 | 完全一致，避免 NDK 兼容差异 |
| Gradle | 8.6 | 8.6 | 一致 |
| ABI | 4 个全编 | 默认 arm64-v8a，可选 armeabi-v7a | 你的目标 |
| onnxruntime | 1.24.3 | 1.24.3 | 一致 |

把 Kotlin 升到 1.9.22 不会带来公开 API 变化（我们的 SDK 表面只用了 `class`/`interface`/`data class`，没用到 1.8+ 才有的 inline value class、context receivers 等高级特性）。

## 6. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| Gradle sync 报 `Unsupported class file major version 65` | 你装的是 JDK 21 | 改用 JDK 17（AGP 8.x 不支持 JDK 21） |
| `NDK at ... did not have a source.properties file` | NDK 没装全 | SDK Manager 里把 NDK 26.3.11579264 卸了重装 |
| `CMake '3.22.1' was not found in PATH` | CMake 没勾 | SDK Tools 里勾 CMake 3.22.1 |
| `aapt2: error: failed processing manifest` | minSdk 比 manifest 的更高 | 检查工程里所有 `minSdk` 都是 24 |
| Studio 一直 Indexing 不结束 | Apple Silicon 第一次跑 + 未授权用 Rosetta | 让它跑完，1~2 小时正常 |
| 装完 brew 之后 `zsh: command not found: brew` | brew 没进当前 shell PATH | `eval "$(/opt/homebrew/bin/brew shellenv)"`；写一份到 ~/.zprofile 永久 |
| 装完 brew 之后 `cmake: command not found` | 没装 cmake 或 brew 没进 PATH | 先确保 brew 能用，再 `brew install cmake` |
| Build 时报 `wget: command not found` | 上游 build-android-*.sh 用 wget 下 onnxruntime | 我们的 04 脚本已替换为 curl prefetch，无需 wget；硬要用就 `brew install wget` |
| `./gradlew :sdk:assembleRelease` 报 `SDK location not found` | 既没 ANDROID_HOME 也没 local.properties | 工程根加 `local.properties`，里面写 `sdk.dir=$HOME/Library/Android/sdk`（带 EOF 时记得展开变量） |
| Kotlin 编译大量报 `Visibility must be specified in explicit API mode` | sdk/build.gradle.kts 启了 -Xexplicit-api=strict 但上游 Kotlin 文件不满足 | 把 `freeCompilerArgs` 里的 `-Xexplicit-api=strict` 删掉（main 工程已经默认去掉，自己后续别加） |
| `adb: more than one device/emulator` | emulator 与真机并存 | `export ANDROID_SERIAL=<真机 serial>`，或 `adb -s <serial> ...` |
| 真机连接但无线调试链路不通 | pairing 与 connect 端口搞混 | pairing 用手机"Pair with code"页那个一次性端口，connect 用 Wireless debugging 主页那个持续端口 |
