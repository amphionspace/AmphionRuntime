## AmphionRuntime for iOS

AmphionRuntime 的 iOS 实现，与 [Android AmphionRuntime](../../android/AmphionRuntime/) 公开 API 一一对应。

| 概念 | Android | iOS（Swift） |
| --- | --- | --- |
| 全局入口 | AsrSdk.init / release | AsrSdk.shared.start / stop |
| 引擎 | AsrEngine | AsrEngine |
| 会话 | AsrSession | AsrSession |
| 配置 | AsrConfig.Builder | AsrConfig (struct + init) |
| 回调 | AsrCallback (interface) | AsrCallback (protocol) |
| 错误 | AsrError + AsrErrorCode | AsrError + AsrErrorCode |
| 结果 | AsrResult | AsrResult |
| 模型管理 | ModelManager | ModelManager |
| 模型描述符 | ModelDescriptor | ModelDescriptor |
| 模型类型 | ModelType (enum) | ModelType (enum) |

跨端不变量见 [shared/api-spec/](../../shared/api-spec/)（manifest schema、错误码）。

## 目录结构

```
ios/AmphionRuntime/
├── Package.swift                  # SPM 入口（Xcode 直接打开）
├── README.md
├── AmphionRuntime.podspec           # CocoaPods 兼容
├── build_xcframework.sh           # 调用上游 build-ios.sh 产出 AmphionRuntime.xcframework
├── Sources/
│   ├── AmphionRuntime/              # 主模块（公开 API + 内部实现）
│   │   ├── AsrSdk.swift
│   │   ├── AsrConfig.swift
│   │   ├── AsrEngine.swift
│   │   ├── AsrSession.swift
│   │   ├── AsrCallback.swift
│   │   ├── AsrError.swift
│   │   ├── AsrResult.swift
│   │   ├── ModelManager.swift
│   │   ├── ModelDescriptor.swift
│   │   ├── ModelType.swift
│   │   └── Internal/
│   │       ├── EngineCore.swift
│   │       ├── SessionCore.swift
│   │       ├── ModelLayout.swift
│   │       ├── ModelDownloader.swift
│   │       ├── Sha256Verifier.swift
│   │       └── Logger.swift
│   └── SherpaOnnxBridge/          # 转发 sherpa-onnx 上游的 swift binding（SherpaOnnx.swift）
│       └── module.modulemap       # 让 Swift 能 import C 函数
└── Sample/                        # SwiftUI 单页 demo
    ├── AmphionRuntimeSampleApp.swift
    └── ContentView.swift
```

## 快速集成

### Swift Package Manager（推荐）

在你的 Xcode 工程：File → Add Packages → URL：
`https://your.git.host/amphion/amphion-runtime-ios.git`

或在 Package.swift 中：

```swift
.package(url: "https://your.git.host/amphion/amphion-runtime-ios.git", from: "0.1.0"),
```

### CocoaPods（兼容）

```ruby
pod 'AmphionRuntime', '~> 0.1'
```

## 编译 xcframework

xcframework 通过 `build_xcframework.sh` 一键产出，脚本会进入 `third_party/sherpa-onnx/` 调用上游 build-ios.sh。

```bash
cd /path/to/amphion-runtime
git submodule update --init --recursive   # 第一次 clone 后必做
bash ios/AmphionRuntime/build_xcframework.sh
# 产物：ios/AmphionRuntime/AmphionRuntime.xcframework
```

脚本内部步骤：

1. 调用 [third_party/sherpa-onnx/build-ios.sh](../../third_party/sherpa-onnx/build-ios.sh) 编译 device + simulator + arm64 simulator
2. 把 `sherpa-onnx.xcframework` 重命名为 `AmphionRuntime.xcframework`
3. 把 [third_party/sherpa-onnx/swift-api-examples/SherpaOnnx.swift](../../third_party/sherpa-onnx/swift-api-examples/SherpaOnnx.swift) 复制到 `Sources/SherpaOnnxBridge/`
4. 把上游产物 + 我们的 Swift 公开 API 一起打包

## 与 Android SDK 的差异

| 维度 | Android | iOS | 备注 |
| --- | --- | --- | --- |
| 模型存储 | filesDir 内部目录 | NSDocumentDirectory | 都是 app 沙箱内 |
| 录音权限 | RECORD_AUDIO | NSMicrophoneUsageDescription | SDK 不接管录音 |
| Endpoint 默认值 | rule1=2.4 / rule2=1.2 / rule3=20 | 同 | 跨端一致 |
| AsrCallback | interface + 默认方法 | protocol + extension 默认方法 | 行为一致 |

## 联系

- 共享协议：[shared/api-spec/](../../shared/api-spec/)
- 跨端烟测样本：[shared/regression-set/](../../shared/regression-set/)（仅烟测，WER 由上游 [scripts/benchmark/](../../scripts/benchmark/) 出报告）
- 发布流程：[shared/docs/RELEASE_PROCESS.md](../../shared/docs/RELEASE_PROCESS.md)
