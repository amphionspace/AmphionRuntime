# AmphionRuntime

基于 sherpa-onnx 的 AmphionRuntime 工程。

包含两个 Gradle 模块：

| 模块 | 类型 | 说明 |
| --- | --- | --- |
| `:sdk` | Android Library (AAR) | 对外发布的 SDK；包名 `com.amphion.asr` |
| `:sample` | Android Application (APK) | 单 Activity 示例：按住说话 → partial / final |

## 快速开始

零基础完整端到端走一遍，请看 `tools/asr/QUICKSTART.md`（含 NDK / brew / cmake / 无线调试 / 模型 push 全链路）。下面假设你已经装好工具链且已用 04/05 脚本编出了 .so：

```bash
# 0) 工具链与 .so 编译（首次必须）
#    - 安装：tools/asr/ANDROID_TOOLCHAIN.md
#    - 编 .so：bash tools/asr/04_build_android_so.sh arm64-v8a
#    - 拷 .so：bash tools/asr/05_package_aar_libs.sh

# 1) 第一次：初始化 Gradle wrapper（从官方 SherpaOnnxAar 复制 gradlew/gradle-wrapper.jar）
bash init_gradle_wrapper.sh

# 2) 让 AGP 找到 Android SDK，二选一即可（推荐 A）：
#    A. 在本目录创建 local.properties
cat > local.properties <<EOF
sdk.dir=$HOME/Library/Android/sdk
EOF
#    B. 或者 export 一个永久环境变量（写到 ~/.zprofile）：
#       export ANDROID_HOME="$HOME/Library/Android/sdk"
#       export ANDROID_SDK_ROOT="$ANDROID_HOME"
# 注：local.properties 不应提交到 git；本工程的 .gitignore 已经排除。

# 3) 构建 SDK（AAR 输出在 sdk/build/outputs/aar/sdk-release.aar）
./gradlew :sdk:assembleRelease

# 4) 发布到本地 Maven（产出 com.amphion:amphion-runtime:0.1.0）
./gradlew :sdk:publishReleasePublicationToLocalFileRepoRepository

# 5) 生成 API 文档
./gradlew :sdk:dokkaHtml
# 文档入口：sdk/build/dokka/html/index.html

# 6) 装 sample 验证
./gradlew :sample:installDebug

# 7) push demo 模型并启动 app
bash ../../tools/asr/00_fetch_demo_model.sh push
adb shell am force-stop com.amphion.asr.sample
adb shell am start -n com.amphion.asr.sample/.MainActivity
```

如果你想在 sample 上同时验证「中英 / 粤英」两个模型（顶部 RadioGroup 切换），把仓库内的两份 demo 模型分别 push 上去即可（每条命令对应一个 model_id；SDK 按 manifest.lang 自动归类）：

```bash
# 中英
bash ../../tools/asr/00_push_my_model.sh \
  --src ../../tools/asr/demo-model/zipformer_L_zh_en \
  --id  amphion-zh-en-streaming_large_crctc_full_lid_musan_traffic_v3_fix \
  --version 1.0.0-iter-140000-avg-1-chunk-32-left-256

# 粤英
bash ../../tools/asr/00_push_my_model.sh \
  --src ../../tools/asr/demo-model/zipformer_L_yue_en \
  --id  amphion-yue-en-streaming_large_crctc_lid_musan_traffic_v5_fix \
  --version 1.0.0-iter-100000-avg-1-chunk-32-left-256

adb shell am force-stop com.amphion.asr.sample
adb shell am start -n com.amphion.asr.sample/.MainActivity
```

切换前提：每份 manifest.json 含 `"lang": "zh-en"` 或 `"lang": "yue-en"`；缺失的话对应 RadioButton 会灰掉，并在状态栏提示。

### 可选：开启 WeText ITN（中文小数/单位/日期/货币）

Sample 的 lang 切换行下方有一个「WeText ITN」Switch，开启后会用我们 fork 的 sherpa-onnx 里 vendored 的 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)（Apache-2.0）三段式 runtime 把口语化中文正规化为书面化中文，覆盖小数、单位、日期、时间、货币、百分比、电话号码、身份证号等场景：

```
两点五八万        -> 2.58万
幺三五七零八四    -> 1357084
二零二六年五月十五日 -> 2026年5月15日
三点五公里        -> 3.5公里
```

SDK 入口是独立的 `WeitnEngine`（详见 [docs/INTEGRATION.md §12.4](docs/INTEGRATION.md)），跟 ASR engine 完全解耦：业务方按需 lazy 创建，错误回退到原文，关闭后立即释放 native FST 内存。

#### 一次性 push WeText fst

WeText 中文 ITN 由 `zh_itn_tagger.fst` + `zh_itn_verbalizer.fst` 两份文件组成，总和约 2–4 MB；不打进 APK，走 adb push（跟标点模型同款模式）：

```bash
# 自动 pip install WeTextProcessing 并编 fst（首次会 conda/pip 装 pynini，需要数分钟）
bash ../../tools/asr/00_push_weitn_fsts.sh

# 多设备 / fork 改包名 / 只编不 push（同 punct 脚本）：
bash ../../tools/asr/00_push_weitn_fsts.sh --serial <adb-serial>
bash ../../tools/asr/00_push_weitn_fsts.sh --pkg com.example.fork.asr
bash ../../tools/asr/00_push_weitn_fsts.sh --no-push

# 或：直接从公司内部 CDN 拉预编译产物（推荐生产环境）
WEITN_TAGGER_URL=https://your-cdn.example.com/weitn/zh_itn_tagger.fst \
WEITN_VERBALIZER_URL=https://your-cdn.example.com/weitn/zh_itn_verbalizer.fst \
WEITN_TAGGER_SHA256=... WEITN_VERBALIZER_SHA256=... \
  bash ../../tools/asr/00_push_weitn_fsts.sh
```

脚本会把 fst 缓存到 `tools/asr/weitn-fsts/`（git 忽略）；push 到 `/sdcard/Android/data/<pkg>/files/asr-weitn-import/`。sample 启动时 `WeitnAssetInstaller` 会一次性搬到 `<filesDir>/asr-weitn/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}`。

#### 运行时表现

- Switch 默认关；fst + ASR engine 双就绪后由 sample 自动开一次（节流；失败也不再重试）
- 关闭 Switch 立即 `WeitnEngine.close()` 释放数 MB native FST 内存
- 录音中 Switch 灰禁，避免会话活跃时关 native；本段录音结束后自动恢复
- ITN 与标点可以同时开：先做 WeText ITN → 再做标点；ASR final 显示用户能看到「先原文 → ITN 替换 → 再加标点」的两次轻微闪烁，但不会阻塞下一段语音的 partial
- fst 未 push 时 Switch 永远灰禁，但 ASR + 标点主功能不受影响

#### 装机验证清单

| 朗读内容 | 期望显示（ITN on） |
| --- | --- |
| 两点五八万 | 2.58万 |
| 幺三五七零八四 | 1357084 |
| 二零二六年五月十五日 | 2026年5月15日 |
| 三点五公里 | 3.5公里 |
| 三百块钱 | 300块钱 |
| 百分之七十五 | 75% |

logcat 关键字（按重要性）：

- `WeitnEngine loaded tagger=... verbalizer=...` —— fst 加载成功
- `WeitnEngine error: <CODE> <message>` / `WeitnEngine error: MODEL_LOAD_FAILED` —— 加载或 normalize 期间出错
- `MainActivity` 里 `installWeitnAsync` 输出 —— sample 端的 WeitnAssetInstaller 状态

若朗读后 UI 没有任何 ITN 效果：

1. 看 logcat 是否有 `WeitnEngine error: MODEL_LOAD_FAILED`，多半是 push 上去的 fst 文件名前缀错（WeText runtime 按 `zh_itn_` / `zh_tn_` 前缀决定 ParseType），需检查 tagger 文件名包含 `zh_itn_`
2. 看 sample 的 `WeitnAssetInstaller` 是否报错（external 路径找不到 fst → push 步骤没跑或者 sample 包名不一致）
3. 长按 sample 标题栏的「dump」按钮，从 `<filesDir>/asr-debug/<ts>/transcript.txt` 取 SDK 原始输出与 ITN 输出对比

### 可选：开启标点（CT-Transformer 中英双语）

Sample 的 ITN 行下方还有一个「标点 (CT-Transformer)」Switch，开启后会用 sherpa-onnx 官方 `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8` 模型给 final 文本加上「，。？」。底层走 SDK 公开 API `PunctuationEngine`（详见 [docs/INTEGRATION.md §12.6](docs/INTEGRATION.md)）。

#### 一次性 push 标点模型

模型 ~62 MB INT8，不打进 APK，走 adb push（仿照 ASR 模型的工程习惯）：

```bash
bash ../../tools/asr/00_push_punct_model.sh           # 下载 + push 到默认 sample 包
# 多设备时：
bash ../../tools/asr/00_push_punct_model.sh --serial <adb-serial>
# 改了 applicationId 的 fork：
bash ../../tools/asr/00_push_punct_model.sh --pkg com.example.fork.asr
# 只下载到本地 cache 不动设备：
bash ../../tools/asr/00_push_punct_model.sh --no-push
```

脚本会把 tarball 缓存到 `tools/asr/punct-model/`（git 忽略），同时校验 tarball 与解压后 `model.int8.onnx` 两层 sha256；push 到 `/sdcard/Android/data/<pkg>/files/asr-punct-import/model.int8.onnx`。sample 启动时 `PunctModelInstaller` 会一次性搬到 `<filesDir>/asr-punct/model.int8.onnx`（之后即使外部目录被清空，模型仍常驻 internal 直到 app 被卸载或手动清理）。

#### 运行时表现

- Switch 默认关。开启时异步加载标点模型（~1 秒），过程中按钮短暂灰禁、状态栏提示「加载标点模型…」
- 加载完成后状态栏切换为「模型就绪（中英）… 已启用标点」
- 关闭 Switch 会立即 `PunctuationEngine.close()` 释放 ~70 MB native 内存
- 录音中 Switch 灰禁，避免会话活跃时关 native；本段录音结束后自动恢复
- 标点推理在专用单线程 `amphion-punct` 上跑，每段 final 大约 20-100 ms。先把无标点的 final 直接显示在 UI，标点回来后**替换**原行（用户能看到"先出文字、再补标点"的轻微闪烁，但不会阻塞下一段语音的 partial 显示）
- ITN 与标点可以同时开：先做 WeText ITN → 再做标点（详见上面 WeText ITN 章节）
- 标点模型未 push 时 Switch 永远灰禁，但 ASR + ITN 主功能不受影响

如果 step 6 报 `more than one device/emulator`：

```bash
adb devices                                     # 找到目标真机的 serial
export ANDROID_SERIAL=<真机 serial>             # 之后 gradle install / adb 都默认走这台
./gradlew :sample:installDebug
```

## 目录布局

```
AmphionRuntime/
├── README.md                   # 本文件
├── LICENSE                     # 自有 SDK 协议（Apache 2.0 模板）
├── NOTICE                      # 第三方依赖声明（sherpa-onnx / onnxruntime / silero-vad / ...）
├── settings.gradle.kts         # 根 settings：include sdk + sample
├── build.gradle.kts            # 根 build：仅声明 plugin 版本
├── gradle.properties           # 全局属性 + SDK 坐标（GROUP/ARTIFACT/VERSION）
├── gradle/
│   ├── libs.versions.toml      # 版本目录（AGP/Kotlin/Dokka/AndroidX 等）
│   └── wrapper/gradle-wrapper.properties
├── init_gradle_wrapper.sh      # 一次性脚本：从 SherpaOnnxAar 复制 gradlew + wrapper jar
│
├── sdk/                        # SDK 模块
│   ├── build.gradle.kts        # AAR + Dokka + maven-publish
│   ├── consumer-rules.pro      # 客户开混淆时自动应用的规则
│   ├── proguard-rules.pro      # 开发态混淆规则（include consumer-rules.pro）
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── jniLibs/<abi>/      # 由 tools/asr/05_package_aar_libs.sh 填充
│       └── java/
│           ├── com/k2fsa/sherpa/onnx/    # 来自 sherpa-onnx 上游（保留 license header）
│           │   ├── OnlineRecognizer.kt
│           │   ├── OnlineStream.kt
│           │   ├── Vad.kt
│           │   ├── FeatureConfig.kt
│           │   └── HomophoneReplacerConfig.kt
│           └── com/amphion/asr/          # AmphionRuntime ASR 的公开 API
│               ├── AsrSdk.kt
│               ├── AsrConfig.kt
│               ├── AsrEngine.kt
│               ├── AsrSession.kt
│               ├── AsrCallback.kt
│               ├── AsrError.kt
│               ├── ModelManager.kt
│               ├── ModelDescriptor.kt
│               └── internal/             # 内部实现（不暴露给客户、不进 Dokka）
│                   ├── Logger.kt
│                   ├── EngineImpl.kt
│                   ├── SessionImpl.kt
│                   ├── ModelDownloader.kt
│                   └── Sha256Verifier.kt
│
├── sample/                     # Sample App
│   ├── build.gradle.kts
│   ├── proguard-rules.pro
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/amphion/asr/sample/
│       │   ├── MainActivity.kt
│       │   └── AudioRecorder.kt
│       └── res/
│           ├── layout/activity_main.xml
│           └── values/strings.xml
│
└── docs/
    ├── INTEGRATION.md          # 集成文档（中文，给客户看）
    ├── PRIVACY.md              # 隐私合规说明
    ├── CHANGELOG.md
    └── API_DOC_BUILD.md        # 如何生成 Dokka HTML 文档
```

## 包名 / 坐标改名（下游 fork 用）

仓库默认坐标是 `com.amphion:amphion-runtime:0.1.0`，包名 `com.amphion.asr`。如果你的团队 fork 出去要换成自己的命名空间，用脚本一键替换：

```bash
# 在仓库根目录执行
bash tools/asr/06_rename_namespace.sh --group-id com.<your-org>
# 默认 pkg-prefix = <group-id>.asr，需要自定义则带 --pkg-prefix com.<your-org>.xxx
```

脚本会处理：

- `gradle.properties` 中 `AMPHION_RUNTIME_GROUP_ID`
- `sdk/` 与 `sample/` 下所有 `*.kt` / `AndroidManifest.xml` / `build.gradle.kts` / `*.pro` 中的 `com.amphion.asr` 字面量
- 物理目录 `sdk/src/main/java/com/amphion/asr/` → `<new-pkg-path>/`

它不会动 `NOTICE` / `LICENSE` / `docs/PRIVACY.md` 里的 `Amphion` 公司名——这些请手工替换为你公司的法定全称。

## 与上游 sherpa-onnx 的关系

本 SDK 锁定 sherpa-onnx tag `v1.13.1`，并在两个层面复用其代码：

1. native 层（运行时）：`libsherpa-onnx-jni.so` + `libonnxruntime.so`，由
   `tools/asr/04_build_android_so.sh` 在 `sherpa-onnx` 仓库根目录执行 NDK 交叉编译产生。
2. Kotlin 层（编译时）：`com.k2fsa.sherpa.onnx.*` 的 5 个 Kotlin 文件（OnlineRecognizer / OnlineStream / Vad / FeatureConfig / HomophoneReplacerConfig），保留上游 Apache-2.0 license header。

我们自己的 SDK 公开 API 全部位于 `com.amphion.asr.*`，把上游 API 完全隐藏，对外只暴露 8 个公开类型。

## 关键开发约束

- 公开 API 只允许 `class` / `interface` / `data class` / `enum class` / `object`，不使用 inline value class、context receivers、suspend fun 等 Kotlin-only 特性
- 所有公开方法 / 类必须有 KDoc
- 公开 API 修改需要同步：consumer-rules.pro / INTEGRATION.md / CHANGELOG.md
- native crash 必须被捕获并归一为错误码 9001，绝不让 Throwable 透传给业务方
- 一切 IO / 阻塞操作都不允许在主线程执行（SDK 不主动占用主线程）
