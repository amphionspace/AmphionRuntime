import Foundation
import SherpaOnnxBridge   // 由 build_xcframework.sh 自动产出，含上游 SherpaOnnx.swift

/// 与 Android `EngineImpl` 行为对齐：包装上游 sherpa-onnx C-API，对上提供 newSession 工厂。
internal final class EngineCore {

    private let config: AsrConfig
    private let recognizer: OpaquePointer?

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
        return SessionCore(
            recognizer: recognizer,
            sampleRate: config.sampleRate,
            engineHotwords: engineHotwords,
            engineHotwordsScore: config.hotwordsScore,
            callback: callback
        )
    }

    func close() {
        if let r = recognizer {
            SherpaOnnxDestroyOnlineRecognizer(r)
        }
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
                provider: "cpu",
                debug: 0,
                modelType: modelTypeStr
            )
        case .paraformer:
            onlineModel = sherpaOnnxOnlineModelConfig(
                tokens: resolved.tokens.path,
                paraformer: sherpaOnnxOnlineParaformerModelConfig(
                    encoder: resolved.encoder!.path,
                    decoder: resolved.decoder!.path
                ),
                numThreads: c.numThreads,
                provider: "cpu",
                debug: 0,
                modelType: modelTypeStr
            )
        case .zipformer2_ctc:
            onlineModel = sherpaOnnxOnlineModelConfig(
                tokens: resolved.tokens.path,
                zipformer2Ctc: sherpaOnnxOnlineZipformer2CtcModelConfig(model: resolved.model!.path),
                numThreads: c.numThreads,
                provider: "cpu",
                debug: 0,
                modelType: modelTypeStr
            )
        case .nemo_ctc:
            onlineModel = sherpaOnnxOnlineModelConfig(
                tokens: resolved.tokens.path,
                nemoCtc: sherpaOnnxOnlineNemoCtcModelConfig(model: resolved.model!.path),
                numThreads: c.numThreads,
                provider: "cpu",
                debug: 0,
                modelType: modelTypeStr
            )
        }

        let feat = sherpaOnnxFeatureConfig(sampleRate: c.sampleRate, featureDim: c.featureDim)

        let endpoint = sherpaOnnxOnlineEndpointConfig(
            rule1MinTrailingSilence: c.endpointRules.rule1MinTrailingSilenceSec,
            rule2MinTrailingSilence: c.endpointRules.rule2MinTrailingSilenceSec,
            rule3MinUtteranceLength: c.endpointRules.rule3MinUtteranceLengthSec
        )

        // 高级特性
        let lm: SherpaOnnxOnlineLMConfig = {
            if let path = c.lmModelPath {
                return sherpaOnnxOnlineLMConfig(model: path.path, scale: c.lmScale)
            }
            return SherpaOnnxOnlineLMConfig()
        }()
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
            lmConfig: lm,
            endpointConfig: endpoint,
            enableEndpoint: c.enableEndpoint,
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
