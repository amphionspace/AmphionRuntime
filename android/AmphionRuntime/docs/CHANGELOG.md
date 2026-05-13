# CHANGELOG

本 SDK 遵循 SemVer 2.0：MAJOR.MINOR.PATCH。

- MAJOR：公开 API 不向后兼容
- MINOR：新增公开 API 但保持向后兼容
- PATCH：仅 bug 修复，公开 API 与行为不变

## [Unreleased]

(见 0.1.0)

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
