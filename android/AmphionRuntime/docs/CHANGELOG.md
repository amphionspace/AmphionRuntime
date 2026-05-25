# CHANGELOG

本 SDK 遵循 SemVer 2.0：MAJOR.MINOR.PATCH。

- MAJOR：公开 API 不向后兼容
- MINOR：新增公开 API 但保持向后兼容
- PATCH：仅 bug 修复，公开 API 与行为不变

## [Unreleased]

新增

- ModelDescriptor 与 LocalModel 增加可选字段 `lang: String?`，对应 manifest.json 的 `lang` 字段（约定值如 `zh-en` / `yue-en`）。`ModelManager.listLocal()` 会在扫目录时顺便解析 manifest 把 lang 填回去；manifest 缺少该字段或解析失败时为 null，不影响列出。
- Sample app 新增「中英 / 粤英」RadioGroup，按 manifest.lang 自动绑定对应模型；切换时自动 stop 当前监听 + close 旧 engine + 用对应 modelDir 重建。详见 [README.md](../README.md) 的快速开始与 [tools/asr/MODEL_LAYOUT.md](../../../tools/asr/MODEL_LAYOUT.md) 的「同时部署多语言模型」一节。
- 新增错误码 `MODEL_TYPE_MISMATCH (2005)`：在加载 zipformer transducer 之前 SDK 会扫 encoder ONNX 的 metadata 区段，校验 manifest.model_type 与模型实际结构（zipformer1 vs zipformer2）一致；不一致直接抛该错误码，避免 sherpa-onnx 走错 InitEncoder 路径找不到 metadata key 直接 native abort。同步更新 [shared/api-spec/errcodes.yaml](../../../shared/api-spec/errcodes.yaml) 与 iOS `AsrErrorCode.modelTypeMismatch`。
- 新增 SDK 公开 API `WeitnConfig` / `WeitnEngine`：封装我们 fork 的 sherpa-onnx 中 vendored 的 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)（Apache-2.0）中文 ITN 三段式 runtime（`tagger.fst → C++ token reorder → verbalizer.fst`），覆盖小数 / 单位 / 日期 / 时间 / 货币 / 百分比 / 电话号码 / 身份证号等场景。`normalize(text): String` 同步接口；构造期 native 加载失败抛 `IllegalStateException`（含 `MODEL_LOAD_FAILED` 错误码），调用期 native 抛出归一为 `AsrError(NATIVE_CRASH)` 走 `errorHandler` 回调，不向上传播。线程安全，`close()` 幂等。新增 5 条 `WeitnConfigTest` 覆盖 tagger / verbalizer 文件存在性校验。详见 [docs/INTEGRATION.md §12.4](INTEGRATION.md)。
- 新增 iOS 公开 API `WeitnConfig` / `WeitnEngine`（与 Android 对齐）；底层通过 Swift wrapper `SherpaOnnxWetextItnWrapper` 调 C-API；xcframework 由 `ios/AmphionRuntime/build_xcframework.sh` 一键产出后自动带 wetext。
- Sample app 新增 `WeitnAssetInstaller` 与 [tools/asr/00_push_weitn_fsts.sh](../../../tools/asr/00_push_weitn_fsts.sh)：脚本支持两种 fst 来源（本机 pip 编译 / 环境变量直拉预编译产物），push 到 external `asr-weitn-import/`，sample 启动时一次性搬到 internal `<filesDir>/asr-weitn/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}`。MainActivity 把 sw_itn 接管为 WeText 开关：fst + engine 双就绪后自动开一次；ASR final 出来后按 `WeitnEngine.normalize → PunctuationEngine.addPunctuation` 顺序异步刷 UI。
- 新增 SDK 公开 API `PunctuationConfig` / `PunctuationEngine`：封装 sherpa-onnx CT-Transformer 中英双语标点模型，提供 `addPunctuation(text): String` 同步接口；构造期 native 加载失败抛 `IllegalStateException`（含 `MODEL_LOAD_FAILED` 错误码），调用期 native 抛出归一为 `AsrError(NATIVE_CRASH)` 走 `errorHandler` 回调，不向上传播。线程安全，`close()` 幂等。新增 5 条 Builder 单测覆盖参数校验。详见 [docs/INTEGRATION.md §12.6](INTEGRATION.md)。
- Sample app 新增「标点 (CT-Transformer)」Switch：默认关，开启时异步加载 ~62 MB INT8 模型（~1 秒），关闭时立即释放 ~70 MB native 内存。final 文本先以无标点版立刻显示，标点 ~30 ms 后回来按行 id 替换；标点失败时静默回退。录音 / 切换中 Switch 灰禁。模型由 `tools/asr/00_push_punct_model.sh` 下载（cache + sha256 校验）+ adb push 到 external，sample 启动时 `PunctModelInstaller` 一次性搬到 internal `<filesDir>/asr-punct/`。详见 [README.md](../README.md) 的「可选：开启标点（CT-Transformer 中英双语）」与 [tools/asr/MODEL_LAYOUT.md §7](../../../tools/asr/MODEL_LAYOUT.md)。

Breaking

- 删除旧 ITN 入口 `AsrConfig.Builder.enableInverseTextNormalization(File)` / `enableInverseTextNormalization(List<File>)`，对应 `AsrConfig.itnRuleFstsPaths` 字段一并移除；iOS 端 `AsrConfig.enableInverseTextNormalization(ruleFsts:)` 与 `itnRuleFstsPaths` 同步移除。迁移到独立的 `WeitnEngine`（详见上面新增段落与 [docs/INTEGRATION.md §12.4](INTEGRATION.md)）。背景：旧 `itn_zh_number.fst`（k2-fsa/colab 单 fst，~25 KB）只覆盖一/二/.../九 的数字数词，无法处理「两点五八万」「幺三五七零八四」「二零二六年五月十五日」等真实业务高频 case；WeTextProcessing 业界 SOTA、社区活跃维护，体积代价（2-4 MB）由 native 路径走 adb push / CDN 拉取消化，APK 不增大。
- 同步删除 sample 端 `ItnPostprocess` / `ItnPostprocessTest` / `ItnAssetInstaller` / sample assets `asr-itn/` / `tools/asr/00_download_itn_fst.sh`：WeText ITN 内置了「幺/两 → 1/2」cardinal 规则，sample 侧的"幺补丁"逻辑不再需要。

兼容性

- 由于 lang 是带默认值的可选字段，Kotlin 调用方无需改动；Java 调用 `new LocalModel(...)` / `new ModelDescriptor(...)` 时若使用旧的位置构造器，需要补一个 `null` 参数（也可改用 `copy(lang = ...)`）。
- `MODEL_TYPE_MISMATCH (2005)` 是新增错误码，复用了 0.1.0 时已废弃的 2005 槽位（原 MODEL_CHECKSUM_FAILED 已重命名为 SHA256_MISMATCH (4003)，槽位空闲）。
- 仓库子模块 `third_party/sherpa-onnx` 当前指向我们的本地 `amphion-wetext` 分支，commit 基于上游 v1.13.1 + WeText vendor 改动。业务方接入时若需 mirror，请把 `amphion-wetext` 分支 push 到自家 fork 后修改 `.gitmodules` url；本仓库默认 url 仍指向上游 k2-fsa/sherpa-onnx，submodule update 后需手动切换到 amphion-wetext SHA。

## [0.1.0] - 2026-05

仓库拆分首版（在新 amphion-runtime 独立仓库内的第一个 tag）。

变更

- 全部 AsrErrorCode 常量与名称对齐 [shared/api-spec/errcodes.yaml](../../../shared/api-spec/errcodes.yaml)（与 iOS 完全一致）。常量重命名清单：
  - `INVALID_CONFIG (1001)` → `INVALID_ARGUMENT (1001)`
  - `INVALID_ARGUMENT (1002)` → `INVALID_SAMPLE_RATE (1002)`
  - 新增 `SDK_NOT_INITIALIZED (1003)`
  - `MODEL_DIR_NOT_FOUND (2001)` → `MODEL_DIR_INVALID (2001)`
  - `MANIFEST_PARSE_FAILED (2006)` → `MODEL_MANIFEST_PARSE_ERROR (2004)`
  - `SESSION_RELEASED (3001)` → `SESSION_ALREADY_CLOSED (3001)`
  - `SAMPLE_RATE_MISMATCH (3004)` → `SAMPLE_RATE_MISMATCH (3002)`
  - `NETWORK_FAILED (4001)` → `NETWORK_UNAVAILABLE (4001)`
  - `DOWNLOAD_TIMEOUT (4002)` → `DOWNLOAD_FAILED (4002)`
  - `MODEL_CHECKSUM_FAILED (2005)` → `SHA256_MISMATCH (4003)`
  - `PERMISSION_DENIED (5001)` → `IO_FAILED (5001)`
  - `STORAGE_FULL (5002)` → `STORAGE_INSUFFICIENT (5002)`
  - 删除：`MODEL_VERSION_MISMATCH (2004)`、`SESSION_NOT_STARTED (3002)`、`DOWNLOAD_CANCELLED (4003)`、`UNKNOWN (9999)`（取消下载等情况现归入 `DOWNLOAD_FAILED`）
- AsrConfig：manifest.json 中的 `decoding_method` 与 `max_active_paths` 字段会被 SDK 真正读取并应用，作为 Builder 默认值的覆盖；调用方显式调用 `.decodingMethod()` / `.maxActivePaths()` 仍优先生效（详见 INTEGRATION.md 第 7 节）。
- 加载时新增日志：tag AsrSdk 会打印 manifest overrides 以及 effective decoding method，便于现场排查。
- 仓库迁移：从 sherpa-onnx 主仓内的子目录迁移为独立仓库 amphion-runtime；sherpa-onnx 通过 third_party/sherpa-onnx submodule 引用，公司侧不再 patch sherpa-onnx 源码。

依赖

- sherpa-onnx v1.13.1（third_party/sherpa-onnx submodule pinned tag）
- ONNX Runtime 1.24.3
- AGP 8.4.0 / Gradle 8.6 / Kotlin 1.9.22
- minSdk 24 / targetSdk 34

新增

- 公开 API：AsrSdk / AsrConfig / AsrEngine / AsrSession / AsrCallback / AsrError / ModelManager / ModelDescriptor
- 流式中英混合识别（基于 streaming Zipformer Transducer，INT8 量化）
- 端点检测（sherpa-onnx 内置 endpointing）
- 热词支持（初始化时传一组词，提升业务领域识别率）
- 模型分发：HTTP 下载 + SHA256 校验 + 本地版本管理
- ProGuard / R8 友好（consumer-rules.pro 自动接管）
- Java 互操作性（公开 API 不使用 Kotlin-only 特性）
- ABI：arm64-v8a（默认），可选 armeabi-v7a

依赖

- sherpa-onnx v1.13.1
- ONNX Runtime 1.24.3
- AGP 8.4.0 / Gradle 8.6 / Kotlin 1.9.22
- minSdk 24 / targetSdk 34
