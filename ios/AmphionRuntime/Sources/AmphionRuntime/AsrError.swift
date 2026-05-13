import Foundation

/// 与 Android 完全一致的错误码段（见 [shared/api-spec/errcodes.yaml](../../../../shared/api-spec/errcodes.yaml)）：
///
///     1xxx 配置类
///     2xxx 模型类
///     3xxx 运行时类
///     4xxx 网络类
///     5xxx 系统类
///     9xxx native crash 兜底
public enum AsrErrorCode: Int {
    // 1xxx
    case invalidArgument         = 1001
    case invalidSampleRate       = 1002
    case sdkNotInitialized       = 1003

    // 2xxx
    case modelDirInvalid         = 2001
    case modelFileMissing        = 2002
    case modelLoadFailed         = 2003
    case modelManifestParseError = 2004

    // 3xxx
    case sessionAlreadyClosed    = 3001
    case sampleRateMismatch      = 3002
    case decodeFailed            = 3003

    // 4xxx
    case networkUnavailable      = 4001
    case downloadFailed          = 4002
    case sha256Mismatch          = 4003

    // 5xxx
    case ioFailed                = 5001
    case storageInsufficient     = 5002

    // 9xxx
    case nativeCrash             = 9001
}

/// 与 Android `AsrError` 一一对应的错误对象。
public struct AsrError: Error, CustomStringConvertible {
    public let code: AsrErrorCode
    public let message: String
    public let underlying: Error?

    public init(code: AsrErrorCode, message: String, underlying: Error? = nil) {
        self.code = code
        self.message = message
        self.underlying = underlying
    }

    public var description: String {
        if let u = underlying {
            return "AsrError(code=\(code.rawValue), \(message), cause=\(u))"
        }
        return "AsrError(code=\(code.rawValue), \(message))"
    }
}
