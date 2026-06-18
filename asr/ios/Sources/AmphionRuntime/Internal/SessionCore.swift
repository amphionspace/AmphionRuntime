import Foundation
import SherpaOnnxBridge

/// 与 Android `SessionImpl` 行为对齐：把 OpaquePointer<OnlineStream> 包成单线程消费的 session。
internal final class SessionCore {

    private let recognizer: OpaquePointer?
    private var stream: OpaquePointer?
    private let sampleRate: Int
    private let engineHotwordsScore: Float
    private weak var callback: AsrCallback?

    private var currentHotwords: String
    private var lastPartialText: String = ""

    private var closed = false
    private var stopped = false

    private let decoderQueue: DispatchQueue
    private let callbackQueue: DispatchQueue

    init(recognizer: OpaquePointer?,
         sampleRate: Int,
         engineHotwords: String,
         engineHotwordsScore: Float,
         callback: AsrCallback) {
        self.recognizer = recognizer
        self.sampleRate = sampleRate
        self.engineHotwordsScore = engineHotwordsScore
        self.callback = callback
        self.currentHotwords = engineHotwords

        let id = ObjectIdentifier(callback as AnyObject).hashValue
        self.decoderQueue = DispatchQueue(label: "asr.decoder.\(id)")
        self.callbackQueue = DispatchQueue(label: "asr.callback.\(id)")

        if let r = recognizer {
            self.stream = SherpaOnnxCreateOnlineStreamWithHotwords(r, currentHotwords)
        }

        callbackQueue.async { [weak self] in
            self?.safeCallback { $0.onSessionStarted() }
        }
    }

    func acceptPcmInt16(samples: [Int16], sampleRate sr: Int) {
        let floats = samples.map { Float($0) / 32768.0 }
        acceptPcmFloat(samples: floats, sampleRate: sr)
    }

    func acceptPcmFloat(samples: [Float], sampleRate sr: Int) {
        if closed || stopped { return }
        if sr != sampleRate {
            postError(.sampleRateMismatch, "expected \(sampleRate), got \(sr)")
            return
        }
        decoderQueue.async { [weak self] in
            guard let self = self else { return }
            guard let r = self.recognizer, let s = self.stream else { return }
            samples.withUnsafeBufferPointer { ptr in
                SherpaOnnxOnlineStreamAcceptWaveform(s, Int32(self.sampleRate), ptr.baseAddress, Int32(samples.count))
            }
            self.drainDecoder(r: r, s: s, isFinal: false)
        }
    }

    func stop() {
        if closed { return }
        if stopped { return }
        stopped = true
        decoderQueue.async { [weak self] in
            guard let self = self else { return }
            guard let r = self.recognizer, let s = self.stream else { return }
            SherpaOnnxOnlineStreamInputFinished(s)
            self.drainDecoder(r: r, s: s, isFinal: true)
            self.callbackQueue.async {
                self.safeCallback { $0.onSessionStopped() }
            }
        }
    }

    func updateHotwords(_ words: [String], score: Float) {
        if closed { return }
        if score != engineHotwordsScore {
            Log.w("updateHotwords: requested score=\(score) differs from engine score=\(engineHotwordsScore); engine score is the one applied.")
        }
        let newHotwords = words.filter { !$0.isEmpty }.joined(separator: "\n")
        if newHotwords == currentHotwords { return }
        decoderQueue.async { [weak self] in
            guard let self = self, let r = self.recognizer else { return }
            let newStream = SherpaOnnxCreateOnlineStreamWithHotwords(r, newHotwords)
            if let old = self.stream {
                SherpaOnnxDestroyOnlineStream(old)
            }
            self.stream = newStream
            self.currentHotwords = newHotwords
            self.lastPartialText = ""
            Log.i("updateHotwords applied: \(words.count) words")
        }
    }

    func close() {
        if closed { return }
        closed = true
        decoderQueue.async { [weak self] in
            guard let self = self else { return }
            if let s = self.stream {
                SherpaOnnxDestroyOnlineStream(s)
                self.stream = nil
            }
        }
    }

    deinit { close() }

    // MARK: - decode loop

    private func drainDecoder(r: OpaquePointer, s: OpaquePointer, isFinal: Bool) {
        while SherpaOnnxIsOnlineStreamReady(r, s) == 1 {
            SherpaOnnxDecodeOnlineStream(r, s)
        }
        let isEndpoint = SherpaOnnxOnlineStreamIsEndpoint(r, s) == 1
        if isEndpoint {
            let result = readResult(r: r, s: s)
            postEndpoint()
            postFinal(result)
            SherpaOnnxOnlineStreamReset(r, s)
            lastPartialText = ""
            return
        }
        let result = readResult(r: r, s: s)
        if isFinal {
            postFinal(result)
            SherpaOnnxOnlineStreamReset(r, s)
            lastPartialText = ""
        } else if result.text != lastPartialText {
            lastPartialText = result.text
            postPartial(result)
        }
    }

    private func readResult(r: OpaquePointer, s: OpaquePointer) -> AsrResult {
        guard let raw = SherpaOnnxGetOnlineStreamResult(r, s) else {
            return AsrResult(text: "")
        }
        defer { SherpaOnnxDestroyOnlineRecognizerResult(raw) }
        let text = String(cString: raw.pointee.text)

        // tokens
        let count = Int(raw.pointee.count)
        var tokens: [String] = []
        if count > 0, let tokensPtr = raw.pointee.tokens_arr {
            for i in 0..<count {
                if let cStr = tokensPtr[i] {
                    tokens.append(String(cString: cStr))
                }
            }
        }
        var timestamps: [Float] = []
        if count > 0, let tsPtr = raw.pointee.timestamps {
            for i in 0..<count {
                timestamps.append(tsPtr[i])
            }
        }
        var probs: [Float] = []
        if count > 0, let probPtr = raw.pointee.ys_probs {
            for i in 0..<count {
                probs.append(probPtr[i])
            }
        }
        let avgProb = probs.isEmpty ? 1.0 : exp(probs.reduce(0, +) / Float(probs.count))
        let confidence = max(0.0, min(1.0, avgProb))
        let tokenConfs = probs.map { max(0.0, min(1.0, exp($0))) }
        return AsrResult(
            text: text,
            confidence: confidence,
            tokens: tokens,
            timestamps: timestamps,
            tokenConfidences: tokenConfs
        )
    }

    // MARK: - dispatch helpers

    private func postPartial(_ r: AsrResult) {
        callbackQueue.async { [weak self] in self?.safeCallback { $0.onPartial(result: r) } }
    }
    private func postFinal(_ r: AsrResult) {
        callbackQueue.async { [weak self] in self?.safeCallback { $0.onFinal(result: r) } }
    }
    private func postEndpoint() {
        callbackQueue.async { [weak self] in self?.safeCallback { $0.onEndpoint() } }
    }
    private func postError(_ code: AsrErrorCode, _ msg: String) {
        let err = AsrError(code: code, message: msg)
        callbackQueue.async { [weak self] in self?.safeCallback { $0.onError(err) } }
    }
    private func safeCallback(_ block: (AsrCallback) -> Void) {
        guard let cb = callback else { return }
        block(cb)
    }
}
