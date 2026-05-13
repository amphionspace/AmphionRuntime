import Foundation

/// 与 Android `ModelDownloader` 行为对齐：基于 URLSession 下载 + sha256 校验 + 解压。
internal final class ModelDownloader: NSObject, URLSessionDownloadDelegate {

    private var progressHandler: ((Double) -> Void)?
    private var completion: ((Result<URL, AsrError>) -> Void)?
    private var destZip: URL?
    private var destDir: URL?
    private var expectedSha256: String?

    func download(
        url: URL,
        expectedSha256: String?,
        destDir: URL,
        progress: ((Double) -> Void)?,
        completion: @escaping (Result<URL, AsrError>) -> Void
    ) {
        let logger = AsrSdk.shared.currentLogger()
        logger.info("downloading \(url.absoluteString) -> \(destDir.path)")

        do {
            try FileManager.default.createDirectory(at: destDir, withIntermediateDirectories: true)
        } catch {
            completion(.failure(AsrError(code: .ioFailed, message: "mkdir failed", underlying: error)))
            return
        }

        let zip = destDir.appendingPathComponent("_model.zip")
        self.destZip = zip
        self.destDir = destDir
        self.expectedSha256 = expectedSha256
        self.progressHandler = progress
        self.completion = completion

        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 60
        cfg.timeoutIntervalForResource = 600
        let session = URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
        session.downloadTask(with: url).resume()
    }

    // MARK: - URLSessionDownloadDelegate

    func urlSession(_ session: URLSession,
                    downloadTask: URLSessionDownloadTask,
                    didFinishDownloadingTo location: URL) {
        guard let zip = destZip, let destDir = destDir else { return }
        do {
            if FileManager.default.fileExists(atPath: zip.path) {
                try FileManager.default.removeItem(at: zip)
            }
            try FileManager.default.moveItem(at: location, to: zip)

            if let exp = expectedSha256, !exp.isEmpty {
                try Sha256Verifier.verify(file: zip, expected: exp)
            }

            try unzip(zip: zip, into: destDir)
            try? FileManager.default.removeItem(at: zip)
            DispatchQueue.main.async { self.completion?(.success(destDir)) }
        } catch let asrErr as AsrError {
            DispatchQueue.main.async { self.completion?(.failure(asrErr)) }
        } catch {
            DispatchQueue.main.async {
                self.completion?(.failure(AsrError(code: .downloadFailed, message: "post-download failed", underlying: error)))
            }
        }
    }

    func urlSession(_ session: URLSession,
                    task: URLSessionTask,
                    didCompleteWithError error: Error?) {
        if let err = error {
            DispatchQueue.main.async {
                self.completion?(.failure(AsrError(code: .networkUnavailable, message: "URLSession error", underlying: err)))
            }
        }
    }

    func urlSession(_ session: URLSession,
                    downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64,
                    totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let p = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
        DispatchQueue.main.async { self.progressHandler?(p) }
    }

    // 极简的 zip 解压；iOS 没有内置 zip API，这里通过 NSFileCoordinator + AppleArchive 实现。
    // 公司若需要 tar.gz / 自定义压缩格式，请在此扩展。
    private func unzip(zip: URL, into destDir: URL) throws {
        // 使用 ProcessInfo + Process（iOS 不可用），所以直接走 NSFileCoordinator + Foundation 的
        // unzipItem 不存在；最简单实用做法：依赖 Apple 提供的 SSZipArchive / ZIPFoundation 或自己加。
        // 为了零依赖，这里用 ProcessInfo 的 unzip CLI 仅在 macOS 工作；iOS 上请挂 ZIPFoundation。
        //
        // 公司实施时建议：把 ZIPFoundation 加到 Package.swift dependencies，调用：
        //   try FileManager.default.unzipItem(at: zip, to: destDir)
        // 这里给出 URL+异常占位，让业务方自然踩到提示。
        throw AsrError(
            code: .ioFailed,
            message: "ZIP unzip not implemented; please add ZIPFoundation dependency in Package.swift " +
                     "and replace ModelDownloader.unzip(zip:into:) impl. See README."
        )
    }
}
