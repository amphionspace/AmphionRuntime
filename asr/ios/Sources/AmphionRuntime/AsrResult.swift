import Foundation

/// 与 Android `AsrResult` 一一对应。
public struct AsrResult {
    public let text: String
    public let confidence: Float
    public let tokens: [String]
    public let timestamps: [Float]
    public let tokenConfidences: [Float]
    /// 一句话或 endpoint 的最终结果。partial 结果为 false。
    public let isFinal: Bool
    /// 整个 session 的最后一条结果。普通 endpoint final 必须为 false。
    public let isLast: Bool
    /// 声纹能力启用且本条 final 可评分时返回；基础 iOS ASR 当前保持 nil。
    public let speakerSimilarity: Float?
    internal let utterancePcmSamples: Int

    public init(
        text: String,
        confidence: Float = 1.0,
        tokens: [String] = [],
        timestamps: [Float] = [],
        tokenConfidences: [Float] = [],
        isFinal: Bool = false,
        isLast: Bool = false,
        speakerSimilarity: Float? = nil,
        utterancePcmSamples: Int = 0
    ) {
        self.text = text
        self.confidence = confidence
        self.tokens = tokens
        self.timestamps = timestamps
        self.tokenConfidences = tokenConfidences
        self.isFinal = isFinal
        self.isLast = isLast
        self.speakerSimilarity = speakerSimilarity
        self.utterancePcmSamples = utterancePcmSamples
    }

    internal func withBoundary(isFinal: Bool, isLast: Bool) -> AsrResult {
        AsrResult(
            text: text,
            confidence: confidence,
            tokens: tokens,
            timestamps: timestamps,
            tokenConfidences: tokenConfidences,
            isFinal: isFinal,
            isLast: isLast,
            speakerSimilarity: speakerSimilarity,
            utterancePcmSamples: utterancePcmSamples
        )
    }

    internal func withSpeakerSimilarity(_ value: Float?) -> AsrResult {
        AsrResult(text: text, confidence: confidence, tokens: tokens, timestamps: timestamps,
                  tokenConfidences: tokenConfidences, isFinal: isFinal, isLast: isLast,
                  speakerSimilarity: value, utterancePcmSamples: utterancePcmSamples)
    }

    internal func withText(_ value: String) -> AsrResult {
        AsrResult(text: value, confidence: confidence, tokens: tokens, timestamps: timestamps,
                  tokenConfidences: tokenConfidences, isFinal: isFinal, isLast: isLast,
                  speakerSimilarity: speakerSimilarity, utterancePcmSamples: utterancePcmSamples)
    }

    internal func withUtterancePcmSamples(_ count: Int) -> AsrResult {
        AsrResult(text: text, confidence: confidence, tokens: tokens, timestamps: timestamps,
                  tokenConfidences: tokenConfidences, isFinal: isFinal, isLast: isLast,
                  speakerSimilarity: speakerSimilarity, utterancePcmSamples: count)
    }
}
