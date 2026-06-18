# AmphionRuntime

AmphionRuntime 是 Amphion 端侧语音运行时（Android / iOS / Linux 服务端三端通用）。当前首期覆盖 ASR，未来在同一套模型 manifest / 三端桥接 / 发布流程下扩展 TTS / VAD / 声纹等其它任务。底层推理引擎基于 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)。

本仓库严格遵循"不修改 sherpa-onnx 任何源码"的原则：sherpa-onnx 通过 git submodule 引用上游 pinned tag（首期 v1.13.1），如需调整其行为，请向上游提交 PR 后再 bump submodule。

## 仓库布局

```
amphion-runtime/
├── README.md                    # 本文件
├── LICENSE                      # 完整 Apache 2.0 正文
├── NOTICE                       # 第三方依赖声明（含 sherpa-onnx 引用关系）
├── .gitmodules                  # third_party/sherpa-onnx -> v1.13.1
│
├── third_party/
│   └── sherpa-onnx/             # git submodule，detached @ v1.13.1，禁止本地修改
│
├── android/AmphionRuntime/      # Android ASR SDK（AAR + Sample + police/dingqiao）
├── android/TtsRuntime/          # Android TTS SDK（AAR + Sample，独立 Gradle root）
├── ios/AmphionRuntime/          # iOS SDK（SPM + CocoaPods）
├── server/asr-service/          # Linux gRPC 服务端（ASR 任务；TTS 服务未来在同级 server/tts-service/）
│
├── shared/
│   ├── api-spec/                # 错误码、manifest schema 等三端共享契约
│   ├── regression-set/          # 端到端回归集清单
│   └── docs/                    # 跨端文档（发布流程、dashboard 等）
│
├── tools/asr/                   # ASR 任务的模型导出 / quantize / 编译 / 打包脚本
├── tools/tts/                   # TTS 任务的模型校验 / license / Android 交付脚本
├── docs/                        # 仓库级文档（troubleshooting 等）
├── ci/                          # CI workflow 参考源（实际驱动在 .github/workflows）
└── .github/workflows/           # GitHub Actions 实际入口
```

## 快速开始（首次 clone）

```bash
# 一定要带 --recurse-submodules，否则 third_party/sherpa-onnx/ 是空的
git clone --recurse-submodules <内部 git url>/amphion-runtime.git
cd amphion-runtime

# 已有仓库忘了 --recurse-submodules：
git submodule update --init --recursive
```

各端编译入口：

| 端 | 入口 | 说明 |
| --- | --- | --- |
| Android ASR | `bash tools/asr/04_build_android_so.sh arm64-v8a` 然后 `bash tools/asr/05_package_aar_libs.sh` 然后 `cd android/AmphionRuntime && ./gradlew :sdk:assembleRelease` | 详见 [android/AmphionRuntime/README.md](android/AmphionRuntime/README.md) |
| Android TTS | `cd android/TtsRuntime && ./gradlew :sdk:assembleRelease :sample:assembleDebug` | 详见 [android/TtsRuntime/README.md](android/TtsRuntime/README.md) |
| iOS | `bash ios/AmphionRuntime/build_xcframework.sh` | 详见 [ios/AmphionRuntime/README.md](ios/AmphionRuntime/README.md) |
| Server | `cmake -DSHERPA_ONNX_DIR=...` 详见 [server/asr-service/README.md](server/asr-service/README.md) | 需要先在 third_party/sherpa-onnx 内做 cxx-api install |

## 与 sherpa-onnx 的关系

- 上游源码：`third_party/sherpa-onnx/`，submodule 指针 detached 在 v1.13.1
- 公司侧绝对不在 submodule 内提交修改，所有补丁走上游
- Android / iOS 编译脚本会进入 `third_party/sherpa-onnx/` 调用上游 `build-android-*.sh` 和 `build-ios.sh`
- Server 端通过 `-DSHERPA_ONNX_DIR=<path-to-install>` 链接 sherpa-onnx 的 cxx-api 头文件与库
- Android Kotlin 桥接层：`android/AmphionRuntime/sdk/src/main/java/com/k2fsa/sherpa/onnx/*.kt` 是从上游 `android/SherpaOnnxAar/` 复制过来（保留上游 license header），由 [tools/asr/07_sync_kotlin_from_upstream.sh](tools/asr/07_sync_kotlin_from_upstream.sh) 与 submodule 保持一致

## 升级 sherpa-onnx 版本流程

```bash
cd third_party/sherpa-onnx
git fetch --tags
git checkout v1.14.0      # 或目标 tag
cd ../..
git add third_party/sherpa-onnx
bash tools/asr/07_sync_kotlin_from_upstream.sh   # 同步 Kotlin 桥接文件
# 三端跑回归 -> 提 PR
```

## 占位符

发版前还需要替换的真实信息（公司品牌相关已经固化为 Amphion / com.amphion）：

| 占位 | 含义 | 出现位置 |
| --- | --- | --- |
| your-internal-git | 内部 git 域名 | podspec、Package.swift |
| your-cdn.example.com | xcframework / 模型 CDN 主机 | podspec、Package.swift、tools/asr/*.sh、demo manifest |
| your.git.host | iOS SPM url 示例 | ios/AmphionRuntime/README.md |
| voice@amphion.example | 维护者邮箱（.example 仍是占位） | podspec、Helm Chart |
| REPLACE_ME | xcframework 二进制 sha256 | Package.swift、podspec |

替换步骤参考 [android/AmphionRuntime/README.md](android/AmphionRuntime/README.md) 末尾的"包名 / 坐标占位"小节。

## 版本号

整库版本号统一在 `0.1.0`（首版）。涉及位置：

- Android：[android/AmphionRuntime/gradle.properties](android/AmphionRuntime/gradle.properties) `AMPHION_RUNTIME_VERSION`
- iOS：[ios/AmphionRuntime/Sources/AmphionRuntime/AsrSdk.swift](ios/AmphionRuntime/Sources/AmphionRuntime/AsrSdk.swift) `version` + [ios/AmphionRuntime/AmphionRuntime.podspec](ios/AmphionRuntime/AmphionRuntime.podspec) `s.version`
- 发布流程：[shared/docs/RELEASE_PROCESS.md](shared/docs/RELEASE_PROCESS.md)
