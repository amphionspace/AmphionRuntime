// swift-tools-version:5.7
import PackageDescription

// AmphionRuntime 的 SPM 描述。
//
// 三种使用模式：
// 1) 业务方直接 .package(url:from:) 这个仓库；编译流程会拉本仓库源码 + binary xcframework
// 2) 业务方下载 AmphionRuntime.xcframework + 把 SDK Swift 源码作为子目录嵌入
// 3) 通过 CocoaPods 集成（见 AmphionRuntime.podspec）
//
// xcframework 二进制不入 git，由 CI 产出后挂在 GitHub Releases / 公司私有 OSS。
// 业务方第一次 `swift build` 会按下面 binaryTarget.url 拉取并校验 sha256。
//
// 注意：替换 binaryTarget.url 与 checksum 为你公司真实地址 + 实际 sha256。

let package = Package(
    name: "AmphionRuntime",
    platforms: [
        .iOS(.v13),
    ],
    products: [
        .library(name: "AmphionRuntime", targets: ["AmphionRuntime"]),
    ],
    dependencies: [
        // 暂无外部依赖；Swift 标准库 + Foundation 已足够
    ],
    targets: [
        // 业务方使用的 Swift 模块；依赖 SherpaOnnxBridge（C-API 桥接）
        .target(
            name: "AmphionRuntime",
            dependencies: ["SherpaOnnxBridge"],
            path: "Sources/AmphionRuntime"
        ),
        // 转发上游 sherpa-onnx 的 Swift API（来自 swift-api-examples/SherpaOnnx.swift），
        // 由 build_xcframework.sh 自动复制到本目录。
        .target(
            name: "SherpaOnnxBridge",
            dependencies: ["SherpaOnnxBinary"],
            path: "Sources/SherpaOnnxBridge"
        ),
        // 二进制 xcframework；CI 产出后挂在 GitHub Releases / 公司 OSS，业务方 SPM 拉取并校验 sha256
        .binaryTarget(
            name: "SherpaOnnxBinary",
            // 替换为你公司私有 OSS 的真实地址：
            // url: "https://your-cdn.example.com/amphion-runtime/0.1.0/AmphionRuntime.xcframework.zip",
            // checksum: "REPLACE_ME_WITH_REAL_SHA256",
            // 临时本地引用（CI 跑 build_xcframework.sh 后会产出在这个相对路径）：
            path: "AmphionRuntime.xcframework"
        ),
    ]
)
