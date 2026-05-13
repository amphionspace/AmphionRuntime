import Foundation

/// 与 Android `AsrEngine` 一一对应。
///
/// 一个 Engine 对应一个加载好的模型 + 共享的 onnx runtime；可派生多个 [AsrSession] 并发使用。
public final class AsrEngine {

    public let config: AsrConfig
    private let core: EngineCore
    private var closed = false
    private let lock = NSLock()

    /// 创建 Engine；同步加载模型，可能耗时数百毫秒。
    /// 推荐在后台线程调用。
    public init(config: AsrConfig) throws {
        AsrSdk.shared.ensureStarted()
        let normalized = try config.validatedAndNormalized()
        self.config = normalized
        self.core = try EngineCore(config: normalized)
        AsrSdk.shared.incrEngine()
    }

    /// 创建一个新的识别会话；callback 在 SDK 专用 dispatch queue 上派发。
    public func newSession(callback: AsrCallback) -> AsrSession {
        lock.lock(); defer { lock.unlock() }
        precondition(!closed, "AsrEngine is closed")
        return AsrSession(core: core.newSession(callback: callback))
    }

    /// 释放本 Engine（包括所有未关闭的 session）。
    public func close() {
        lock.lock(); defer { lock.unlock() }
        if closed { return }
        closed = true
        core.close()
        AsrSdk.shared.decrEngine()
    }

    deinit {
        close()
    }
}
