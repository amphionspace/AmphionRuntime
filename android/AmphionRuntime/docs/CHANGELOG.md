# CHANGELOG

本 SDK 遵循 SemVer 2.0：MAJOR.MINOR.PATCH。

- MAJOR：公开 API 不向后兼容
- MINOR：新增公开 API 但保持向后兼容
- PATCH：仅 bug 修复，公开 API 与行为不变

## [Unreleased]

修复

- 修复 `EngineImpl.close()` 与 `SessionImpl.feedAndDecode()` 之间的 race：旧路径下主线程调 `engine.close()` 后立即 `vad.release()`，但 decoder 线程上「正在执行」的 feedAndDecode 仍可能调用 `Vad.isSpeechDetected()`，拿到已释放的 native pointer 直接 SIGSEGV（fault addr 0x0）。现在 `EngineImpl.close()` 会在 release vad 前 join 所有 session 的 decoder thread（超时 500 ms），确保「当前 feedAndDecode」跑完才释放 vad。

新增

- VAD 真正接入流式管线：`SessionImpl.feedAndDecode` 现在在 ASR 之上叠加 silero VAD 的 Gate + 主动 endpoint，speech 之后尾静音 ≥ `VadConfig.activeEndpointSilenceMs`（默认 500 ms）即主动出 final，比 `EndpointRules.rule2MinTrailingSilenceSec` 的 1.4 秒更敏感，显著缓解长句子说一半不切分的现象。
- 公开 API `VadConfig` + `VadModelType`：业务方可调 VAD 阈值 / min / max speech duration / 主动 endpoint 静音阈值。`AsrConfig.Builder.vadConfig(VadConfig)` 入口。
- `VadModelType.TEN_VAD` 枚举位预留（当前 AAR 未打包资产，选择会抛 `UnsupportedOperationException`），方便未来切换。
- ASR bundle 新增 `bbpe.vocab`（sherpa-onnx ssentencepiece 库专用的「token + score」两列文本词表，zh-en / yue-en 各一份，单份约 230 KB）：modeling_unit=bbpe 路径必备文件，sherpa-onnx 用它把热词字符串切成 BPE token，决定 `AsrConfig.Builder.hotwords()` 是否命中。
- 新增脚本 `tools/asr/09_export_bbpe_vocab.py`：把 google SentencePiece protobuf `.model` 转成 ssentencepiece 期望的两列文本 `.vocab`；模型导出阶段一次性运行即可。

变更

- 0.1.x ~ 0.2.0 期间 `vad(true)` 实际只构造了 silero `Vad` 对象但没参与解码；本版本起 `vad(true)` 真的会改变识别行为。开关含义不变；如果不想要新的主动 endpoint 行为，把 `activeEndpointSilenceMs` 设为 0 即可退化成「只做 gate / 不主动切」。
- 热词 tokenization 由 `cjkchar` 切换到 `bbpe`：之前用 `cjkchar` 是因为缺词表，sherpa-onnx 把汉字按 UTF-8 char 拆，但模型本身是 byte-level BPE，多数热词 OOV 后被静默 skip；现在配合 `bbpe.vocab` 走 byte-level BPE，热词真正映射到模型 token，`hotwords()` + `hotwordsScore` 才有放大效果。开关 / API 不变，业务方代码不动。
- AAR 体积小幅增加（~460 KB），首次启动会重新解包 zh-en / yue-en 两份 `bbpe.vocab`（SDK_VERSION bump 到 0.2.2）。注意中间一版 0.2.1 误把 google SentencePiece protobuf `.model` 当词表直接打进 AAR，会让 ssentencepiece 解析 segfault；0.2.2 改用同源导出的 `.vocab` 文本格式，闪退修复。

## [0.2.0] - 2026-05

> 这是一次破坏性升级：API 表面减少 ~70%，全部模型整合进单个 AAR，业务方接入只剩 4 个公开类。

新增

- 顶层入口 `AmphionRuntime`：替代旧 `AsrSdk`，集 init / preInstall / create / version / release 于一体；调用方仅看到 4 个公开类即可完成全部接入。
- 公开 enum `AsrLanguage`：业务方在 `create(context, AsrLanguage.ZH_EN, config)` 时声明业务语言；不再暴露 modelId / version / model_type / decoding_method 等内部细节。
- SDK 内置全部模型：中英 ASR / 粤英 ASR / 标点 / 中文 ITN / VAD 5 类资产打进 AAR assets 的 `amphion-models/<bundle>/v1/` 下，`AssetInstaller` 在首次 create 或 preInstall 时一次性解到 internal storage。SDK 升级时按 `BuildConfig.SDK_VERSION` 重新解包，业务方代码无感。
- 内部 PostProcessor：在 ASR final 出来后串行做 ITN（仅 ZH_EN）→ 标点 → 单次 onFinal 派发，消除 0.1.x 时 sample 端「先出原文 → 异步替换」的 UI 抖动。
- 新增脚本 `tools/asr/08_pack_sdk_assets.sh`：把 5 类资产打进 SDK assets，缺失项自动调用 00_push_punct_model.sh / 00_push_weitn_fsts.sh 拉取。详见 `docs/DELIVERY.md`。
- 新增内部交付指南 `docs/DELIVERY.md`：从模型准备 → 打 AAR → 交付物清单 → 升级 SOP 的完整流程。
- 多语言预加载：`AmphionRuntime.preload(ctx, languages, config)` 一次性把多个语言的 OnlineRecognizer 加载到 SDK 内部 ASR 池；后续 `create(language)` 命中池 O(ms)、用户切换语言肉眼无感（先前每次切换需要 1~3 s 的同步加载）。共享 punct/itn 提到 `SharedPostProcessor` 单例（进程级一份），内存收益 ~80 MB；2 语言常驻 RSS ≤ 200 MB。详见 `docs/INTEGRATION.md` §11。
- 端侧标准指标：新增公开 data class `AmphionMetrics` + `AsrCallback.onMetrics(default no-op)`；每段话 onFinal 同帧派发 `kind=UTTERANCE`（含 utteranceE2eLatencyMs / firstPartialLatencyMs / decodeDurationMs / postProcessMs / rtf / nativeRssMb 等），engine close 派发 `kind=SESSION`（含 totalUtterances / avgRtf / p95Rtf / peakNativeRssMb）。指标同时通过 logcat tag `AmphionMetrics` KV 行输出，方便 `adb logcat -s AmphionMetrics` 直接拉取；schema 与未来鸿蒙端共用。详见 `docs/INTEGRATION.md` §12。

Breaking

- 删除公开类型：`AsrSdk` / `AsrSdkOptions` / `AsrLogLevel` / `ModelManager` / `ModelDescriptor` / `ModelFile` / `LocalModel` / `ModelDownloadCallback` / `ModelType` / `DecodingMethod` / `PunctuationConfig` / `PunctuationEngine` / `WeitnConfig` / `WeitnEngine`。后六者作为内部实现（`com.amphion.asr.internal.*`）保留；其它已经无对应概念。
- `AsrSdk.init/release/version` → `AmphionRuntime.init/release/version`；`AsrSdkOptions` → `AmphionOptions`；`AsrLogLevel` → `AmphionLogLevel`。
- `AsrConfig` 重写：删除全部模型路径字段（`modelDir` / `vadModelPath` / `homophoneLexiconPath` / `homophoneRuleFstsPath` / `lmModelPath` / `sampleRate` / `featureDim` / `decodingMethod` / `maxActivePaths`），新增 `punctuation` / `itn` / `vad` 三个 boolean 开关。`enableEndpoint` 重命名为 `endpoint`。
- `AsrSession.acceptPcmShort(samples, sampleRate)` / `acceptPcmFloat(samples, sampleRate)` → `acceptPcmShort(samples)` / `acceptPcmFloat(samples)`。SDK 锁定 16 kHz；不再接受其他采样率，业务方需自行重采样。
- `AsrCallback.onFinal(text, confidence)` 现在是后处理后的最终文本（已含 ITN + 标点），单段话只触发一次。0.1.x 时序「先出原文 final → 业务侧异步加 ITN/标点」整套被 SDK 内部接管。
- `AsrEngine` 构造器改为 `internal`；只能通过 `AmphionRuntime.create` 拿实例。
- 错误码全面精简（含义/编号都重新对齐）：
  - 1xxx 调用约定：`INVALID_ARGUMENT (1001)` / `SDK_NOT_INITIALIZED (1002)` / `SESSION_ALREADY_CLOSED (1003)`
  - 2xxx 资源：`LANGUAGE_UNAVAILABLE (2001)` / `ASSET_INSTALL_FAILED (2002)` / `STORAGE_INSUFFICIENT (2003)`
  - 3xxx 运行时：`DECODE_FAILED (3001)` / `POSTPROCESS_FAILED (3002)`
  - 9xxx native 兜底：`NATIVE_CRASH (9001)`
  - 删除：`INVALID_SAMPLE_RATE (1002)`、`MODEL_DIR_INVALID (2001)`、`MODEL_FILE_MISSING (2002)`、`MODEL_LOAD_FAILED (2003)`、`MODEL_MANIFEST_PARSE_ERROR (2004)`、`MODEL_TYPE_MISMATCH (2005)`、`SAMPLE_RATE_MISMATCH (3002)`、`NETWORK_UNAVAILABLE (4001)`、`DOWNLOAD_FAILED (4002)`、`SHA256_MISMATCH (4003)`、`IO_FAILED (5001)`
- SDK AndroidManifest 不再建议业务方声明 `INTERNET` / `ACCESS_NETWORK_STATE`：0.2.0 不发起任何网络请求。
- Sample app：删除 LandingActivity / EvalActivity / RecordSentenceActivity 等评估模式 + 相关资源；MainActivity 改为唯一 LAUNCHER，按住说话 + 中英/粤英切换。

兼容性

- AAR 体积从 ~30 MB 涨到 ~280 MB（包含全部模型），首次启动会有 5-30s 解包；详见 `docs/INTEGRATION.md` §10。
- SDK_VERSION 用作 `<filesDir>/amphion-runtime/install.flag` 的标识；SDK 版本变更会自动重新解包。
- Java 客户依旧能直接用所有公开 API（`@JvmStatic` / `@JvmOverloads` 已添加）。

依赖

- sherpa-onnx v1.13.1（third_party/sherpa-onnx submodule pinned tag）
- ONNX Runtime 1.24.3
- AGP 8.4.0 / Gradle 8.6 / Kotlin 1.9.22
- minSdk 24 / targetSdk 34

## [0.1.1-rc] - 2026-05 (撤回；0.2.0 直接超过本版)

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
