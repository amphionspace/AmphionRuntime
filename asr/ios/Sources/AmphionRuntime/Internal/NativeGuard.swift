import Foundation

/// 与 Android `NativeGuard` 行为对齐：把任何 NSException / Swift Error 翻成 NATIVE_CRASH (9001)。
///
/// Swift 没有 Java 的 Throwable 概念，但 ObjC 的 NSException 仍可能从 C 函数抛出来；
/// 这里做最小可用的"包一层 try/catch"，业务方调用方只看到 [AsrError]。
internal enum NativeGuard {

    /// 同步执行 [block]；任何错误都包成 [AsrError(NATIVE_CRASH)] 返回 nil。
    static func run<R>(_ opName: String, block: () throws -> R) -> R? {
        do {
            return try block()
        } catch {
            Log.e("[NativeGuard] \(opName) threw: \(error)", error: error)
            return nil
        }
    }

    /// 同步执行 [block]，吞掉所有错误（用于 close/release）。
    static func runQuietly(_ opName: String, _ block: () -> Void) {
        block()   // C 函数通常不抛异常；保留 helper 用以将来扩展
        _ = opName
    }
}
