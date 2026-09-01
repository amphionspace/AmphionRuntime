## 跨端 CI

本目录是 AmphionRuntime 工程链路的 CI/CD 编排集合（首期覆盖 ASR），目标：

- 每个端（android / ios / server）有一份独立 workflow，独立失败定位
- 共用 [shared/regression-set/](../shared/regression-set/) 做端到端烟测；识别正确性（WER / CER）由上游 sherpa-onnx 的 `scripts/benchmark/`（位于 `third_party/sherpa-onnx/scripts/benchmark/`）统一出报告，下游 CI 不再重复计算
- artifact 命名遵循 `<sdk>-<version>-<git-sha>.<ext>`，便于灰度发布

注意：ci/ 下的 yml 是“参考源”，真正驱动 GitHub Actions 的拷贝在 `.github/workflows/`，并且每个 actions/checkout 都加了 `with: submodules: recursive`，否则 third_party/sherpa-onnx 不会被拉下来，跨编译入口都会失败。

## 工作流清单

| 文件 | 端 | 触发 | 主要产物 |
| --- | --- | --- | --- |
| [android.yml](android.yml) | Android SDK | push / PR / tag v\* | sdk-release.aar |
| [ios.yml](ios.yml) | iOS SDK contract | push / PR | 参数覆盖、纯 Swift 状态机 typecheck、源码语法与组包脚本检查；XCFramework 发布构建单独执行 |
| server.yml | Linux 服务端 | TODO Phase 4 | docker image |
| [dashboard.yml](dashboard.yml) | 跨端 | 月度 cron / 手动 | trends/reports/YYYY-MM.md + trends/\*.csv |

## 复制到目标 CI 平台

仓库中的 yml 默认按 GitHub Actions 编写。如果公司用 GitLab CI / Jenkins，注意以下差异：

- secrets：`secrets.MAVEN_USERNAME` / `secrets.MAVEN_PASSWORD` 在 GitLab 里改用 `$MAVEN_USERNAME`
- artifact：GitLab 用 `artifacts.paths`，Jenkins 用 `archiveArtifacts`
- matrix：GitLab 用 `parallel.matrix`

## 关键约定

1. NDK 必须用 r26d (26.3.11579264)，与 [asr/tools/ANDROID_TOOLCHAIN.md](../asr/tools/ANDROID_TOOLCHAIN.md) 对齐
2. CI 拉模型走公司内网 OSS：env `MODEL_OSS_URL`，CI 任务自己 export 后调 `asr/tools/00_fetch_demo_model.sh` 之类脚本
3. 识别正确性（WER / CER）由上游 sherpa-onnx `scripts/benchmark/`（路径：`third_party/sherpa-onnx/scripts/benchmark/`）统一出报告；下游 dashboard 通过 `--upstream-wer-report-url` 引用上游 URL，不重复跑
