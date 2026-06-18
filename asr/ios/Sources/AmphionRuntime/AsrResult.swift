import Foundation

/// 与 Android `AsrResult` 一一对应。
public struct AsrResult {
    public let text: String
    public let confidence: Float
    public let tokens: [String]
    public let timestamps: [Float]
    public let tokenConfidences: [Float]

    public init(
        text: String,
        confidence: Float = 1.0,
        tokens: [String] = [],
        timestamps: [Float] = [],
        tokenConfidences: [Float] = []
    ) {
        self.text = text
        self.confidence = confidence
        self.tokens = tokens
        self.timestamps = timestamps
        self.tokenConfidences = tokenConfidences
    }
}
