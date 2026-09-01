// swift-tools-version:5.7
import PackageDescription

// AmphionRuntime 的 SPM 描述。
//
// 当前开发阶段的使用模式：
// 1) 先运行 build_xcframework.sh，再以本地 Package 引用 asr/ios
// 2) 业务方下载 AmphionRuntime.xcframework，并把 SDK Swift 源码作为子目录嵌入
// 3) 通过本地 CocoaPods path 集成（见 AmphionRuntime.podspec）
//
// xcframework 二进制不入 git。正式发布远程 SPM 前，需要先冻结下载地址与 checksum。

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
        // 业务方使用的 Swift 模块。上游 Swift bridge 必须与 SDK 源码编入同一 module：
        // bridge 的 API 是实现细节（internal），拆成独立 target 后 SDK 源码无法访问。
        .target(
            name: "AmphionRuntime",
            dependencies: ["SherpaOnnxBinary"],
            path: "Sources",
            sources: [
                "AmphionRuntime",
                "SherpaOnnxBridge/SherpaOnnx.swift",
            ]
        ),
        // 当前开发版使用 build_xcframework.sh 生成的本地二进制。
        .binaryTarget(
            name: "SherpaOnnxBinary",
            path: "AmphionRuntime.xcframework"
        ),
        .testTarget(
            name: "AmphionRuntimeTests",
            dependencies: ["AmphionRuntime"],
            path: "Tests/AmphionRuntimeTests"
        ),
    ]
)
