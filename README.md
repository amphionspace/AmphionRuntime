# AmphionRuntime

AmphionRuntime 是 Amphion 端侧与服务端语音运行时仓库。仓库按能力纵切组织，当前覆盖 ASR、TTS、鼎桥客户交付工程，以及 ASR WebSocket 服务。底层推理引擎基于 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)。

本仓库严格遵循"不修改 sherpa-onnx 任何源码"的原则：sherpa-onnx 通过 git submodule 引用上游 pinned tag（首期 v1.13.1），如需调整其行为，请向上游提交 PR 后再 bump submodule。

## 仓库布局

```
amphion-runtime/
├── README.md                    # 本文件
├── LICENSE                      # 完整 Apache 2.0 正文
├── NOTICE                       # 第三方依赖声明（含 sherpa-onnx 引用关系）
├── .gitmodules                  # third_party/sherpa-onnx -> v1.13.1
│
├── asr/                         # ASR 能力纵切
│   ├── android/                 # Android ASR SDK（AAR + Sample + police/dingqiao）
│   ├── harmony/                 # HarmonyOS ASR HAR（amphion_asr / amphion_police / amphion_dingqiao）
│   ├── ios/                     # iOS SDK（SPM + CocoaPods）
│   ├── server/                  # Linux 原生服务端
│   ├── ws-server/               # Python WebSocket 流式 ASR 服务
│   └── tools/                   # 模型导出 / 量化 / 编译 / 打包 / target speaker 调研工具
│
├── tts/                         # TTS 能力纵切
│   ├── android/                 # Android TTS SDK（AAR + Sample，独立 Gradle root）
│   ├── harmony/                 # HarmonyOS TTS HAR
│   └── tools/                   # 模型校验 / license / 交付脚本
│
├── delivery/
│   └── harmony-dingqiao/        # 鼎桥 HarmonyOS ASR+TTS 客户交付聚合层
│
├── third_party/
│   └── sherpa-onnx/             # git submodule，detached @ v1.13.1，禁止本地修改
│
├── shared/
│   ├── api-spec/                # 错误码、manifest schema 等三端共享契约
│   ├── regression-set/          # 端到端回归集清单
│   └── docs/                    # 跨端文档（发布流程、dashboard 等）
│
├── docs/                        # 仓库级文档（troubleshooting 等）
├── ci/                          # CI workflow 参考源（实际驱动在 .github/workflows）
└── .github/workflows/           # GitHub Actions 实际入口
```

## 文档组织

先看根 README 了解仓库入口，再按任务进入对应文档：

| 场景 | 入口 |
| --- | --- |
| 文档索引与组织规则 | [docs/README.md](docs/README.md) |
| Android ASR SDK 构建与集成 | [asr/android/README.md](asr/android/README.md) |
| HarmonyOS ASR SDK | [asr/harmony/README.md](asr/harmony/README.md) |
| ASR WebSocket 服务 | [asr/ws-server/README.md](asr/ws-server/README.md) |
| Android TTS SDK | [tts/android/README.md](tts/android/README.md) |
| HarmonyOS TTS SDK | [tts/harmony/docs/BUILD.md](tts/harmony/docs/BUILD.md) |
| 鼎桥 Android 客户接口契约 | [asr/android/docs/customer/语音识别SDK接口-交付批注版.md](asr/android/docs/customer/语音识别SDK接口-交付批注版.md) |
| 鼎桥 HarmonyOS 交付聚合层 | [delivery/harmony-dingqiao/README.md](delivery/harmony-dingqiao/README.md) |
| 客户交付包验收规则 | [docs/delivery-zip-verification.md](docs/delivery-zip-verification.md) |

文档分层原则：

- 根 `README.md` 只放仓库总览、模块入口和首次构建提示。
- 模块 `README.md` 说明该模块如何构建、运行和集成。
- `docs/` 放跨模块工程经验、排障、交付流程和文档组织说明。
- 客户可见文档放在模块或交付目录的 `docs/customer/` 下；不得暴露内部路径、密钥、私钥、客户 SN 或 `.secure/` 内容。
- 自动生成的报告放在 `reports/` 目录下，默认不作为接口契约来源。

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
| Android ASR | `bash asr/tools/04_build_android_so.sh arm64-v8a` 然后 `bash asr/tools/05_package_aar_libs.sh` 然后 `cd asr/android && ./gradlew :sdk:assembleRelease` | 详见 [asr/android/README.md](asr/android/README.md) |
| HarmonyOS ASR | `bash asr/tools/04_build_harmony_so.sh` 然后 `bash asr/tools/05_package_har_libs.sh` | 详见 [asr/harmony/README.md](asr/harmony/README.md) |
| Android TTS | `cd tts/android && ./gradlew :sdk:assembleRelease :sample:assembleDebug` | 详见 [tts/android/README.md](tts/android/README.md) |
| HarmonyOS TTS | 先构建共享 native，再用 DevEco 打开 `tts/harmony/` | 详见 [tts/harmony/docs/BUILD.md](tts/harmony/docs/BUILD.md) |
| iOS | `bash asr/ios/build_xcframework.sh` | 详见 [asr/ios/README.md](asr/ios/README.md) |
| ASR Server | `cmake -DSHERPA_ONNX_DIR=...` | 详见 [asr/server/README.md](asr/server/README.md)，需要先在 `third_party/sherpa-onnx` 内做 cxx-api install |
| ASR WebSocket | `uv pip install -e asr/ws-server` 后运行 `python -m amphion_asr_ws` | 详见 [asr/ws-server/README.md](asr/ws-server/README.md) |
| 鼎桥 HarmonyOS 交付 | `bash delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh` | 详见 [delivery/harmony-dingqiao/README.md](delivery/harmony-dingqiao/README.md) |

## 与 sherpa-onnx 的关系

- 上游源码：`third_party/sherpa-onnx/`，submodule 指针 detached 在 v1.13.1
- 公司侧绝对不在 submodule 内提交修改，所有补丁走上游
- Android / iOS 编译脚本会进入 `third_party/sherpa-onnx/` 调用上游 `build-android-*.sh` 和 `build-ios.sh`
- Server 端通过 `-DSHERPA_ONNX_DIR=<path-to-install>` 链接 sherpa-onnx 的 cxx-api 头文件与库
- Android Kotlin 桥接层：`asr/android/sdk/src/main/java/com/k2fsa/sherpa/onnx/*.kt` 是从上游 `android/SherpaOnnxAar/` 复制过来（保留上游 license header），由 [asr/tools/07_sync_kotlin_from_upstream.sh](asr/tools/07_sync_kotlin_from_upstream.sh) 与 submodule 保持一致

## 升级 sherpa-onnx 版本流程

```bash
cd third_party/sherpa-onnx
git fetch --tags
git checkout v1.14.0      # 或目标 tag
cd ../..
git add third_party/sherpa-onnx
bash asr/tools/07_sync_kotlin_from_upstream.sh   # 同步 Kotlin 桥接文件
# 三端跑回归 -> 提 PR
```

## 占位符

发版前还需要替换的真实信息（公司品牌相关已经固化为 Amphion / com.amphion）：

| 占位 | 含义 | 出现位置 |
| --- | --- | --- |
| your-internal-git | 内部 git 域名 | podspec、Package.swift |
| your-cdn.example.com | xcframework / 模型 CDN 主机 | podspec、Package.swift、asr/tools/*.sh、demo manifest |
| your.git.host | iOS SPM url 示例 | asr/ios/README.md |
| voice@amphion.example | 维护者邮箱（.example 仍是占位） | podspec、Helm Chart |
| REPLACE_ME | xcframework 二进制 sha256 | Package.swift、podspec |

替换步骤参考 [asr/android/README.md](asr/android/README.md) 末尾的"包名 / 坐标占位"小节。

## 版本号

整库版本号统一在 `0.1.0`（首版）。涉及位置：

- Android：[asr/android/gradle.properties](asr/android/gradle.properties) `AMPHION_RUNTIME_VERSION`
- iOS：[asr/ios/Sources/AmphionRuntime/AsrSdk.swift](asr/ios/Sources/AmphionRuntime/AsrSdk.swift) `version` + [asr/ios/AmphionRuntime.podspec](asr/ios/AmphionRuntime.podspec) `s.version`
- 发布流程：[shared/docs/RELEASE_PROCESS.md](shared/docs/RELEASE_PROCESS.md)
