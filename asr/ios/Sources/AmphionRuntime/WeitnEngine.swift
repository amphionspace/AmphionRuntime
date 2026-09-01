import Foundation
import SherpaOnnxBinary

/// WeText inverse text normalization backed by the same patched sherpa C API used by
/// Android/Harmony. The caller supplies the two audited FST resources; the SDK never downloads
/// or silently substitutes rules at runtime.
public final class WeitnEngine {

    public let config: WeitnConfig
    private let lock = NSLock()
    private var handle: OpaquePointer?

    public init(config: WeitnConfig) throws {
        self.config = config
        let created = config.taggerFst.path.withCString { tagger in
            config.verbalizerFst.path.withCString { verbalizer in
                SherpaOnnxCreateWetextItn(tagger, verbalizer)
            }
        }
        guard let created else {
            throw AsrError(code: .modelLoadFailed,
                           message: "failed to create WeText ITN from the supplied FST resources")
        }
        handle = created
    }

    public var isClosed: Bool {
        lock.lock(); defer { lock.unlock() }
        return handle == nil
    }

    public func normalize(_ text: String) -> String {
        guard !text.isEmpty else { return text }
        lock.lock(); defer { lock.unlock() }
        guard let handle else {
            Log.w("WeitnEngine.normalize called after close; returning input as-is")
            return text
        }
        guard let output = text.withCString({ SherpaOnnxWetextItnNormalize(handle, $0) }) else {
            Log.w("WeText ITN rejected input; returning original text")
            return text
        }
        defer { SherpaOnnxWetextItnFreeText(output) }
        return String(cString: output)
    }

    public func close() {
        let old: OpaquePointer? = {
            lock.lock(); defer { lock.unlock() }
            let value = handle
            handle = nil
            return value
        }()
        if let old { SherpaOnnxDestroyWetextItn(old) }
    }

    deinit { close() }
}
