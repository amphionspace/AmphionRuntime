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
| WeText ITN | WeitnConfig + WeitnEngine | WeitnConfig + WeitnEngine |

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
3. 把 [third_party/sherpa-onnx/swift-api-examples/SherpaOnnx.swift](../../third_party/sherpa-onnx/swift-api-examples/SherpaOnnx.swift) 复制到 `Sources/SherpaOnnxBridge/`（自动带上 fork 里新增的 `sherpaOnnxWetextItnConfig` / `SherpaOnnxWetextItnWrapper`）
4. 把上游产物 + 我们的 Swift 公开 API 一起打包

依赖：完整 Xcode + iOS SDK（不是 Command Line Tools），活动开发者目录指向 Xcode.app：

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
xcodebuild -version              # 应输出 Xcode 版本号
```

兼容性：上游 [ios.toolchain.cmake](../../third_party/sherpa-onnx/toolchains/ios.toolchain.cmake) 与 CMake 4.x 的 `get_filename_component()` 参数检查更严，如果 `xcodebuild -version -sdk iphonesimulator Path` 因缺 Xcode 而返回空字符串，cmake configure 会 fatal。建议 CI 上锁定 CMake 3.x 或安装完整 Xcode。

#### 在没有 iOS 完整 Xcode 时验证 wetext 集成

如果只是想本地验证 fork 里 vendor 的 WeText C++ runtime + C-API 改动能编译通过，可以用上游自带的 `build-swift-macos.sh`（不依赖 ios.toolchain.cmake，纯 macOS native build）：

```bash
cd third_party/sherpa-onnx
rm -rf build-swift-macos
bash build-swift-macos.sh
nm build-swift-macos/lib/libsherpa-onnx-c-api.a | grep WetextItn
# 期望输出（4 个外部符号）：
# _SherpaOnnxCreateWetextItn
# _SherpaOnnxDestroyWetextItn
# _SherpaOnnxWetextItnFreeText
# _SherpaOnnxWetextItnNormalize
```

## WeText ITN

iOS 端的 `WeitnEngine` 与 Android 同款，内部包装我们 fork 的 sherpa-onnx 里 vendored 的 [WeTextProcessing](https://github.com/wenet-e2e/WeTextProcessing)（Apache-2.0）三段式中文 ITN runtime。fst 体积 ~2-4 MB，不打进 xcframework，运行时由业务方分发。

```swift
import AmphionRuntime

let docs = FileManager.default.urls(
    for: .documentDirectory, in: .userDomainMask
).first!
let cfg = try WeitnConfig(
    taggerFst: docs.appendingPathComponent("asr-weitn/zh_itn_tagger.fst"),
    verbalizerFst: docs.appendingPathComponent("asr-weitn/zh_itn_verbalizer.fst")
)
let itn = try WeitnEngine(config: cfg)

let out = itn.normalize("两点五八万")        // "2.58万"
let out2 = itn.normalize("二零二六年五月十五日") // "2026年5月15日"

itn.close()
```

特点：

- 与 `AsrEngine` 完全解耦：ITN 失败不影响 ASR；推荐 `ASR final → WeitnEngine.normalize → 业务后处理` 的串行管线
- 线程安全；内部带 `NSLock`，并发 normalize 串行排队
- fst 由业务方分发：通常把 `zh_itn_tagger.fst` + `zh_itn_verbalizer.fst` 放在自家 CDN，业务侧下载到 `NSDocumentDirectory` 内即可

详见 Android 端的 [docs/INTEGRATION.md §12.4](../../android/AmphionRuntime/docs/INTEGRATION.md)（行为对齐）与 [tools/asr/MODEL_LAYOUT.md §6](../../tools/asr/MODEL_LAYOUT.md)（fst 分发约定）。

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
