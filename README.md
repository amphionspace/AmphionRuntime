# sherpa-asr-sdk

公司内部 ASR SDK 工程，三端（Android / iOS / Linux 服务端）共享一份模型与 manifest 协议，底层流式识别基于 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)。

本仓库严格遵循"不修改 sherpa-onnx 任何源码"的原则：sherpa-onnx 通过 git submodule 引用上游 pinned tag（首期 v1.13.1），如需调整其行为，请向上游提交 PR 后再 bump submodule。

## 仓库布局

```
sherpa-asr-sdk/
├── README.md                    # 本文件
├── LICENSE                      # 完整 Apache 2.0 正文
├── NOTICE                       # 第三方依赖声明（含 sherpa-onnx 引用关系）
├── .gitmodules                  # third_party/sherpa-onnx -> v1.13.1
│
├── third_party/
│   └── sherpa-onnx/             # git submodule，detached @ v1.13.1，禁止本地修改
│
├── android/SherpaAsrSdk/        # Android SDK（AAR + Sample）
├── ios/SherpaAsrSdk/            # iOS SDK（SPM + CocoaPods）
├── server/asr-service/          # Linux gRPC 服务端
│
├── shared/
│   ├── api-spec/                # 错误码、manifest schema 等三端共享契约
│   ├── regression-set/          # 端到端回归集清单
│   └── docs/                    # 跨端文档（发布流程、dashboard 等）
│
├── tools/asr-sdk/               # 模型导出 / quantize / 编译 / 打包脚本
├── docs/                        # 仓库级文档（troubleshooting 等）
├── ci/                          # CI workflow 参考源（实际驱动在 .github/workflows）
└── .github/workflows/           # GitHub Actions 实际入口
```

## 快速开始（首次 clone）

```bash
# 一定要带 --recurse-submodules，否则 third_party/sherpa-onnx/ 是空的
git clone --recurse-submodules <内部 git url>/sherpa-asr-sdk.git
cd sherpa-asr-sdk

# 已有仓库忘了 --recurse-submodules：
git submodule update --init --recursive
```

各端编译入口：

| 端 | 入口 | 说明 |
| --- | --- | --- |
| Android | `bash tools/asr-sdk/04_build_android_so.sh arm64-v8a` 然后 `bash tools/asr-sdk/05_package_aar_libs.sh` 然后 `cd android/SherpaAsrSdk && ./gradlew :sdk:assembleRelease` | 详见 [android/SherpaAsrSdk/README.md](android/SherpaAsrSdk/README.md) |
| iOS | `bash ios/SherpaAsrSdk/build_xcframework.sh` | 详见 [ios/SherpaAsrSdk/README.md](ios/SherpaAsrSdk/README.md) |
| Server | `cmake -DSHERPA_ONNX_DIR=...` 详见 [server/asr-service/README.md](server/asr-service/README.md) | 需要先在 third_party/sherpa-onnx 内做 cxx-api install |

## 与 sherpa-onnx 的关系

- 上游源码：`third_party/sherpa-onnx/`，submodule 指针 detached 在 v1.13.1
- 公司侧绝对不在 submodule 内提交修改，所有补丁走上游
- Android / iOS 编译脚本会进入 `third_party/sherpa-onnx/` 调用上游 `build-android-*.sh` 和 `build-ios.sh`
- Server 端通过 `-DSHERPA_ONNX_DIR=<path-to-install>` 链接 sherpa-onnx 的 cxx-api 头文件与库
- Android Kotlin 桥接层：`android/SherpaAsrSdk/sdk/src/main/java/com/k2fsa/sherpa/onnx/*.kt` 是从上游 `android/SherpaOnnxAar/` 复制过来（保留上游 license header），由 [tools/asr-sdk/07_sync_kotlin_from_upstream.sh](tools/asr-sdk/07_sync_kotlin_from_upstream.sh) 与 submodule 保持一致

## 升级 sherpa-onnx 版本流程

```bash
cd third_party/sherpa-onnx
git fetch --tags
git checkout v1.14.0      # 或目标 tag
cd ../..
git add third_party/sherpa-onnx
bash tools/asr-sdk/07_sync_kotlin_from_upstream.sh   # 同步 Kotlin 桥接文件
# 三端跑回归 -> 提 PR
```

## 占位符

发版前必须替换为公司真实信息：

| 占位 | 含义 | 出现位置 |
| --- | --- | --- |
| com.yourco | Android Group ID / 包名 | gradle.properties、Kotlin package、AndroidManifest |
| YourCo | 公司名 | LICENSE、NOTICE 末尾、podspec author |
| your-internal-git | 内部 git 域名 | podspec、Package.swift |
| voice@your-org.example | 维护者邮箱 | podspec |
| REPLACE_ME | xcframework 二进制 sha256 | Package.swift、podspec |

替换步骤参考 [android/SherpaAsrSdk/README.md](android/SherpaAsrSdk/README.md) 末尾的"包名 / 坐标占位"小节。

## 版本号

整库版本号统一在 `0.1.0`（首版）。涉及位置：

- Android：[android/SherpaAsrSdk/gradle.properties](android/SherpaAsrSdk/gradle.properties) `ASR_SDK_VERSION`
- iOS：[ios/SherpaAsrSdk/Sources/SherpaAsrSdk/AsrSdk.swift](ios/SherpaAsrSdk/Sources/SherpaAsrSdk/AsrSdk.swift) `version` + [ios/SherpaAsrSdk/SherpaAsrSdk.podspec](ios/SherpaAsrSdk/SherpaAsrSdk.podspec) `s.version`
- 发布流程：[shared/docs/RELEASE_PROCESS.md](shared/docs/RELEASE_PROCESS.md)
