import Foundation
import SherpaOnnxBinary

/// 与 Android `SessionImpl` 行为对齐：把 OpaquePointer<OnlineStream> 包成单线程消费的 session。
internal final class SessionCore {

    private let recognizer: OpaquePointer?
    private var stream: OpaquePointer?
    private let sampleRate: Int
    private let engineHotwordsScore: Float
    // Session owns its callback for the whole public lifetime. Requiring the caller to retain the
    // callback separately makes callbacks disappear nondeterministically under ARC.
    private var callback: AsrCallback?

    private var currentHotwords: String
    private var lastPartialText: String = ""
    private var currentUtterancePcm: [Float] = []
    private var finalTransformer: ((AsrResult, [Float]) -> AsrResult)?

    private var closed = false
    private var stopped = false
    private let stateLock = NSLock()

    private let decoderQueue: DispatchQueue
    private let callbackQueue: DispatchQueue
    private let decoderQueueKey = DispatchSpecificKey<UInt8>()

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
        self.decoderQueue.setSpecific(key: decoderQueueKey, value: 1)

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
        let acceptsInput = stateLock.withLock { !closed && !stopped }
        if !acceptsInput { return }
        if sr != sampleRate {
            postError(.sampleRateMismatch, "expected \(sampleRate), got \(sr)")
            return
        }
        decoderQueue.async { [weak self] in
            guard let self = self else { return }
            guard !self.stateLock.withLock({ self.closed }) else { return }
            guard let r = self.recognizer, let s = self.stream else { return }
            samples.withUnsafeBufferPointer { ptr in
                SherpaOnnxOnlineStreamAcceptWaveform(s, Int32(self.sampleRate), ptr.baseAddress, Int32(samples.count))
            }
            self.currentUtterancePcm.append(contentsOf: samples)
            self.drainDecoder(r: r, s: s, isFinal: false)
        }
    }

    func stop() {
        let shouldStop = stateLock.withLock { () -> Bool in
            if closed || stopped { return false }
            stopped = true
            return true
        }
        if !shouldStop { return }
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
        if stateLock.withLock({ closed }) { return }
        if score != engineHotwordsScore {
            Log.w("updateHotwords: requested score=\(score) differs from engine score=\(engineHotwordsScore); engine score is the one applied.")
        }
        let newHotwords = words.filter { !$0.isEmpty }.joined(separator: "\n")
        decoderQueue.async { [weak self] in
            guard let self = self else { return }
            guard !self.stateLock.withLock({ self.closed }) else { return }
            if newHotwords == self.currentHotwords { return }
            guard let r = self.recognizer else { return }
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

    func setFinalTransformer(_ transformer: ((AsrResult, [Float]) -> AsrResult)?) {
        decoderQueue.sync { finalTransformer = transformer }
    }

    func close() {
        closeAndWait()
    }

    /// Engine 释放门禁：返回前保证所有已入队 native 调用完成且 stream 已销毁。
    func closeAndWait() {
        let shouldClose = stateLock.withLock { () -> Bool in
            if closed { return false }
            closed = true
            stopped = true
            callback = nil
            return true
        }
        if !shouldClose { return }
        let destroy = { [self] in
            if let stream {
                SherpaOnnxDestroyOnlineStream(stream)
                self.stream = nil
            }
        }
        if DispatchQueue.getSpecific(key: decoderQueueKey) != nil {
            destroy()
        } else {
            decoderQueue.sync(execute: destroy)
        }
    }

    deinit { close() }

    var isReady: Bool {
        decoderQueue.sync { stream != nil }
    }

    // MARK: - decode loop

    private func drainDecoder(r: OpaquePointer, s: OpaquePointer, isFinal: Bool) {
        while SherpaOnnxIsOnlineStreamReady(r, s) == 1 {
            SherpaOnnxDecodeOnlineStream(r, s)
        }
        let isEndpoint = SherpaOnnxOnlineStreamIsEndpoint(r, s) == 1
        if isEndpoint {
            let result = readResult(r: r, s: s)
            postEndpoint()
            // finish 与 endpoint 同一解码边界命中时，这一条就是 session tail；不能先发
            // non-last endpoint 再制造第二条空 terminal final。
            postFinal(transformFinal(result.withBoundary(isFinal: true, isLast: isFinal)))
            SherpaOnnxOnlineStreamReset(r, s)
            lastPartialText = ""
            return
        }
        let result = readResult(r: r, s: s)
        if isFinal {
            postFinal(transformFinal(result.withBoundary(isFinal: true, isLast: true)))
            SherpaOnnxOnlineStreamReset(r, s)
            lastPartialText = ""
        } else if result.text != lastPartialText {
            lastPartialText = result.text
            postPartial(result.withBoundary(isFinal: false, isLast: false))
        }
    }


    private func transformFinal(_ result: AsrResult) -> AsrResult {
        let pcm = currentUtterancePcm
        currentUtterancePcm.removeAll(keepingCapacity: true)
        let decorated = result.withUtterancePcmSamples(pcm.count)
        return finalTransformer?(decorated, pcm) ?? decorated
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
        // sherpa-onnx 1.13.1 的 public online result 不暴露 token probability。
        // 保持既有 API 默认值，不制造不存在的逐 token 置信度。
        return AsrResult(
            text: text,
            tokens: tokens,
            timestamps: timestamps
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
        guard let cb = stateLock.withLock({ callback }) else { return }
        block(cb)
    }
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
