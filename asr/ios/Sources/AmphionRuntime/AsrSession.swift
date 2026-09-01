import Foundation

/// 与 Android `AsrSession` 一一对应。
///
/// 单一 session 串行接收 PCM；多个 session 之间相互独立（共用同一 Engine）。
public final class AsrSession {

    private let core: SessionCore

    internal init(core: SessionCore) {
        self.core = core
    }

    internal var isReady: Bool { core.isReady }

    internal func setFinalTransformer(_ transformer: ((AsrResult, [Float]) -> AsrResult)?) {
        core.setFinalTransformer(transformer)
    }

    /// 接收 16-bit PCM short 数组；SDK 内部会转 float。
    public func acceptPcm(_ samples: [Int16], sampleRate: Int) {
        core.acceptPcmInt16(samples: samples, sampleRate: sampleRate)
    }

    /// 接收 [-1, 1] 范围的 float PCM。
    public func acceptPcm(_ samples: [Float], sampleRate: Int) {
        core.acceptPcmFloat(samples: samples, sampleRate: sampleRate)
    }

    /// 主动结束音频输入；解码器会 flush 出最后一段 final。
    public func stop() {
        core.stop()
    }

    /// 与 Android `updateHotwords` 行为一致；score 仅一致性检查。
    public func updateHotwords(_ words: [String], score: Float = 1.5) {
        core.updateHotwords(words, score: score)
    }

    /// 释放本 session；之后所有调用都会被忽略。
    public func close() {
        core.close()
    }
}
