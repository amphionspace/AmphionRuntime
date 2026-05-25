# 零到真机跑通 Demo：完整端到端指南

适用：macOS（Apple Silicon）+ Android Studio Koala/Ladybug+ + 一台 arm64 真机
目标：跑通 整套 SDK 链路（编 .so → 出 AAR → 装 sample → 推 demo 模型 → 看到中英流式识别结果）。
预计总耗时：80–110 分钟（其中 60 分钟以上是各种下载和首次编译，机器只是闲着等）。

本文是按 实际真机验证过的成功路径 写的，每一步都给可以直接 copy 的命令，并把每个验证点和失败时的处置写在旁边。如果你只想集成 SDK 不想从源码构建，请看 `android/AmphionRuntime/docs/INTEGRATION.md`。

## 0. 时间表与你需要的东西

| 阶段 | 内容 | 耗时 | 网络下载量 |
| --- | --- | --- | --- |
| 0 | Homebrew + cmake (+ wget) | 5 min | ~50 MB |
| 1 | Android Studio + SDK Platform 34 + Build-Tools + NDK r26d | 15–30 min | ~3 GB |
| 2 | 写环境变量到 .zprofile | 1 min | 0 |
| 3 | 下载 demo 模型 | 1–3 min | 487 MB |
| 4 | 编 sherpa-onnx-jni.so（含 onnxruntime 预下） | 15–25 min | ~440 MB |
| 5 | 拷 .so 到 SDK 工程 | <10 sec | 0 |
| 6 | 初始化 Gradle wrapper | <10 sec | 0 |
| 7 | 编 SDK AAR（Gradle 8.6 + AGP 8.4 首次同步） | 5–10 min | ~300 MB |
| 8 | 配对无线调试 | 1 min | 0 |
| 9 | 编 sample APK 并安装 | 2–3 min | 0 |
| 10 | push demo 模型到设备 | 1–3 min | 0（USB / WiFi 局域网） |
| 11 | 重启 app 验证识别 | <1 min | 0 |

需要准备：

- 至少 15 GB 可用磁盘空间
- 一台 arm64 真机（Snapdragon 6xx 以上 / 麒麟 970+ / Apple-style ARMv8），建议 Android 8+
- 真机和 Mac 在同一 WiFi（用无线调试）；或一根 USB-C 数据线（用 USB 调试）
- 不需要 翻墙，所有资源都在 Google CDN / GitHub / Homebrew 镜像

## 1. 装基础工具（Homebrew + cmake）

打开 macOS 自带 Terminal，执行：

```bash
# 1.1 装 Homebrew（如果已经装过就跳过）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 1.2 让 brew 进当前 shell PATH（很容易忘 → 之后 `brew install` 会报 command not found）
eval "$(/opt/homebrew/bin/brew shellenv)"

# 1.3 永久写到 ~/.zprofile，下次开终端自动生效
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile

# 1.4 装 cmake（必装）+ wget（可装可不装）
brew install cmake
# 想顺手装 wget 也行：brew install cmake wget
```

验证：

```bash
which cmake && cmake --version | head -1
# 期望：/opt/homebrew/bin/cmake，版本 ≥ 3.22
```

## 2. 装 Android Studio + 命令行需要的组件

如果还没装 Android Studio：

```bash
brew install --cask android-studio
```

启动一次让它把基础组件装好（首次启动会下 ~1 GB 的 SDK Platform）。然后：

1. 主菜单 `More Actions` → `SDK Manager`，或工程内 `Tools` → `SDK Manager`
2. 切到 `SDK Platforms`，勾选：
   - Android 14.0 (API 34) — 必勾
   - Android 7.0 (API 24) — 推荐勾（minSdk 用）
3. 切到 `SDK Tools`，右下勾 `Show Package Details`，再勾选：
   - Android SDK Build-Tools 34.0.0
   - Android SDK Platform-Tools（任意最新版）
   - NDK (Side by side) → 26.3.11579264 — 默认不会装，必须手动勾
   - CMake → 3.22.1
4. `Apply` → `OK`，等下载安装完（NDK ~2 GB，慢）

注意：`NDK (Side by side)` 这一项必须展开后勾具体版本号 26.3.11579264。Android Studio 默认不带 NDK，不勾就会在编 .so 阶段报"NDK 不存在"。

验证：

```bash
ls "$HOME/Library/Android/sdk/ndk/26.3.11579264/build/cmake/android.toolchain.cmake"
ls "$HOME/Library/Android/sdk/build-tools/34.0.0/aapt2"
ls "$HOME/Library/Android/sdk/platform-tools/adb"
# 三条都返回路径而不是 No such file，就 OK
```

## 3. 写一份永久环境变量

把 SDK / NDK / adb 全部加到 PATH，避免后续每次都要 export。一次性追加到 `~/.zprofile`：

```bash
cat >> ~/.zprofile <<'EOF'

# Android SDK
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_NDK="$ANDROID_HOME/ndk/26.3.11579264"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/build-tools/34.0.0:$PATH"
EOF

# 让当前 shell 立刻生效
source ~/.zprofile

# 验证
echo $ANDROID_NDK
which adb && adb version
```

JDK：AGP 8.4 要求 JDK 17。Android Studio 自带一份内置的；如果你机器上 `java -version` 不是 17 也不影响 Gradle build（Gradle 会用 Studio 内置那个）。万一 build 时报 `Unsupported class file major version`，把这一行也加到 `~/.zprofile`：

```bash
echo 'export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"' >> ~/.zprofile
source ~/.zprofile
java -version    # 应该看到 17.x.x
```

## 4. 下载 demo 模型

强烈推荐先用 demo 模型把工程跑通，再换自己的 ONNX。理由见 `tools/asr/README.md`。

```bash
cd /Users/boxp/workspace/amphion-runtime
bash tools/asr/00_fetch_demo_model.sh
```

会下载 487 MB 的 sherpa-onnx 官方 streaming-zipformer-bilingual-zh-en-2023-02-20，自动重命名为 SDK 标准布局，并生成 manifest.json。

验证：

```bash
ls -lh tools/asr/demo-model/zipformer_L_zh_en/
# 期望看到：
#   encoder.int8.onnx   ~173 MB
#   decoder.onnx        ~13 MB
#   joiner.int8.onnx    ~3.1 MB
#   tokens.txt          ~55 KB
#   manifest.json       ~1.3 KB
```

## 5. 编 sherpa-onnx-jni.so

只编 arm64-v8a，速度最快：

```bash
cd /Users/boxp/workspace/amphion-runtime
bash tools/asr/04_build_android_so.sh arm64-v8a
```

脚本会做这些事：

1. 自检 cmake / curl / NDK 是否齐全
2. 用 curl 预下 onnxruntime-android-1.24.3.zip（约 39 MB）
3. 调用仓库自带的 `build-android-arm64-v8a.sh`，cmake configure + make + install/strip
4. 用 llvm-readelf 打印 .so 的 NEEDED 依赖

整个过程 15–25 分钟。期间 Terminal 会滚动 `[ N%] Building CXX object ...`，正常现象。

验证：

```bash
ls -lh build-android-arm64-v8a/install/lib/
# 期望：
#   libonnxruntime.so       ~25 MB
#   libsherpa-onnx-jni.so   ~3 MB
```

## 6. 拷 .so 到 SDK 工程

```bash
bash tools/asr/05_package_aar_libs.sh
```

会把上一步的两个 .so 拷到 `android/AmphionRuntime/sdk/src/main/jniLibs/arm64-v8a/`。armeabi-v7a 没编，会被 SKIP，是预期行为。

## 7. 初始化 Gradle 工程并编 AAR

```bash
cd android/AmphionRuntime

# 7.1 第一次：从官方 SherpaOnnxAar 复制 gradlew 二进制（一次性）
bash init_gradle_wrapper.sh

# 7.2 写 local.properties，告诉 AGP SDK 在哪
cat > local.properties <<EOF
sdk.dir=$HOME/Library/Android/sdk
EOF

# 7.3 编 AAR（首次会下 Gradle 8.6 + AGP 8.4 + Kotlin + AndroidX，约 5–10 分钟）
./gradlew :sdk:assembleRelease
```

验证：

```bash
ls -lh sdk/build/outputs/aar/sdk-release.aar
# 期望约 28 MB（含 jniLibs/arm64-v8a/ 两个 .so）

# 顺手看看 AAR 内部结构
unzip -l sdk/build/outputs/aar/sdk-release.aar | grep -E '\.so|classes\.jar|AndroidManifest'
```

第一次跑会看到很多类似下面的"恐怖"日志：

```
This version only understands SDK XML versions up to 3 but an SDK XML file of version 4 ...
Failed to fetch URL https://dl.google.com/android/repository/sys-img/...
意外的元素 (uri:"", local:"abi") ...
```

这些是 AGP 在解析 SDK 元数据时枚举到了它不认识的 system image。能忽略，不影响 build。Build-Tools 34 / Platform 34 这两个真正用到的会被装好（terminal 末尾会看到 `License accepted` / `complete`）。

## 8. 配对无线调试

如果用 USB 数据线，跳过这一节，直接 `adb devices` 确认有设备即可。

无线调试要求手机和 Mac 在同一 WiFi。

手机端：

1. 设置 → 关于本机 → 连点 7 次"版本号"，开发者选项启用
2. 系统 → 开发者选项 → 启用 Wireless debugging
3. 进入 Wireless debugging 页面 → 点 `Pair device with pairing code`
4. 屏幕显示一段 IP:port + 6 位配对码，先不要关

Mac 终端：

```bash
# 用手机屏幕上的 pairing IP:port，不是主页那个
adb pair 192.168.1.100:38271
# 提示输入 6 位 pairing code，输入回车
# 看到 Successfully paired

# 配对成功后，回到手机的 Wireless debugging 主页，复制主页那个 IP:port（端口和 pairing 不同）
adb connect 192.168.1.100:42123
# 看到 connected to 192.168.1.100:42123

adb devices
# 期望：
# 192.168.1.100:42123    device
```

如果 `adb devices` 同时显示模拟器或多个设备，会触发 `more than one device/emulator` 错误。永久指定真机：

```bash
export ANDROID_SERIAL=192.168.1.100:42123
# 之后所有 adb / gradle install 命令默认走这台
```

## 9. 装 sample APK

```bash
cd /Users/boxp/workspace/amphion-runtime/android/AmphionRuntime
./gradlew :sample:installDebug
```

无线调试 install 比 USB 慢，5–10 MB 的 APK 通常 30 秒到 1 分钟。

启动一次 让 externalFilesDir 提前创建（push 模型脚本要用到这个目录）：

```bash
adb shell am start -n com.amphion.asr.sample/.eval.LandingActivity
```

屏幕会显示「没找到本地模型」，并附带 push 命令的提示，预期行为。

## 10. push demo 模型到设备

```bash
cd /Users/boxp/workspace/amphion-runtime
bash tools/asr/00_fetch_demo_model.sh push

# 如果连了多个设备，明确指定：
# bash tools/asr/00_fetch_demo_model.sh push 192.168.1.100:42123
```

会把 4 个模型文件 + manifest.json 推到设备的：

```
/sdcard/Android/data/com.amphion.asr.sample/files/asr-models-import/
  zipformer_L_zh_en/1.0.0/
```

（本地 `demo-model/zipformer_L_zh_en/` 是单层目录，设备端 ModelImporter 期望 `<id>/<v>/` 双层路径，push 脚本会自动补上 `1.0.0` 这一层。）

总共约 190 MB；USB ~10 秒，WiFi 5 GHz ~1 分钟，2.4 GHz ~3 分钟。

## 11. 重启 app 验证识别

```bash
adb shell am force-stop com.amphion.asr.sample
adb shell am start -n com.amphion.asr.sample/.eval.LandingActivity

# 实时看日志
adb logcat -c && adb logcat -s AsrSdk AsrSampleImporter MainActivity *:E
```

预期 logcat 输出：

```
AsrSampleImporter: importing /sdcard/.../zipformer_L_zh_en/1.0.0 -> /data/user/0/.../asr-models/...
AsrSdk: AsrSdk initialized, version=1.0.0, logLevel=WARN
AsrSdk: OnlineRecognizer loaded from /data/user/0/com.amphion.asr.sample/files/asr-models/zipformer_L_zh_en/1.0.0
```

屏幕状态变成「模型就绪，按住说话」，按住按钮说话：

- 「实时结果」框：partial 文本随说话增量刷新
- 松开后：「最终结果」框追加一行 final 文本

成功！工程链路全部验证通过。

## 12. 故障排查

按照"症状 → 根因 → 处置"的格式，每条都是真实在调试过程中遇到过的。

| 症状 | 根因 | 处置 |
| --- | --- | --- |
| `bash tools/asr/04_build_android_so.sh: line 31: LATEST_TAG。: unbound variable` | bash 在中文标点旁不能正确截断变量名 | 已修复（${VAR} 显式界定）。如自己写脚本注意：变量后接中文标点必须 `${VAR}` 不能 `$VAR` |
| `[ERROR] /Users/.../ndk/26.3.11579264 看起来不是合法 NDK` | Android Studio 没装 NDK | SDK Manager → SDK Tools → 勾 Show Package Details → 勾 NDK 26.3.11579264 |
| `wget: command not found` | 上游 build-android-*.sh 用 wget | 04 脚本现在自带 curl prefetch，不再需要 wget；如要装：`brew install wget` |
| `cmake: command not found` | macOS 默认没 cmake | `brew install cmake`；先确保 `eval "$(/opt/homebrew/bin/brew shellenv)"` 让 brew 进 PATH |
| `zsh: command not found: brew` 装完 brew 后 | brew 不在 PATH | `eval "$(/opt/homebrew/bin/brew shellenv)"`；写到 ~/.zprofile 永久 |
| `./gradlew :sdk:assembleRelease` → `SDK location not found` | 没写 local.properties，也没 export ANDROID_HOME | `cat > local.properties <<EOF\nsdk.dir=$HOME/Library/Android/sdk\nEOF`，或者 `export ANDROID_HOME=...` |
| Kotlin 编译报 100+ 条 `Visibility must be specified in explicit API mode` | 我之前在 sdk/build.gradle.kts 加了 -Xexplicit-api=strict，与从上游复制的 com.k2fsa.sherpa.onnx.* 冲突 | 已修复（去掉了 strict 开关） |
| `zsh: command not found: adb` | platform-tools 不在 PATH | 把 `$ANDROID_HOME/platform-tools` 加到 PATH，参见第 3 节 |
| `adb: more than one device/emulator` | 有 emulator 同时在线 | `export ANDROID_SERIAL=<真机 serial>`，或关掉 emulator |
| 真机连不上无线调试 | 配对端口和连接端口是不同的两个 | pairing 用手机"Pair with code"页面那个端口（一次性），connect 用 Wireless debugging 主页那个端口（持续有效） |
| `BUILD SUCCESSFUL` 但 logcat 看到 `Unable to strip the following libraries: libonnxruntime.so, libsherpa-onnx-jni.so` | AGP 找不到 NDK 的 llvm-strip 想再 strip 一次 | 忽略。这两个 .so 在 04 脚本里 `make install/strip` 已经 strip 过了 |
| 屏幕一直停在「准备模型…」 | 多种可能；先看 logcat | `adb logcat -s AsrSdk` 找具体错误码：2002 是模型文件缺失；2003 是 native 加载失败 |
| 「实时结果」一直空 | 录音权限没给 | 第一次启动会弹权限对话框；如错过，去系统设置 → 应用 → ASR Sample → 权限 → 麦克风 |
| 装 sample 时 `INSTALL_FAILED_NO_MATCHING_ABIS` | 设备是 x86_64（模拟器），SDK 只编了 arm64-v8a | 用真机；或在 sdk/build.gradle.kts 里把 `abiFilters` 加上 x86_64 重编 |
| Build 中途 `Java heap space` | 默认 -Xmx4096m 在 8 GB Mac 偏紧 | gradle.properties 里把 `org.gradle.jvmargs=-Xmx4096m` 改成 `-Xmx2048m`，编译速度差不多 |
| 多次 build 后磁盘吃紧 | Gradle 缓存 + onnxruntime 解压 + NDK 各 1+ GB | 临时清理：`rm -rf ~/.gradle/caches build-android-*`，下次会重下 |

## 13. 下次再来怎么跑（第二次开始）

环境变量、SDK、NDK、cmake、Gradle wrapper、demo 模型都已就位，第二次只需 4 条命令：

```bash
# 切到工程根
cd /Users/boxp/workspace/amphion-runtime

# 编 + 拷
bash tools/asr/04_build_android_so.sh arm64-v8a    # 增量编译，2–5 分钟
bash tools/asr/05_package_aar_libs.sh

# 装 sample
cd android/AmphionRuntime
./gradlew :sample:installDebug

# 重启 app
adb shell am force-stop com.amphion.asr.sample
adb shell am start -n com.amphion.asr.sample/.eval.LandingActivity
```

模型不变就不用再 push；要换成自己的模型见下一节。

## 14. 换成自己导出的模型

第 4 节用的是 demo 模型。你自己用 icefall 导出 + INT8 量化好的模型怎么放进来？整个链路涉及四个位置，按"宿主机 → 设备外部存储 → 设备内部存储"流向梳理一遍：

```
（1）宿主机准备目录                                    （4）SDK 实际加载位置（内部存储，App 私有）
你随便起的一个目录                                      /data/data/<pkg>/files/asr-models/<id>/<v>/
   │                                                      ▲
   │                                                      │ ModelImporter 启动时一次性迁移并清空源
   │                                                      │
   ▼ adb push（脚本完成）                              （3）设备外部存储（push 中转区，App 可写）
（2）00_push_my_model.sh                               /sdcard/Android/data/<pkg>/files/asr-models-import/<id>/<v>/
```

### 14.1 准备本地目录

把你的 4 个文件按 SDK 硬编码的固定名字组织好：

```
~/my-asr-models/asr-streaming-zipformer-zh-en/1.0.1/
├── encoder.int8.onnx        ← 必需，就用这个名字
├── decoder.onnx             ← 必需，FP32
├── joiner.int8.onnx         ← 必需
├── tokens.txt               ← 必需，第一行必须是 "<blk> 0"
└── manifest.json            ← 可选但强烈建议（里面的 model_type 决定 native 选哪条解码路径）
```

注意：

- 上层目录路径 不需要 跟 model_id / version 同名，这两个值由 push 脚本的 --id / --version 决定。但分两层目录、用 SemVer 版本号是好习惯。
- 文件名是 EngineImpl 写死的（`sdk/src/main/java/com/amphion/asr/internal/EngineImpl.kt:131-136`）。如果你的 icefall 输出叫 `encoder-epoch-99-avg-1.int8.onnx`，必须在本地先 mv 重命名好。
- tokens.txt 第一行必须是 `<blk> 0`；不是的话 sherpa-onnx 加载会失败或乱码。详见 `MODEL_LAYOUT.md` 第 2 节。

### 14.2 生成 manifest.json（可选但建议）

虽然 push 路线不会读 url / sha256 字段，但 manifest 里这几个字段 EngineImpl 会真正读取并应用到运行时：

| 字段 | 作用 | 缺失时行为 |
| --- | --- | --- |
| model_type | 传给 native 让它选对网络分支（zipformer / zipformer2 / paraformer 等） | 留空让 native 从 ONNX metadata 推断；多数模型能成功 |
| decoding_method | 切换 greedy_search 与 modified_beam_search | 用 AsrConfig.Builder 默认 GREEDY_SEARCH |
| max_active_paths | modified_beam_search 时的 beam size | 用 Builder 默认 4 |

streaming zipformer 训出来的应该是 `zipformer2`；老 icefall 的可能是 `zipformer`。配错会在加载时报参数维度不匹配。

调用方在代码里显式调用 `.decodingMethod(...)` / `.maxActivePaths(...)` 的优先级最高，会盖掉 manifest。详见 `android/AmphionRuntime/docs/INTEGRATION.md` 第 7 节。

最快生成：

```bash
cd ~/my-asr-models/asr-streaming-zipformer-zh-en/1.0.1

python3 - <<'PY'
import hashlib, json, os, pathlib
MODEL_ID = "asr-streaming-zipformer-zh-en"
VERSION  = "1.0.1"
MODEL_TYPE = "zipformer2"   # 老模型如果是 zipformer 改这里
BASE_URL = f"https://your-cdn.example.com/{MODEL_ID}/{VERSION}"
FILES = ["encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt"]

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1<<20), b""): h.update(c)
    return h.hexdigest()

manifest = {
    "manifest_version": 1,
    "model_id": MODEL_ID, "version": VERSION,
    "min_sdk_version": "1.0.0", "max_sdk_version": "2.0.0",
    "model_type": MODEL_TYPE,
    "decoding_method": "greedy_search",   # 或 modified_beam_search
    "max_active_paths": 4,                # 仅 modified_beam_search 生效，默认 4
    "sample_rate": 16000, "feature_dim": 80,
    "files": [
        {"name": n, "url": f"{BASE_URL}/{n}",
         "size_bytes": os.path.getsize(n), "sha256": sha256(n)} for n in FILES
    ],
}
pathlib.Path("manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
print("manifest.json written")
PY
```

如果你以后要走真正的远程下载链路（生产环境），把这份 manifest 上传到 CDN，再把 URL 配到 sample 的 `MainActivity.manifestUrl` 即可。

### 14.3 用通用 push 脚本推到设备

```bash
cd /Users/boxp/workspace/amphion-runtime
bash tools/asr/00_push_my_model.sh \
    --src ~/my-asr-models/asr-streaming-zipformer-zh-en/1.0.1 \
    --id  asr-streaming-zipformer-zh-en \
    --version 1.0.1
```

脚本会：

1. 校验 4 个必需文件存在 + tokens.txt 第一行是 `<blk> 0`
2. 校验 sample app 已经装到设备
3. 把整个目录 push 到 `/sdcard/Android/data/com.amphion.asr.sample/files/asr-models-import/<id>/<v>/`
4. 提示重启命令

可选：

- `--serial <adb-serial>` ：多设备时指定
- `--pkg <package-name>` ：你改过 `applicationId` 的话传你的
- `--skip-checks` ：上面两个校验是可以绕过的，但极不建议

### 14.4 让 sample 选中你的模型

sample 里 `MainActivity.ensureModel()` 是这样选模型的：

```121:128:android/AmphionRuntime/sample/src/main/java/com/amphion/asr/sample/MainActivity.kt
        val mm = ModelManager(this)
        // 优先看是否已有本地模型
        val local = mm.listLocal().firstOrNull()
        if (local != null) {
            modelDir = local.dir
            onModelReady(local.dir)
            return
        }
```

`firstOrNull()` 取的是文件系统遍历的第一个，顺序不可控。所以如果设备上同时还有第 10 节装过的 demo 模型，启动时可能用 demo 也可能用你新 push 的。两种处理方式：

A. 推荐：清空 import + 内部存储，再 push 自己的

```bash
# 一次性清掉所有已导入模型
adb shell run-as com.amphion.asr.sample rm -rf files/asr-models
adb shell rm -rf /sdcard/Android/data/com.amphion.asr.sample/files/asr-models-import

# 再 push 自己的
bash tools/asr/00_push_my_model.sh --src ~/my-asr-models/.../1.0.1 \
    --id asr-streaming-zipformer-zh-en --version 1.0.1

adb shell am force-stop com.amphion.asr.sample
adb shell am start -n com.amphion.asr.sample/.eval.LandingActivity
```

B. 如果你想保留多份模型来回切，改 sample 的选择策略：把 `firstOrNull()` 改成 `findLast { it.modelId == "asr-streaming-zipformer-zh-en" }`，按 model_id 锁定一个。这是 sample 应用层的策略，不动 SDK API。

### 14.5 验证你的模型生效了

```bash
adb logcat -c && adb logcat -s AsrSdk AsrSampleImporter MainActivity *:E
```

成功日志应当类似：

```
AsrSampleImporter: importing /sdcard/.../asr-streaming-zipformer-zh-en/1.0.1 -> /data/user/0/.../asr-models/asr-streaming-zipformer-zh-en/1.0.1
AsrSdk: OnlineRecognizer loaded from /data/user/0/com.amphion.asr.sample/files/asr-models/asr-streaming-zipformer-zh-en/1.0.1
```

注意第二行 `OnlineRecognizer loaded from` 后面那段路径，必须是你新 push 的 model_id / version，不是 demo 那个。如果还是看到 `zipformer_L_zh_en`（demo 默认名）或 `sherpa-onnx-streaming-zh-en-demo`（更早的 demo 名），说明清理没做干净，回 14.4 步骤 A。

### 14.6 常见踩坑（针对自有模型）

| 现象 | 根因 | 处置 |
| --- | --- | --- |
| 加载报 `model_type mismatch` 或 encoder 输入维度不匹配 | manifest.json 里 model_type 配错了，或者训练参数与 export 参数不一致 | 老 icefall recipe 用 zipformer，新的（含 chunk-size 32 + left-context 4）用 zipformer2；export-onnx-streaming 时这两个是 fusion 进 ONNX 的，必须与训练时一致 |
| 加载成功但识别全空 / 全是同一个字符 | tokens.txt 第一行不是 `<blk> 0` | 用编辑器打开看，缺则在最前面插入 `<blk> 0` 一行，并把后续所有 id 全部 +1（注意保持升序连续） |
| 加载成功但识别全是 `<unk>` | tokens.txt 与训练时的 BPE 不一致（混用了不同 recipe） | 必须用训练这版模型时的同一份 bpe.model 派生 tokens.txt |
| 识别出来全是英文，听不到中文 | encoder.int8 量化没用 per_channel | 重做量化，加上 `per_channel=True`（02_quantize_int8.md 第 3 节） |
| 第一句识别延迟极大（10s+），后面正常 | 首次 OnnxRuntime 需要做算子 JIT，此外热启动会复用 | 是预期行为；生产环境建议在 splash 阶段后台预热 |
| 模型超过 200 MB，push 一半中断 | 无线调试带宽 / 设备 /sdcard/ 配额 | 改 USB 数据线 push；或 split 量化（先编 + push encoder 再 joiner） |
| 同一份模型推过去又被 SDK 拒了 | manifest.json 里 min_sdk_version 比当前 SDK 版本高 | 改 manifest 里的 min_sdk_version 到 SDK 当前版本以下，比如 1.0.0 |
