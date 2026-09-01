## AmphionRuntime for iOS

AmphionRuntime 的 iOS 实现。基础 ASR API 已有原型；鼎桥兼容层正在按
[跨端参数契约](../../shared/api-spec/dingqiao-asr-parameters.json) 分阶段对齐。当前代码不能描述为
Android/HarmonyOS 完整能力等价，已完成范围和剩余门禁见
[DINGQIAO_PARITY.md](DINGQIAO_PARITY.md)。

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
| WeText ITN | WeitnConfig + WeitnEngine | 已接 patched sherpa C API；Dingqiao final 按 ITN → 标点自动处理 |

跨端不变量见 [shared/api-spec/](../../shared/api-spec/)（manifest schema、错误码）。

## 目录结构

```
asr/ios/
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
│   │   ├── Dingqiao/                # 鼎桥兼容参数、生命周期和引擎适配层
│   │   └── Internal/
│   │       ├── EngineCore.swift
│   │       ├── SessionCore.swift
│   │       ├── ModelLayout.swift
│   │       ├── ModelDownloader.swift
│   │       ├── Sha256Verifier.swift
│   │       └── Logger.swift
│   └── SherpaOnnxBridge/          # 与主 SDK 编入同一 module 的上游 Swift binding
│       └── SherpaOnnx.swift
└── Sample/                        # SwiftUI 单页 demo
    ├── AmphionRuntimeSample.xcodeproj
    ├── AmphionRuntimeSampleApp.swift
    └── ContentView.swift
```

## 快速集成

> 当前为 `0.3.4-ios-alpha` 开发阶段，尚未发布可直接引用的远程 SPM/CocoaPods 制品。开发验证应先
> 运行 `build_xcframework.sh`，再通过 Xcode Add Local Package 引用 `asr/ios`。

### Swift Package Manager（推荐）

在你的 Xcode 工程中选择 File → Add Package Dependencies → Add Local，并指向本仓库的
`asr/ios`。也可以在本地 `Package.swift` 中使用路径依赖：

```swift
.package(path: "/path/to/AmphionRuntime/asr/ios"),
```

### CocoaPods（兼容）

```ruby
pod 'AmphionRuntime', :path => '/path/to/AmphionRuntime/asr/ios'
```

## 编译 xcframework

xcframework 通过 `build_xcframework.sh` 一键产出。脚本不会修改固定 submodule，而是在忽略的
`asr/ios/.native-src/` worktree 中应用与 Android/Harmony 相同的 Amphion patch series 后编译。

```bash
cd /path/to/amphion-runtime
git submodule update --init --recursive   # 第一次 clone 后必做
bash asr/ios/build_xcframework.sh
# 产物：asr/ios/AmphionRuntime.xcframework
```

脚本内部步骤：

1. 从固定 `sherpa-onnx` 1.13.1 创建隔离 worktree，应用全部 `third_party/patches/sherpa-amphion`，
   再编译 device arm64 与 simulator arm64/x86_64；patch 哈希变化时拒绝复用旧派生源码
2. 校验固定 ONNX Runtime 1.17.1 归档的大小与 SHA-256，并把对应 ORT 静态库合入每个
   device/simulator slice，避免客户工程出现 `_OrtGetApiBase` 未定义
3. 为每个 slice 写入 `SherpaOnnxBinary` module map，再把 `sherpa-onnx.xcframework` 封装为
   `AmphionRuntime.xcframework`
4. 把 [third_party/sherpa-onnx/swift-api-examples/SherpaOnnx.swift](../../third_party/sherpa-onnx/swift-api-examples/SherpaOnnx.swift) 同步到 `Sources/SherpaOnnxBridge/`；它与主 SDK 源码编入同一个 Swift module
5. native XCFramework 作为 binary target；AmphionRuntime Swift 公共 API 由 SPM/CocoaPods
   source target 一起交付。当前脚本不会把 Swift wrapper 编译进单一闭源 XCFramework。

依赖：完整 Xcode + iOS SDK（不是 Command Line Tools），活动开发者目录指向 Xcode.app：

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
xcodebuild -version              # 应输出 Xcode 版本号
```

兼容性：上游 [ios.toolchain.cmake](../../third_party/sherpa-onnx/toolchains/ios.toolchain.cmake) 与 CMake 4.x 的 `get_filename_component()` 参数检查更严，如果 `xcodebuild -version -sdk iphonesimulator Path` 因缺 Xcode 而返回空字符串，cmake configure 会 fatal。建议 CI 上锁定 CMake 3.x 或安装完整 Xcode。

## WeText ITN

`build_xcframework.sh` 应用的 Amphion patch series 已提供 WeText 与离线标点 C API；`WeitnEngine`
从调用方提供的 tagger/verbalizer FST 创建真实 native processor。Dingqiao final 固定按
`WeText ITN → CT-Transformer 标点` 串行处理，与 Android/Harmony 相同；任一资源缺失时保留上一阶段
文本，并可通过 `runtimeCapabilities()` 预检，Demo 也会明确显示“资源未就绪”。

`setAuxiliaryModelDirectory` 支持直接公共根目录或其 `amphion-models/` 子目录，交付布局为：

```text
punct-zhen/v1/model.int8.ort        # 也兼容 model.int8.onnx
itn-zh/v1/zh_itn_tagger.fst
itn-zh/v1/zh_itn_verbalizer.fst
```

这些大资源不重复提交到 iOS 代码目录；正式组包必须从审核过的单一模型源复制并记录哈希。

## 鼎桥兼容 API

```swift
let sdk = SpeechRecognizeSdk.shared
try sdk.setWorkPath(appSupportDirectory)
sdk.setModelDirectory(deliveredModelDirectory)
sdk.setAuxiliaryModelDirectory(deliveredSharedModelDirectory)
let capabilities = sdk.runtimeCapabilities()
sdk.prepareRuntime(callback: prepareCallback)

let engine = try sdk.createEngine(
    CreateEngineParams(
        language: "zh-CN",
        extraParams: ["recognizerMode": "short"]
    )
)
engine.setListener(listener)
engine.startListening(
    StartParams(
        sessionId: "session_001",
        extraParams: [
            "recognitionMode": 1,
            "recognizerMode": "short",
            "vadEnd": 800,
            "maxAudioDuration": 60_000,
        ]
    )
)
// 每次写入 640 字节：16 kHz / 16-bit / mono / little-endian / 20 ms PCM。
engine.writeAudio(sessionId: "session_001", audio: pcmFrame)
engine.finish(sessionId: "session_001")
```

已经锁定的生命周期语义：

- 普通 endpoint final：`isFinal=true, isLast=false`。
- 显式 `finish` 或 `maxAudioDuration`：唯一一次 `isLast=true`，随后唯一一次 `onComplete`。
- `cancel`：不再产生 final 或 `onComplete`。
- `onStart` 派发前 session 已经发布，可在回调内同步写入、finish 或 cancel。
- finishing 状态调用 `shutdown` 会等待 native tail，再释放 stream 和 recognizer。

`vadBegin` 已接多信号起音门禁；声纹注册/逐 final 打分、窗口式 Speaker VAD 状态事件和离线
说话人分离已接公共模型，并在模型缺失时显式拒绝启动；自动 ITN/标点已串入 final，并由能力快照
反映实际资源状态。Police LAC、正式离线授权、Diagnostics v2 和 Objective-C facade 仍未完成；
详见能力矩阵，不要把当前开发制品描述为完整客户版。

## 与 Android SDK 的差异

| 维度 | Android | iOS | 备注 |
| --- | --- | --- | --- |
| 模型存储 | filesDir 内部目录 | NSDocumentDirectory | 都是 app 沙箱内 |
| 录音权限 | RECORD_AUDIO | NSMicrophoneUsageDescription | SDK 不接管录音 |
| Endpoint 默认值 | rule1=2.4 / rule2=1.4 / rule3=20 | 同 | 基础 API 跨端一致 |
| AsrCallback | interface + 默认方法 | protocol + extension 默认方法 | 行为一致 |

## 联系

- 共享协议：[shared/api-spec/](../../shared/api-spec/)
- 跨端烟测样本：[shared/regression-set/](../../shared/regression-set/)（仅烟测，WER 由上游 [scripts/benchmark/](../../scripts/benchmark/) 出报告）
- 发布流程：[shared/docs/RELEASE_PROCESS.md](../../shared/docs/RELEASE_PROCESS.md)
