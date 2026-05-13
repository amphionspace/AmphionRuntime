import Foundation

/// 解码方式枚举；与 Android 的 `DecodingMethod` 对齐。
public enum DecodingMethod: String {
    case greedySearch = "greedy_search"
    case modifiedBeamSearch = "modified_beam_search"
}

/// 端点检测规则；与 Android `EndpointRules` 对齐，默认值跨端必须一致。
public struct EndpointRules {
    public var rule1MinTrailingSilenceSec: Float
    public var rule2MinTrailingSilenceSec: Float
    public var rule3MinUtteranceLengthSec: Float

    public init(
        rule1MinTrailingSilenceSec: Float = 2.4,
        rule2MinTrailingSilenceSec: Float = 1.2,
        rule3MinUtteranceLengthSec: Float = 20.0
    ) {
        self.rule1MinTrailingSilenceSec = rule1MinTrailingSilenceSec
        self.rule2MinTrailingSilenceSec = rule2MinTrailingSilenceSec
        self.rule3MinUtteranceLengthSec = rule3MinUtteranceLengthSec
    }
}

/// ASR 引擎配置；与 Android `AsrConfig.Builder` 一一对应。
///
/// Swift 用 builder-style fluent API 体感不强，这里改用 struct + 初始化 + 链式 with 方法。
public struct AsrConfig {

    // 必填
    public let modelDir: URL

    // 通用
    public var numThreads: Int = 2
    public var enableEndpoint: Bool = true
    public var endpointRules: EndpointRules = EndpointRules()
    public var sampleRate: Int = 16000
    public var featureDim: Int = 80

    // 解码
    public var decodingMethod: DecodingMethod = .greedySearch
    public var maxActivePaths: Int = 4

    // 热词
    public var hotwords: [String] = []
    public var hotwordsScore: Float = 1.5

    // VAD
    public var enableVad: Bool = false
    public var vadModelPath: URL? = nil

    // 高级特性
    public var homophoneLexiconPath: URL? = nil
    public var homophoneRuleFstsPath: URL? = nil
    public var itnRuleFstsPaths: [URL] = []
    public var lmModelPath: URL? = nil
    public var lmScale: Float = 0.5

    // SDK 内部追踪显式覆盖（与 Android 的 *IsExplicit 字段同义）
    internal var decodingMethodIsExplicit: Bool = false
    internal var maxActivePathsIsExplicit: Bool = false

    /// 必传 modelDir；其它字段全部默认。链式 `with*` 方法用于覆盖。
    public init(modelDir: URL) {
        self.modelDir = modelDir
    }

    // MARK: - Fluent 配置（与 Android Builder 一一对应）

    public func with(numThreads: Int) -> AsrConfig {
        precondition(numThreads >= 1 && numThreads <= 16, "numThreads must be in [1,16]")
        var c = self; c.numThreads = numThreads; return c
    }

    public func with(enableEndpoint: Bool) -> AsrConfig {
        var c = self; c.enableEndpoint = enableEndpoint; return c
    }

    public func with(endpointRules: EndpointRules) -> AsrConfig {
        var c = self; c.endpointRules = endpointRules; return c
    }

    public func with(hotwords: [String], score: Float? = nil) -> AsrConfig {
        var c = self
        c.hotwords = hotwords.filter { !$0.isEmpty }
        if let s = score { c.hotwordsScore = s }
        return c
    }

    public func with(decodingMethod: DecodingMethod) -> AsrConfig {
        var c = self
        c.decodingMethod = decodingMethod
        c.decodingMethodIsExplicit = true
        return c
    }

    public func with(maxActivePaths: Int) -> AsrConfig {
        precondition(maxActivePaths >= 1 && maxActivePaths <= 32)
        var c = self
        c.maxActivePaths = maxActivePaths
        c.maxActivePathsIsExplicit = true
        return c
    }

    public func with(enableVad: Bool, vadModelPath: URL? = nil) -> AsrConfig {
        var c = self
        c.enableVad = enableVad
        c.vadModelPath = vadModelPath
        return c
    }

    public func enableHomophoneReplacer(lexicon: URL, ruleFsts: URL) -> AsrConfig {
        var c = self
        c.homophoneLexiconPath = lexicon
        c.homophoneRuleFstsPath = ruleFsts
        return c
    }

    public func enableInverseTextNormalization(ruleFsts: [URL]) -> AsrConfig {
        precondition(!ruleFsts.isEmpty)
        var c = self
        c.itnRuleFstsPaths = ruleFsts
        return c
    }

    public func enableLmRescoring(modelPath: URL, scale: Float = 0.5) -> AsrConfig {
        var c = self
        c.lmModelPath = modelPath
        c.lmScale = scale
        return c
    }

    /// 与 Android `Builder.build()` 等价：执行 hotwords/LM ↔ decoding 协商 + fail-fast 检查。
    /// 直接由 AsrEngine 内部在创建时调用，业务方不需要显式调。
    internal func validatedAndNormalized() throws -> AsrConfig {
        let fm = FileManager.default
        var isDir: ObjCBool = false
        if !fm.fileExists(atPath: modelDir.path, isDirectory: &isDir) || !isDir.boolValue {
            throw AsrError(code: .modelDirInvalid, message: "modelDir not a directory: \(modelDir.path)")
        }
        let tokens = modelDir.appendingPathComponent("tokens.txt")
        if !fm.fileExists(atPath: tokens.path) {
            throw AsrError(code: .modelFileMissing, message: "missing tokens.txt under \(modelDir.path)")
        }

        var c = self
        let needsBeam = !c.hotwords.isEmpty || c.lmModelPath != nil
        if needsBeam {
            if !c.decodingMethodIsExplicit {
                c.decodingMethod = .modifiedBeamSearch
                c.decodingMethodIsExplicit = true
            } else if c.decodingMethod != .modifiedBeamSearch {
                throw AsrError(
                    code: .invalidArgument,
                    message: "hotwords / LM rescoring require decodingMethod=.modifiedBeamSearch"
                )
            }
        }

        // homophone 必须配对
        if (c.homophoneLexiconPath == nil) != (c.homophoneRuleFstsPath == nil) {
            throw AsrError(
                code: .invalidArgument,
                message: "enableHomophoneReplacer must be called with both lexicon and ruleFsts"
            )
        }
        return c
    }
}
