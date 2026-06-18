import Foundation

/// AmphionRuntime 全局入口；与 Android 的 `AsrSdk` 一一对应。
///
/// 典型生命周期（与 Android 一致）：
///
///     AsrSdk.shared.start()           // App 启动期一次
///     let engine = try AsrEngine(config)
///     let session = engine.newSession(callback: myCallback)
///     session.acceptPcm(...)
///     session.stop()
///     session.close()
///     engine.close()
///     AsrSdk.shared.stop()            // App 退出期一次（可选）
///
/// SDK 不做录音；调用方需要自己处理 AVAudioSession + AVAudioEngine（见 Sample）。
public final class AsrSdk {

    /// 单例入口，与 Android 的 `AsrSdk.init()` 静态方法对齐。
    public static let shared = AsrSdk()

    /// SDK 版本号；与 Android `BuildConfig.SDK_VERSION` 同步。
    public let version: String = "0.1.0"

    /// 进程内已启动的 Engine 数（仅诊断用）。
    public private(set) var liveEngineCount: Int = 0

    private let lock = NSLock()
    private var started: Bool = false
    private var logger: AsrLogger = DefaultAsrLogger()

    private init() {}

    /// 必须在创建任何 `AsrEngine` 之前调用一次（多次调用幂等）。
    ///
    /// 与 Android `AsrSdk.init(context)` 对齐；iOS 没有 Context 概念，所以无参数。
    public func start(logger: AsrLogger? = nil) {
        lock.lock()
        defer { lock.unlock() }
        if started { return }
        if let l = logger { self.logger = l }
        started = true
        self.logger.info("AsrSdk \(version) started")
    }

    /// 进程退出前调用；不调用也不会泄露资源（GC 会回收），只是不能复用 Engine。
    public func stop() {
        lock.lock()
        defer { lock.unlock() }
        if !started { return }
        started = false
        logger.info("AsrSdk stopped (live engines=\(liveEngineCount))")
    }

    /// 注入自定义 logger，所有 SDK 内部日志会走它。
    public func setLogger(_ logger: AsrLogger) {
        lock.lock(); defer { lock.unlock() }
        self.logger = logger
    }

    // MARK: - 内部接口（同包可见，但不对外暴露）

    internal func currentLogger() -> AsrLogger { logger }

    internal func incrEngine() {
        lock.lock(); defer { lock.unlock() }
        liveEngineCount += 1
    }

    internal func decrEngine() {
        lock.lock(); defer { lock.unlock() }
        liveEngineCount = max(0, liveEngineCount - 1)
    }

    internal func ensureStarted() {
        lock.lock(); defer { lock.unlock() }
        precondition(started, "AsrSdk.shared.start() must be called before creating an AsrEngine")
    }
}

/// 自定义日志的注入点；与 Android 端 `Logger` 等价。
public protocol AsrLogger: AnyObject {
    func debug(_ message: String)
    func info(_ message: String)
    func warn(_ message: String)
    func error(_ message: String, error: Error?)
}

/// 默认走 NSLog；接 Sample / 业务方自己实现 OSLog / SwiftyBeaver / etc。
public final class DefaultAsrLogger: AsrLogger {
    public init() {}
    public func debug(_ message: String) { NSLog("[AsrSdk D] %@", message) }
    public func info(_ message: String)  { NSLog("[AsrSdk I] %@", message) }
    public func warn(_ message: String)  { NSLog("[AsrSdk W] %@", message) }
    public func error(_ message: String, error: Error?) {
        if let e = error {
            NSLog("[AsrSdk E] %@: %@", message, "\(e)")
        } else {
            NSLog("[AsrSdk E] %@", message)
        }
    }
}
