import Foundation

/// 内部 logger 适配器：所有 SDK 内部代码用 `Log.*` 而非直接 print/NSLog，以便统一注入。
internal enum Log {
    static func d(_ msg: @autoclosure () -> String) {
        AsrSdk.shared.currentLogger().debug(msg())
    }
    static func i(_ msg: @autoclosure () -> String) {
        AsrSdk.shared.currentLogger().info(msg())
    }
    static func w(_ msg: @autoclosure () -> String) {
        AsrSdk.shared.currentLogger().warn(msg())
    }
    static func e(_ msg: @autoclosure () -> String, error: Error? = nil) {
        AsrSdk.shared.currentLogger().error(msg(), error: error)
    }
}
