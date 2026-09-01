import Foundation

/// iOS 鼎桥兼容引擎。
///
/// 录音仍由宿主负责；本类只接收 16 kHz / 16-bit / mono、小端序、20 ms PCM 帧。
/// 声纹、Speaker VAD 与离线说话人分离只有在公共辅助模型真实可用时才允许启动。
public final class DingqiaoRecognitionEngine: DingqiaoSpeechRecognitionEngine {
    private let createParams: DingqiaoCreateEngineParams
    private let baseConfig: AsrConfig
    private let lock = NSLock()
    private let callbackQueue = DispatchQueue(label: "com.amphion.dingqiao.ios.callback")
    private let speakerQueue = DispatchQueue(label: "com.amphion.dingqiao.ios.speaker")
    private let diarizationQueue = DispatchQueue(label: "com.amphion.dingqiao.ios.diarization")
    private let voiceprintRuntime: VoiceprintRuntime?
    private let diarizationRuntime: SpeakerDiarizationRuntime?
    private let textPostProcessor: DingqiaoTextPostProcessor?
    private let onShutdown: ((DingqiaoRecognitionEngine) -> Void)?

    private var listener: DingqiaoRecognitionListener?
    private var gate = DingqiaoLifecycleGate()
    private var activeSession: AsrSession?
    private var activeAsrEngine: AsrEngine?
    private var activeCallback: SessionCallback?
    private var activeSessionId: String?
    private var activeOptions: DingqiaoSessionOptions?
    private var audioMsWritten: Int64 = 0
    private var initialSilenceTracker: InitialSilenceTracker?
    private var engineClosed = false
    private var sessionPcm: [Float] = []
    private var speakerVadOverride: Bool?
    private var lastSpeakerVadAccepted: Bool?
    private var speakerVadBelowCount = 0
    private var nextSpeakerVadSample = 0
    private var diarizationTimelineMs = 0
    private var diarizationUtterances: [PendingDiarizationUtterance] = []
    private var shutdownNotified = false

    internal init(createParams: DingqiaoCreateEngineParams, baseConfig: AsrConfig,
                  voiceprintRuntime: VoiceprintRuntime?, diarizationRuntime: SpeakerDiarizationRuntime?,
                  textPostProcessor: DingqiaoTextPostProcessor? = nil,
                  onShutdown: ((DingqiaoRecognitionEngine) -> Void)? = nil) {
        self.createParams = createParams
        self.baseConfig = baseConfig
        self.voiceprintRuntime = voiceprintRuntime
        self.diarizationRuntime = diarizationRuntime
        self.textPostProcessor = textPostProcessor
        self.onShutdown = onShutdown
    }

    public func setListener(_ listener: DingqiaoRecognitionListener?) {
        lock.withLock { self.listener = listener }
    }

    public func startListening(_ params: DingqiaoStartParams) {
        do {
            let options = try DingqiaoParameterPolicy.parse(create: createParams, start: params)
            try DingqiaoParameterPolicy.validateRuntimeCapabilities(
                options, policeEnhancementAvailable: false
            )
            let sessionVoiceprintRuntime: VoiceprintRuntime?
            if options.enableVoiceprintVerification || options.enableSpeakerVad {
                guard let voiceprintRuntime, voiceprintRuntime.isAvailable else {
                    throw DingqiaoParameterError.unsupported("voiceprint model is unavailable")
                }
                guard !options.voiceprintIds.isEmpty else {
                    throw DingqiaoParameterError.invalid("voiceprintIds must contain at least one registered ID")
                }
                sessionVoiceprintRuntime = voiceprintRuntime
            } else {
                sessionVoiceprintRuntime = nil
            }
            if options.speakerDiarizationMaxSpeakers != nil,
               diarizationRuntime?.isAvailable != true {
                throw DingqiaoParameterError.unsupported("speaker diarization models are unavailable")
            }

            // Capability failures must be reported before allocating a native recognizer/stream.
            // Once allocation succeeds, every later throwing path is paired with explicit cleanup.
            var sessionConfig = baseConfig
            sessionConfig.endpointRules.rule2MinTrailingSilenceSec = Float(options.vadEndMs) / 1_000
            sessionConfig.endpointRules.rule3MinUtteranceLengthSec = options.recognizerMode == "short"
                ? Float(options.endpointMaxUtteranceMs) / 1_000
                : -1
            let sessionEngine = try AsrEngine(config: sessionConfig)
            let callback = SessionCallback(sessionId: params.sessionId)
            callback.owner = self
            let session = sessionEngine.newSession(callback: callback)
            guard session.isReady else {
                session.close()
                sessionEngine.close()
                throw DingqiaoParameterError.invalid("failed to create native ASR stream")
            }
            if let voiceprintRuntime = sessionVoiceprintRuntime {
                session.setFinalTransformer { result, pcm in
                    guard !result.text.isEmpty || !result.tokens.isEmpty else { return result }
                    return result.withSpeakerSimilarity(
                        voiceprintRuntime.similarity(samples: pcm, ids: options.voiceprintIds))
                }
            }
            do {
                try lock.withLock {
                    guard !engineClosed else { throw DingqiaoParameterError.invalid("engine is destroyed") }
                    try gate.start(sessionId: params.sessionId)
                    activeAsrEngine = sessionEngine
                    activeSession = session
                    activeCallback = callback
                    activeSessionId = params.sessionId
                    activeOptions = options
                    audioMsWritten = 0
                    initialSilenceTracker = options.vadBeginMs.map { InitialSilenceTracker(timeoutMs: $0) }
                    sessionPcm.removeAll(keepingCapacity: true)
                    speakerVadOverride = nil
                    lastSpeakerVadAccepted = nil
                    speakerVadBelowCount = 0
                    nextSpeakerVadSample = options.speakerVadWindowMs * 16
                    diarizationTimelineMs = 0
                    diarizationUtterances.removeAll(keepingCapacity: true)
                    enqueueStartLocked(sessionId: params.sessionId)
                }
            } catch {
                session.close()
                sessionEngine.close()
                throw error
            }

        } catch {
            let code = errorCode(for: error, fallback: DingqiaoErrorCode.startListeningFailed)
            dispatchError(sessionId: params.sessionId, code: code, message: String(describing: error))
        }
    }

    public func writeAudio(sessionId: String, audio: Data) {
        if audio.isEmpty { return }
        guard audio.count == DINGQIAO_AUDIO_FRAME_BYTES_20MS else {
            dispatchError(
                sessionId: sessionId,
                code: DingqiaoErrorCode.recognitionError,
                message: "audio frame must be \(DINGQIAO_AUDIO_FRAME_BYTES_20MS) bytes"
            )
            return
        }

        var session: AsrSession?
        var shouldFinish = false
        var ignoreLateAudio = false
        var error: (Int, String)?
        lock.withLock {
            guard !engineClosed else {
                error = (DingqiaoErrorCode.engineDestroyed, "engine is destroyed")
                return
            }
            guard gate.isBusy, let activeSessionId else {
                error = (DingqiaoErrorCode.notListening, "startListening not succeeded")
                return
            }
            guard activeSessionId == sessionId else {
                error = (DingqiaoErrorCode.recognitionError, "sessionId mismatch")
                return
            }
            if gate.ignoresLateAudio(sessionId: sessionId) {
                ignoreLateAudio = true
                return
            }
            guard gate.acceptsAudio(sessionId: sessionId), let current = activeSession else {
                error = (DingqiaoErrorCode.notListening, "startListening not succeeded")
                return
            }
            session = current
            audioMsWritten += 20
            if let limit = activeOptions?.maxAudioDurationMs, limit > 0, audioMsWritten >= limit {
                shouldFinish = (try? gate.finish(sessionId: sessionId)) == .requestNativeFinish
            }
        }
        if ignoreLateAudio { return }
        if let error {
            dispatchError(sessionId: sessionId, code: error.0, message: error.1)
            return
        }

        let pcm = audio.int16LittleEndianSamples
        let floats = pcm.map { Float($0) / 32768 }
        let initialTimeout = lock.withLock { initialSilenceTracker?.observe(floats) == true }
        let speakerProbe: (samples: [Float], ids: [String], threshold: Float,
                           consecutiveBelow: Int)? = lock.withLock {
            sessionPcm.append(contentsOf: floats)
            guard let options = activeOptions,
                  speakerVadOverride ?? options.enableSpeakerVad,
                  !options.voiceprintIds.isEmpty,
                  sessionPcm.count >= nextSpeakerVadSample else { return nil }
            let windowSamples = options.speakerVadWindowMs * 16
            guard sessionPcm.count >= windowSamples else { return nil }
            let window = Array(sessionPcm.suffix(windowSamples))
            nextSpeakerVadSample += options.speakerVadHopMs * 16
            return (window, options.voiceprintIds, options.speakerVadThreshold,
                    options.speakerVadConsecutiveBelow)
        }
        if let speakerProbe { evaluateSpeakerVad(sessionId: sessionId, probe: speakerProbe) }
        session?.acceptPcm(pcm, sampleRate: 16_000)
        if initialTimeout {
            let request = lock.withLock { (try? gate.finish(sessionId: sessionId)) == .requestNativeFinish }
            if request { session?.stop() }
            return
        }
        if shouldFinish { session?.stop() }
    }

    public func finish(sessionId: String) {
        do {
            let action: DingqiaoLifecycleAction = try lock.withLock {
                guard !engineClosed else { throw DingqiaoParameterError.invalid("engine is destroyed") }
                return try gate.finish(sessionId: sessionId)
            }
            if action == .requestNativeFinish {
                lock.withLock { activeSession }?.stop()
            }
        } catch {
            dispatchError(
                sessionId: sessionId,
                code: errorCode(for: error, fallback: DingqiaoErrorCode.finishFailed),
                message: String(describing: error)
            )
        }
    }

    public func cancel(sessionId: String) {
        do {
            var session: AsrSession?
            var sessionEngine: AsrEngine?
            let action: DingqiaoLifecycleAction = try lock.withLock {
                guard !engineClosed else { throw DingqiaoParameterError.invalid("engine is destroyed") }
                let action = try gate.cancel(sessionId: sessionId)
                if action == .closeWithoutCallbacks {
                    session = activeSession
                    sessionEngine = activeAsrEngine
                    clearActiveLocked()
                }
                return action
            }
            if action == .closeWithoutCallbacks {
                session?.close()
                sessionEngine?.close()
            }
        } catch {
            dispatchError(
                sessionId: sessionId,
                code: errorCode(for: error, fallback: DingqiaoErrorCode.cancelFailed),
                message: String(describing: error)
            )
        }
    }

    public func setSpeakerVadEnabled(_ enabled: Bool) {
        let error: (String, Int, String)? = lock.withLock {
            guard let sessionId = activeSessionId, let options = activeOptions else {
                return ("", DingqiaoErrorCode.notListening, "startListening not succeeded")
            }
            if enabled && (voiceprintRuntime?.isAvailable != true || options.voiceprintIds.isEmpty) {
                return (sessionId, DingqiaoErrorCode.voiceprintNotFound,
                        "Speaker VAD requires a voiceprint model and registered voiceprintIds")
            }
            speakerVadOverride = enabled
            speakerVadBelowCount = 0
            lastSpeakerVadAccepted = nil
            if enabled { nextSpeakerVadSample = sessionPcm.count + options.speakerVadWindowMs * 16 }
            return nil
        }
        if let error { dispatchError(sessionId: error.0, code: error.1, message: error.2) }
    }

    public func isBusy() -> Bool { lock.withLock { gate.isBusy } }

    public func shutdown() {
        var session: AsrSession?
        var sessionEngine: AsrEngine?
        var closeEngineNow = false
        lock.withLock {
            if engineClosed { return }
            let action = gate.shutdown()
            if action == .closeWithoutCallbacks {
                session = activeSession
                sessionEngine = activeAsrEngine
                clearActiveLocked()
            }
            if gate.isShutdown {
                engineClosed = true
                closeEngineNow = true
            }
        }
        session?.close()
        if closeEngineNow { sessionEngine?.close() }
        if closeEngineNow { notifyShutdownOnce() }
    }

    fileprivate func receivePartial(sessionId: String, result: AsrResult) {
        lock.withLock { initialSilenceTracker?.observeAsr(text: result.text, tokenCount: result.tokens.count) }
        let shouldDeliver = lock.withLock {
            (try? gate.acceptResult(sessionId: sessionId, isLast: false)) == true &&
                (activeOptions?.enablePartialResult ?? true)
        }
        guard shouldDeliver else { return }
        dispatch { listener in
            listener.onResult(
                sessionId: sessionId,
                result: DingqiaoSpeechRecognitionResult(isFinal: false, isLast: false, result: result.text)
            )
        }
    }

    fileprivate func receiveFinal(sessionId: String, result: AsrResult) {
        lock.withLock { initialSilenceTracker?.observeAsr(text: result.text, tokenCount: result.tokens.count) }
        let shouldDeliver = lock.withLock {
            (try? gate.acceptResult(sessionId: sessionId, isLast: result.isLast)) == true
        }
        guard shouldDeliver else { return }

        let speakerVadEnabled = lock.withLock {
            guard let options = activeOptions else { return false }
            return speakerVadOverride ?? options.enableSpeakerVad
        }
        let speakerVadThreshold = lock.withLock { activeOptions?.speakerVadThreshold ?? 0.35 }
        let speakerRejected = DingqiaoSpeakerVadFinalPolicy.shouldReject(
            enabled: speakerVadEnabled,
            text: result.text,
            similarity: result.speakerSimilarity,
            threshold: speakerVadThreshold
        )
        if speakerRejected {
            dispatch { listener in
                let detail = result.speakerSimilarity.map { String(format: "score=%.2f", $0) }
                    ?? "target speaker absent"
                listener.onEvent(sessionId: sessionId,
                                 eventCode: DingqiaoEventCode.speakerVadRejected,
                                 eventMessage: "speaker vad rejected: \(detail)")
            }
        }

        // Match Android/Harmony public final semantics: rejected Speaker VAD spans commit an
        // empty final; accepted text then goes through WeText ITN and punctuation. Recognition
        // evidence, tokens and PCM ownership remain unchanged.
        let publicText = speakerRejected ? "" :
            (textPostProcessor?.process(result.text) ?? result.text)
        let result = result.withText(publicText)

        let timing: (begin: Int, end: Int, id: String?) = lock.withLock {
            let begin = diarizationTimelineMs
            let durationMs = result.utterancePcmSamples * 1_000 / 16_000
            let end = begin + durationMs
            diarizationTimelineMs = end
            guard activeOptions?.speakerDiarizationMaxSpeakers != nil,
                  !result.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return (begin, end, nil)
            }
            let id = "u\(diarizationUtterances.count + 1)"
            diarizationUtterances.append(PendingDiarizationUtterance(
                utteranceId: id, rawText: result.text, text: result.text,
                beginTime: begin, endTime: end
            ))
            return (begin, end, id)
        }
        let payload = DingqiaoSpeechRecognitionResult(
            isFinal: true,
            isLast: result.isLast,
            result: result.text,
            beginTime: timing.begin,
            endTime: timing.end,
            speakerSimilarity: result.speakerSimilarity,
            targetSpeakerEnhancementApplied: result.speakerSimilarity == nil ? nil : false,
            utteranceId: timing.id
        )
        callbackQueue.async { [weak self] in
            guard let self else { return }
            let target = self.lock.withLock { self.listener }
            if result.isLast,
               let count = self.lock.withLock({ self.activeOptions?.speakerDiarizationMaxSpeakers }),
               let runtime = self.diarizationRuntime {
                let pcm = self.lock.withLock { self.sessionPcm }
                let utterances = self.lock.withLock { self.diarizationUtterances }
                self.deliverDiarizationThenTerminal(sessionId: sessionId, payload: payload,
                                                    pcm: pcm, maxSpeakers: count,
                                                    runtime: runtime, utterances: utterances,
                                                    listener: target)
                return
            }
            target?.onResult(sessionId: sessionId, result: payload)
            if result.isLast { self.finishCompletion(sessionId: sessionId, listener: target) }
        }
    }

    fileprivate func receiveError(sessionId: String, error: AsrError) {
        dispatchError(
            sessionId: sessionId,
            code: DingqiaoErrorCode.recognitionError,
            message: error.description
        )
    }

    private func finishCompletion(sessionId: String, listener target: DingqiaoRecognitionListener?) {
        var session: AsrSession?
        var sessionEngine: AsrEngine?
        let shouldComplete = lock.withLock {
            guard gate.complete(sessionId: sessionId) else { return false }
            session = activeSession
            sessionEngine = activeAsrEngine
            clearActiveLocked()
            if gate.isShutdown {
                engineClosed = true
            }
            return true
        }
        guard shouldComplete else { return }
        session?.close()
        sessionEngine?.close()
        target?.onComplete(sessionId: sessionId, eventMessage: "recognize complete")
        if lock.withLock({ engineClosed }) { notifyShutdownOnce() }
    }

    private func deliverDiarizationThenTerminal(
        sessionId: String,
        payload: DingqiaoSpeechRecognitionResult,
        pcm: [Float],
        maxSpeakers: Int,
        runtime: SpeakerDiarizationRuntime,
        utterances: [PendingDiarizationUtterance],
        listener target: DingqiaoRecognitionListener?
    ) {
        let delivery = OnceDelivery()
        let finish: (DingqiaoSpeakerDiarizationResult) -> Void = { [weak self] diarization in
            guard let self, delivery.claim() else { return }
            self.callbackQueue.async {
                let decorated = Self.decorateDiarization(diarization, utterances: utterances)
                for utterance in decorated.utterances {
                    target?.onSpeakerDiarizationUpdate(
                        sessionId: sessionId,
                        update: DingqiaoSpeakerDiarizationUpdate(
                            utteranceId: utterance.utteranceId, revision: 1,
                            speakerIndex: utterance.speakerIndex,
                            secondarySpeakerIndexes: utterance.secondarySpeakerIndexes,
                            beginTime: utterance.beginTime, endTime: utterance.endTime,
                            confidence: utterance.confidence
                        )
                    )
                }
                target?.onSpeakerDiarizationResult(sessionId: sessionId, result: decorated)
                target?.onResult(sessionId: sessionId, result: payload)
                self.finishCompletion(sessionId: sessionId, listener: target)
            }
        }
        diarizationQueue.async {
            finish(runtime.process(samples: pcm, maxSpeakers: maxSpeakers))
        }
        callbackQueue.asyncAfter(deadline: .now() + 10) {
            finish(runtime.degraded(.inferenceTimeout,
                                    "speaker diarization exceeded the 10 second finish barrier"))
        }
    }

    private static func decorateDiarization(
        _ result: DingqiaoSpeakerDiarizationResult,
        utterances: [PendingDiarizationUtterance]
    ) -> DingqiaoSpeakerDiarizationResult {
        guard !result.degraded else { return result }
        let decorated = utterances.map { utterance -> DingqiaoDiarizedUtterance in
            var overlapBySpeaker: [Int: Int] = [:]
            var covered = 0
            for turn in result.speakerTurns {
                let overlap = max(0, min(utterance.endTime, turn.endTime) -
                                  max(utterance.beginTime, turn.beginTime))
                guard overlap > 0 else { continue }
                overlapBySpeaker[turn.speakerIndex, default: 0] += overlap
                covered += overlap
            }
            let best = overlapBySpeaker.max { $0.value < $1.value }
            let speaker = best?.key ?? -1
            let secondary = overlapBySpeaker.keys.filter { $0 != speaker }.sorted()
            let confidence = covered > 0 ? Float(best?.value ?? 0) / Float(covered) : 0
            return DingqiaoDiarizedUtterance(
                utteranceId: utterance.utteranceId, rawText: utterance.rawText,
                text: utterance.text, beginTime: utterance.beginTime,
                endTime: utterance.endTime, speakerIndex: speaker,
                secondarySpeakerIndexes: secondary, confidence: confidence,
                overlap: !secondary.isEmpty
            )
        }
        return DingqiaoSpeakerDiarizationResult(
            utterances: decorated, speakerTurns: result.speakerTurns,
            speakerCount: result.speakerCount, degraded: result.degraded,
            degradedReason: result.degradedReason, degradedMessage: result.degradedMessage,
            inferenceMs: result.inferenceMs, rtf: result.rtf
        )
    }

    private func clearActiveLocked() {
        activeSession = nil
        activeAsrEngine = nil
        activeCallback = nil
        activeSessionId = nil
        activeOptions = nil
        audioMsWritten = 0
        initialSilenceTracker = nil
        sessionPcm.removeAll(keepingCapacity: true)
        speakerVadOverride = nil
        lastSpeakerVadAccepted = nil
        speakerVadBelowCount = 0
        nextSpeakerVadSample = 0
        diarizationTimelineMs = 0
        diarizationUtterances.removeAll(keepingCapacity: true)
    }

    private func evaluateSpeakerVad(
        sessionId: String,
        probe: (samples: [Float], ids: [String], threshold: Float, consecutiveBelow: Int)
    ) {
        guard let voiceprintRuntime else { return }
        speakerQueue.async { [weak self] in
            guard let self,
                  let similarity = voiceprintRuntime.similarity(samples: probe.samples, ids: probe.ids) else { return }
            self.callbackQueue.async { [weak self] in
                guard let self else { return }
                let change: Bool? = self.lock.withLock {
                    guard self.activeSessionId == sessionId, let options = self.activeOptions,
                          self.speakerVadOverride ?? options.enableSpeakerVad else { return nil }
                    let accepted: Bool?
                    if similarity >= probe.threshold {
                        self.speakerVadBelowCount = 0
                        accepted = true
                    } else {
                        self.speakerVadBelowCount += 1
                        accepted = self.speakerVadBelowCount >= probe.consecutiveBelow ? false : nil
                    }
                    guard let accepted, accepted != self.lastSpeakerVadAccepted else { return nil }
                    self.lastSpeakerVadAccepted = accepted
                    return accepted
                }
                guard let change else { return }
                let target = self.lock.withLock { self.listener }
                target?.onEvent(sessionId: sessionId, eventCode: DingqiaoEventCode.speakerVadChanged,
                                eventMessage: change ? "target speaker active" : "target speaker inactive")
            }
        }
    }

    /// 必须在持有状态锁、session 已发布时入队，防止并发 write 的结果抢在 onStart 前面。
    private func enqueueStartLocked(sessionId: String) {
        callbackQueue.async { [weak self] in
            guard let self else { return }
            let target = self.lock.withLock { self.listener }
            target?.onStart(sessionId: sessionId, eventMessage: "recognize started")
        }
    }

    private func dispatch(_ callback: @escaping (DingqiaoRecognitionListener) -> Void) {
        callbackQueue.async { [weak self] in
            guard let self else { return }
            guard let listener = self.lock.withLock({ self.listener }) else { return }
            callback(listener)
        }
    }

    private func dispatchError(sessionId: String, code: Int, message: String) {
        dispatch { $0.onError(sessionId: sessionId, errorCode: code, errorMessage: message) }
    }

    private func notifyShutdownOnce() {
        let shouldNotify = lock.withLock { () -> Bool in
            guard !shutdownNotified else { return false }
            shutdownNotified = true
            return true
        }
        if shouldNotify { onShutdown?(self) }
    }

    private func errorCode(for error: Error, fallback: Int) -> Int {
        guard let parameter = error as? DingqiaoParameterError else { return fallback }
        switch parameter {
        case .unsupported: return DingqiaoErrorCode.engineNotInitialized
        case .invalid(let message):
            if message == "engine is busy" { return DingqiaoErrorCode.engineBusy }
            if message == "engine is destroyed" { return DingqiaoErrorCode.engineDestroyed }
            return fallback
        }
    }
}

private struct PendingDiarizationUtterance {
    let utteranceId: String
    let rawText: String
    let text: String
    let beginTime: Int
    let endTime: Int
}

internal enum DingqiaoSpeakerVadFinalPolicy {
    static func shouldReject(enabled: Bool, text: String, similarity: Float?, threshold: Float) -> Bool {
        guard enabled, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let similarity else { return false }
        return similarity < threshold
    }
}

private final class OnceDelivery {
    private let lock = NSLock()
    private var delivered = false
    func claim() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !delivered else { return false }
        delivered = true
        return true
    }
}

private final class SessionCallback: AsrCallback {
    let sessionId: String
    weak var owner: DingqiaoRecognitionEngine?

    init(sessionId: String) { self.sessionId = sessionId }

    func onPartial(result: AsrResult) { owner?.receivePartial(sessionId: sessionId, result: result) }
    func onFinal(result: AsrResult) { owner?.receiveFinal(sessionId: sessionId, result: result) }
    func onError(_ error: AsrError) { owner?.receiveError(sessionId: sessionId, error: error) }
    func onSessionStarted() {}
    func onSessionStopped() {}
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}

private extension Data {
    var int16LittleEndianSamples: [Int16] {
        var samples: [Int16] = []
        samples.reserveCapacity(count / 2)
        var index = startIndex
        while index < endIndex {
            let low = UInt16(self[index])
            let highIndex = self.index(after: index)
            let high = UInt16(self[highIndex]) << 8
            samples.append(Int16(bitPattern: low | high))
            index = self.index(after: highIndex)
        }
        return samples
    }
}
