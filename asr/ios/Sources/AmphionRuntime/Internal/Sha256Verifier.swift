import Foundation
import CryptoKit

/// 与 Android `Sha256Verifier` 行为完全一致。
internal enum Sha256Verifier {
    /// 计算文件 SHA256 hex 字符串（小写）。
    static func hex(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        let bufSize = 1 << 16   // 64 KB
        while true {
            let data = handle.readData(ofLength: bufSize)
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        let digest = hasher.finalize()
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    /// 校验文件 sha256 是否匹配（大小写无关）；不匹配抛出 [AsrError]。
    static func verify(file: URL, expected: String) throws {
        let actual = try hex(of: file).lowercased()
        let exp = expected.lowercased()
        if actual != exp {
            throw AsrError(
                code: .sha256Mismatch,
                message: "sha256 mismatch for \(file.lastPathComponent): expected=\(exp) actual=\(actual)"
            )
        }
    }
}
