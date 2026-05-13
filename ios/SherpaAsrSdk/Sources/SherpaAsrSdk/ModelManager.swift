import Foundation

/// 与 Android `ModelManager` 一一对应：负责模型本地路径解析、远程下载、SHA256 校验。
///
/// 与 Android 的差异：
/// - Android 用 Context.filesDir；iOS 用 NSDocumentDirectory（也是 app 沙箱内）
/// - Android 用 OkHttp；iOS 用 URLSession.shared
public final class ModelManager {

    public let rootDir: URL

    /// 默认根目录：~/Documents/AsrModels；可由调用方覆盖。
    public init(rootDir: URL? = nil) {
        if let r = rootDir {
            self.rootDir = r
        } else {
            let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            self.rootDir = docs.appendingPathComponent("AsrModels", isDirectory: true)
        }
        try? FileManager.default.createDirectory(at: self.rootDir, withIntermediateDirectories: true)
    }

    /// 给定 modelId + version，返回本地存放目录（不一定存在）。
    public func localDir(modelId: String, version: String) -> URL {
        return rootDir
            .appendingPathComponent(modelId, isDirectory: true)
            .appendingPathComponent(version, isDirectory: true)
    }

    /// 检查给定模型是否已经在本地存在并完整（manifest.json 存在 + 必备文件存在）。
    public func isReady(modelId: String, version: String) -> Bool {
        let dir = localDir(modelId: modelId, version: version)
        let manifest = dir.appendingPathComponent("manifest.json")
        let tokens = dir.appendingPathComponent("tokens.txt")
        return FileManager.default.fileExists(atPath: manifest.path)
            && FileManager.default.fileExists(atPath: tokens.path)
    }

    /// 把本地一个目录注册到本 ModelManager 管理（业务方手动 import 模型场景）。
    public func importLocal(srcDir: URL, modelId: String, version: String) throws {
        let dst = localDir(modelId: modelId, version: version)
        if FileManager.default.fileExists(atPath: dst.path) {
            try FileManager.default.removeItem(at: dst)
        }
        try FileManager.default.createDirectory(at: dst.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: srcDir, to: dst)
    }

    /// 异步下载远程模型并校验 SHA256；与 Android `ModelManager.fetch` 行为一致。
    /// 返回的 URL 是 unzip 完成后的目录（含 manifest.json）。
    public func fetchAsync(
        descriptor: ModelDescriptor,
        progress: ((Double) -> Void)? = nil,
        completion: @escaping (Result<URL, AsrError>) -> Void
    ) {
        let logger = AsrSdk.shared.currentLogger()
        let dir = localDir(modelId: descriptor.modelId, version: descriptor.version)
        if isReady(modelId: descriptor.modelId, version: descriptor.version) {
            logger.info("model already cached: \(dir.path)")
            completion(.success(dir))
            return
        }

        guard let urlStr = descriptor.url, let url = URL(string: urlStr) else {
            completion(.failure(AsrError(code: .invalidArgument, message: "ModelDescriptor.url is missing")))
            return
        }

        let downloader = ModelDownloader()
        downloader.download(
            url: url,
            expectedSha256: descriptor.sha256,
            destDir: dir,
            progress: progress
        ) { result in
            switch result {
            case .success:
                logger.info("model downloaded: \(dir.path)")
                completion(.success(dir))
            case .failure(let err):
                logger.error("download failed", error: err)
                completion(.failure(err))
            }
        }
    }

    /// async/await 包装版本，便于 SwiftUI / async 调用方使用。
    @available(iOS 13.0, *)
    public func fetch(descriptor: ModelDescriptor,
                      progress: ((Double) -> Void)? = nil) async throws -> URL {
        return try await withCheckedThrowingContinuation { cont in
            fetchAsync(descriptor: descriptor, progress: progress) { result in
                switch result {
                case .success(let url): cont.resume(returning: url)
                case .failure(let err): cont.resume(throwing: err)
                }
            }
        }
    }
}
