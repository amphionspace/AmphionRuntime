import Foundation
import SherpaOnnxBinary

/// 与 Android `EngineImpl` 行为对齐：包装上游 sherpa-onnx C-API，对上提供 newSession 工厂。
internal final class EngineCore {

    private let config: AsrConfig
    private var recognizer: OpaquePointer?
    private let lifecycleLock = NSLock()
    private var sessions: [ObjectIdentifier: WeakSessionCore] = [:]
    private var closed = false

    /// 给 SessionCore 在 createStream 时透传热词字符串
    fileprivate(set) var engineHotwords: String

    init(config: AsrConfig) throws {
        self.config = config
        self.engineHotwords = config.hotwords.joined(separator: "\n")

        var rc = try EngineCore.buildRecognizerConfig(config: config)
        guard let r = NativeGuard.run("OnlineRecognizer init", block: {
            SherpaOnnxCreateOnlineRecognizer(&rc)
        }) ?? nil else {
            throw AsrError(code: .modelLoadFailed,
                           message: "Failed to create OnlineRecognizer from \(config.modelDir.path)")
        }
        self.recognizer = r
        Log.i("OnlineRecognizer loaded from \(config.modelDir.path)")
    }

    func newSession(callback: AsrCallback) -> SessionCore {
        lifecycleLock.lock()
        defer { lifecycleLock.unlock() }
        precondition(!closed, "AsrEngine is closed")
        let session = SessionCore(
            recognizer: self.recognizer,
            sampleRate: config.sampleRate,
            engineHotwords: engineHotwords,
            engineHotwordsScore: config.hotwordsScore,
            callback: callback
        )
        sessions[ObjectIdentifier(session)] = WeakSessionCore(session)
        sessions = sessions.filter { $0.value.value != nil }
        return session
    }

    func close() {
        let snapshot: ([SessionCore], OpaquePointer?) = {
            lifecycleLock.lock()
            defer { lifecycleLock.unlock() }
            if closed { return ([], nil) }
            closed = true
            let liveSessions = sessions.values.compactMap(\.value)
            sessions.removeAll()
            let native = recognizer
            recognizer = nil
            return (liveSessions, native)
        }()
        // 必须先等所有 stream 的串行 native 工作结束，再释放进程内 recognizer。
        snapshot.0.forEach { $0.closeAndWait() }
        if let native = snapshot.1 { SherpaOnnxDestroyOnlineRecognizer(native) }
    }

    deinit {
        close()
    }

    /// 翻译 [AsrConfig] -> 上游 [SherpaOnnxOnlineRecognizerConfig]。
    private static func buildRecognizerConfig(config c: AsrConfig) throws -> SherpaOnnxOnlineRecognizerConfig {
        let modelType = ModelType.from(manifestString: try? readModelTypeFromManifest(modelDir: c.modelDir))
        let resolved = try ModelLayout.resolve(modelDir: c.modelDir, type: modelType)

        // model_type 字符串：手 hand off 给上游用的细分名
        let modelTypeStr: String = {
            switch modelType {
            case .transducer: return "zipformer2"
            case .paraformer: return "paraformer"
            case .zipformer2_ctc: return "zipformer2_ctc"
            case .nemo_ctc: return "nemo_ctc"
            }
        }()

        let onlineModel: SherpaOnnxOnlineModelConfig
        switch modelType {
        case .transducer:
            onlineModel = sherpaOnnxOnlineModelConfig(
                tokens: resolved.tokens.path,
                transducer: sherpaOnnxOnlineTransducerModelConfig(
                    encoder: resolved.encoder!.path,
                    decoder: resolved.decoder!.path,
                    joiner: resolved.joiner!.path
                ),
                numThreads: c.numThreads,
                provider: c.disablePrepack ? "cpu;DisablePrepacking=1" : "cpu",
                debug: 0,
                modelType: modelTypeStr,
                modelingUnit: resolved.bpeVocab == nil ? "cjkchar" : "bbpe",
                bpeVocab: resolved.bpeVocab?.path ?? ""
            )
        case .paraformer:
            onlineModel = sherpaOnnxOnlineModelConfig(
                tokens: resolved.tokens.path,
                paraformer: sherpaOnnxOnlineParaformerModelConfig(
                    encoder: resolved.encoder!.path,
                    decoder: resolved.decoder!.path
                ),
                numThreads: c.numThreads,
                provider: c.disablePrepack ? "cpu;DisablePrepacking=1" : "cpu",
                debug: 0,
                modelType: modelTypeStr
            )
        case .zipformer2_ctc:
            onlineModel = sherpaOnnxOnlineModelConfig(
                tokens: resolved.tokens.path,
                zipformer2Ctc: sherpaOnnxOnlineZipformer2CtcModelConfig(model: resolved.model!.path),
                numThreads: c.numThreads,
                provider: c.disablePrepack ? "cpu;DisablePrepacking=1" : "cpu",
                debug: 0,
                modelType: modelTypeStr
            )
        case .nemo_ctc:
            onlineModel = sherpaOnnxOnlineModelConfig(
                tokens: resolved.tokens.path,
                numThreads: c.numThreads,
                provider: c.disablePrepack ? "cpu;DisablePrepacking=1" : "cpu",
                debug: 0,
                modelType: modelTypeStr,
                nemoCtc: sherpaOnnxOnlineNemoCtcModelConfig(model: resolved.model!.path)
            )
        }

        let feat = sherpaOnnxFeatureConfig(sampleRate: c.sampleRate, featureDim: c.featureDim)
        let hr: SherpaOnnxHomophoneReplacerConfig = {
            if let lex = c.homophoneLexiconPath, let fst = c.homophoneRuleFstsPath {
                return sherpaOnnxHomophoneReplacerConfig(lexicon: lex.path, ruleFsts: fst.path)
            }
            return SherpaOnnxHomophoneReplacerConfig()
        }()
        // 注：ITN 已迁出到独立的 WeitnEngine（基于 WeTextProcessing），不再走
        // sherpa-onnx 的 rule_fsts 通道。
        return sherpaOnnxOnlineRecognizerConfig(
            featConfig: feat,
            modelConfig: onlineModel,
            enableEndpoint: c.enableEndpoint,
            rule1MinTrailingSilence: c.endpointRules.rule1MinTrailingSilenceSec,
            rule2MinTrailingSilence: c.endpointRules.rule2MinTrailingSilenceSec,
            rule3MinUtteranceLength: c.endpointRules.rule3MinUtteranceLengthSec,
            decodingMethod: c.decodingMethod.rawValue,
            maxActivePaths: c.maxActivePaths,
            hotwordsFile: "",
            hotwordsScore: c.hotwordsScore,
            ruleFsts: "",
            ruleFars: "",
            blankPenalty: 0,
            hotwordsBuf: "",
            hotwordsBufSize: 0,
            hr: hr
        )
    }

    /// 从 modelDir/manifest.json 读取 model_type；不存在或解析失败返回 nil。
    private static func readModelTypeFromManifest(modelDir: URL) throws -> String? {
        let mf = modelDir.appendingPathComponent("manifest.json")
        if !FileManager.default.fileExists(atPath: mf.path) { return nil }
        let data = try Data(contentsOf: mf)
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return json["model_type"] as? String
    }
}

private final class WeakSessionCore {
    weak var value: SessionCore?
    init(_ value: SessionCore) { self.value = value }
}
