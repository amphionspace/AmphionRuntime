package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import com.amphion.asr.AmphionRuntime
import com.amphion.dingqiao.diarization.DiarizationFinishInput
import com.amphion.dingqiao.diarization.DiarizationFinishOutput
import com.amphion.dingqiao.diarization.DegradedSpeakerDiarizationSession
import com.amphion.dingqiao.diarization.SpeakerDiarizationController
import com.amphion.dingqiao.diarization.SpeakerDiarizationFinishBarrier
import com.amphion.dingqiao.diarization.SpeakerDiarizationSession
import com.amphion.dingqiao.diarization.SpeakerDiarizationSessionObserver
import com.amphion.police.PoliceEnhancePipeline
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * 鼎桥 [SpeechRecognitionEngine] 实现：
 * Amphion ASR + 可选声纹打分 + 警务三域后处理。
 *
 * 声纹策略（鼎桥交付约定）：按会话配置回调原始或增强文本，并携带
 * [SpeechRecognitionResult.speakerSimilarity]；不在 SDK 内丢弃非目标说话人结果。
 */
internal class DingqiaoRecognitionEngine(
    private val appContext: Context,
    private val createParams: CreateEngineParams,
    private val voiceprintStore: VoiceprintStore,
    private val speakerModelPath: String?,
    private val callbackExecutor: ExecutorService,
    private val onShutdown: (SpeechRecognitionEngine) -> Unit,
    private val preloadedEngine: AsrEngine? = null,
    private val injectedTextEnhancer: ((String) -> String)? = null,
) : SpeechRecognitionEngine {

    /**
     * 鼎桥交付默认启用全国 V2 后处理（车牌/派出所/术语）。V2 仅在此处显式打开，三个 prefs 全局
     * 默认仍为 false（内部 sample 等不受影响）；如需回退到 V1，将下面三个 *V2Enabled 改回 false 即可。
     * normalize 默认全开、FST 默认关，与交付基线一致。
     */
    private val enhancePipeline: PoliceEnhancePipeline? = if (injectedTextEnhancer == null) {
        PoliceEnhancePipeline.create(
            context = appContext,
            plateV2Enabled = true,
            stationV2Enabled = true,
            termsV2Enabled = true,
        ).also { pipeline ->
            pipeline.configurePersonNames(DingqiaoEngineConfig.sysGeneralLexicon(createParams))
        }
    } else {
        null
    }
    private val destroyed = AtomicBoolean(false)
    private val callbackEpoch = CallbackEpoch()
    private val lifecycleCallbackLock = ReentrantLock(true)
    private val callbackInvocation = CallbackInvocationContext()
    private val shutdownComplete = CountDownLatch(1)

    private var shutdownRequested = false
    private var terminalCallbackInProgress = false

    @Volatile
    private var listener: RecognitionListener? = null

    @Volatile
    private var engine: AsrEngine? = null

    private var activeRule3Policy: DingqiaoEngineConfig.Rule3Policy =
        DingqiaoEngineConfig.rule3Policy(createParams, null)

    @Volatile
    private var session: AsrSession? = null

    @Volatile
    private var activeSessionId: String? = null

    @Volatile
    private var listening = false

    @Volatile
    private var finishRequested = false

    @Volatile
    private var completeSent = false

    @Volatile
    private var activeEpoch = callbackEpoch.current()

    @Volatile
    private var terminalCallbackSessionId: String? = null

    private var audioMsWritten = 0L
    private var maxAudioDurationMs = 0L
    private var enablePartial = true
    private var partialRequested = true
    private var policeEnhancementEnabled = true
    private var voiceprintEnabled = false
    private var speakerVadEnabled = false
    private var voiceprintIds: List<String> = emptyList()
    private var speechActive = false
    private var speakerDiarizationSession: SpeakerDiarizationController? = null
    private var speakerDiarizationFinishBarrier:
        SpeakerDiarizationFinishBarrier<SpeechRecognitionResult, SpeakerDiarizationResult>? = null
    private var diarizationTerminalClaimed = false
    @Volatile
    private var diarizationQuiescent = CountDownLatch(0)

    init {
        try {
            buildEngine()
        } catch (t: Throwable) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.CREATE_ENGINE_FAILED,
                "createEngine failed: ${t.message ?: t.javaClass.simpleName}",
                t,
            )
        }
    }

    @Synchronized
    override fun setListener(listener: RecognitionListener?) {
        if (staleCallbackTargetsReplacement()) return
        this.listener = listener
    }

    override fun startListening(params: StartParams) = lifecycleCallbackLock.withLock {
        synchronized(this) { startListeningLocked(params) }
    }

    private fun startListeningLocked(params: StartParams) {
        if (staleCallbackTargetsReplacement()) return
        ensureAlive()
        if (listening) {
            notifyError(
                callbackEpoch.current(),
                params.sessionId,
                DingqiaoErrorCode.ENGINE_BUSY,
                "engine is busy",
            )
            return
        }
        val epoch = callbackEpoch.beginSession()
        activeEpoch = epoch
        try {
            params.audioInfo.validate()
            params.sessionId.requireValidId()
            DingqiaoEngineConfig.validateRecognitionMode(params)
            validateVoiceprintParams(params)
            validateSpeakerDiarizationConfig(params.speakerDiarization)

            maxAudioDurationMs = DingqiaoEngineConfig.maxAudioDurationMs(params)
            partialRequested = DingqiaoEngineConfig.enablePartialResult(params)
            policeEnhancementEnabled = DingqiaoEngineConfig.enablePoliceEnhancement(params)
            voiceprintEnabled = DingqiaoEngineConfig.enableVoiceprintVerification(params)
            speakerVadEnabled = DingqiaoEngineConfig.enableSpeakerVad(params)
            // Speaker VAD only corrects committed finals. Partials remain speculative and follow
            // the caller's enablePartialResult setting for API compatibility.
            enablePartial = partialRequested
            voiceprintIds = DingqiaoEngineConfig.voiceprintIds(params)
            finishRequested = false
            completeSent = false
            audioMsWritten = 0L
            speechActive = false
            diarizationTerminalClaimed = false

            ensureRecognizerConfig(params)
            val eng = engine
                ?: throw DingqiaoEngineException(
                    DingqiaoErrorCode.START_LISTENING_FAILED,
                    "engine not ready",
                )
            val sessionConfig = DingqiaoEngineConfig.buildSessionConfig(
                params,
                speakerModelPath,
                voiceprintCapabilityProvisioned = voiceprintIds.isNotEmpty(),
            )
            val s = eng.newSession(createAsrCallback(params.sessionId, epoch), sessionConfig)
            // session 必须在 listening=true 之前对外可见：否则录音线程早到的 writeAudio
            // 会落到 session==null 的空安全调用上被静默丢弃，导致首字丢失。
            session = s
            configureVoiceprint(s)
            activeSessionId = params.sessionId
            listening = true
            params.speakerDiarization?.let { diarizationConfig ->
                val diarizationEpoch = epoch
                val diarizationSessionId = params.sessionId
                val diarizationObserver = object : SpeakerDiarizationSessionObserver {
                    override fun onUpdate(update: SpeakerDiarizationUpdate) {
                        dispatchDiarizationUpdate(diarizationEpoch, diarizationSessionId, update)
                    }

                    override fun onWindowResult(result: SpeakerDiarizationResult) {
                        dispatchDiarizationWindow(diarizationEpoch, diarizationSessionId, result)
                    }

                    override fun onFinished(result: SpeakerDiarizationResult) {
                        synchronized(this@DingqiaoRecognitionEngine) {
                            if (!ownsSessionLocked(diarizationEpoch, diarizationSessionId)) return
                            speakerDiarizationFinishBarrier?.resolveSpeaker(
                                DiarizationFinishInput(result.degraded, result),
                            )
                        }
                    }
                }
                speakerDiarizationSession = try {
                    SpeakerDiarizationSession(
                        appContext,
                        voiceprintStore.sdkWorkPath(),
                        diarizationConfig.maxSpeakers,
                        diarizationObserver,
                    )
                } catch (t: Throwable) {
                    DegradedSpeakerDiarizationSession(
                        diarizationConfig.maxSpeakers,
                        diarizationObserver,
                        SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
                        "speaker diarization initialization failed: ${t.message ?: t.javaClass.simpleName}",
                    )
                }
                speakerDiarizationFinishBarrier = SpeakerDiarizationFinishBarrier(
                    SPEAKER_DIARIZATION_FINISH_TIMEOUT_MS,
                    stopFallbackExecutor,
                    onReady = { output ->
                        completeSpeakerDiarizationSession(
                            diarizationEpoch,
                            diarizationSessionId,
                            output,
                        )
                    },
                    timeoutAsrFallback = { createSpeakerDiarizationTimeoutLastResult() },
                )
            }
            if (DiagnosticsModule.isBuildEnabled()) {
                DiagnosticsModule.beginSession(
                    params.sessionId,
                    mapOf(
                        "recognizerMode" to activeRule3Policy.mode,
                        "enablePartialResult" to partialRequested,
                        "enablePoliceEnhancement" to policeEnhancementEnabled,
                        "enableVoiceprintVerification" to voiceprintEnabled,
                        "enableSpeakerVad" to speakerVadEnabled,
                        "voiceprintIdCount" to voiceprintIds.size,
                        "vadBeginMs" to DingqiaoEngineConfig.vadBeginMs(params),
                        "vadEndMs" to DingqiaoEngineConfig.vadEndMs(params),
                        "maxAudioDurationMs" to maxAudioDurationMs,
                    ),
                )
            }
            notifyStart(epoch, params.sessionId)
            callbackInvocation.adopt(epoch)
        } catch (t: Throwable) {
            if (!callbackEpoch.isCurrent(epoch)) return
            val errorEpoch = tearDownSession(epoch) ?: return
            val code = (t as? DingqiaoEngineException)?.errorCode
                ?: DingqiaoErrorCode.START_LISTENING_FAILED
            notifyError(errorEpoch, params.sessionId, code, t.message ?: "startListening failed")
        }
    }

    @Synchronized
    override fun writeAudio(sessionId: String, audio: ByteArray) {
        if (staleCallbackTargetsReplacement()) return
        ensureAlive()
        if (!listening) {
            if (terminalCallbackSessionId == sessionId) return
            notifyError(
                callbackEpoch.current(),
                sessionId,
                DingqiaoErrorCode.NOT_LISTENING,
                "startListening not succeeded",
            )
            return
        }
        if (sessionId != activeSessionId) {
            notifyError(
                activeEpoch,
                sessionId,
                DingqiaoErrorCode.RECOGNITION_ERROR,
                "sessionId mismatch",
            )
            return
        }
        if (audio.isEmpty()) return
        if (!DingqiaoEngineConfig.isSupportedAudioFrameBytes(audio.size)) {
            notifyError(
                activeEpoch,
                sessionId,
                DingqiaoErrorCode.RECOGNITION_ERROR,
                "audio frame must be $DINGQIAO_AUDIO_FRAME_BYTES bytes",
            )
            return
        }
        if (finishRequested) return
        val epoch = activeEpoch
        val currentSession = session ?: return
        val samples = PcmIo.bytesToShortsLE(audio)
        audioMsWritten += samples.size * 1000L / 16000
        speakerDiarizationSession?.append(audio)
        currentSession.acceptPcmShort(samples)
        if (DiagnosticsModule.isBuildEnabled()) DiagnosticsModule.captureAudio(sessionId, audio)
        if (
            ownsSession(epoch, sessionId) &&
            session === currentSession &&
            !finishRequested &&
            maxAudioDurationMs > 0L &&
            audioMsWritten >= maxAudioDurationMs
        ) {
            // 达到单会话上限是正常的生命周期终止，不是错误：等价于自动 finish，
            // flush 出最终 onResult + onComplete 并清理会话，使引擎可被再次 startListening。
            finishRequested = true
            requestSpeakerDiarizationFinishLocked()
            currentSession.stop()
        }
    }

    @Synchronized
    override fun finish(sessionId: String) {
        if (staleCallbackTargetsReplacement()) return
        ensureAlive()
        if (!listening || sessionId != activeSessionId) {
            if (!listening && terminalCallbackSessionId == sessionId) return
            notifyError(callbackEpoch.current(), sessionId, DingqiaoErrorCode.FINISH_FAILED, "finish failed")
            return
        }
        finishRequested = true
        requestSpeakerDiarizationFinishLocked()
        if (DiagnosticsModule.isBuildEnabled()) {
            DiagnosticsModule.record(
                sessionId,
                "FINISH_REQUESTED",
                mapOf("audioMsWritten" to audioMsWritten),
            )
        }
        session?.stop()
    }

    override fun cancel(sessionId: String) = lifecycleCallbackLock.withLock {
        synchronized(this) { cancelLocked(sessionId) }
    }

    private fun cancelLocked(sessionId: String) {
        if (staleCallbackTargetsReplacement()) return
        ensureAlive()
        if (!listening || sessionId != activeSessionId) {
            if (!listening && terminalCallbackSessionId == sessionId) return
            notifyError(callbackEpoch.current(), sessionId, DingqiaoErrorCode.CANCEL_FAILED, "cancel failed")
            return
        }
        val cancelledEpoch = activeEpoch
        finishRequested = false
        if (DiagnosticsModule.isBuildEnabled()) {
            DiagnosticsModule.record(
                sessionId,
                "CANCEL_REQUESTED",
                mapOf("audioMsWritten" to audioMsWritten),
            )
        }
        tearDownSession(cancelledEpoch)
    }

    @Synchronized
    override fun setSpeakerVadEnabled(enabled: Boolean) {
        if (staleCallbackTargetsReplacement()) return
        ensureAlive()
        val currentSession = session ?: return
        val sid = activeSessionId ?: return
        val epoch = activeEpoch
        val speakerVadBeforeToggle = speakerVadEnabled
        try {
            if (enabled) {
                requireSpeakerModel("speaker VAD")
                val embedding = voiceprintStore.loadMergedEmbedding(voiceprintIds)
                    ?: throw DingqiaoEngineException(
                        DingqiaoErrorCode.VOICEPRINT_NOT_FOUND,
                        "voiceprint not found for speaker VAD",
                    )
                currentSession.setTargetSpeaker(embedding)
            }
            currentSession.setTargetSpeakerEnabled(voiceprintEnabled || enabled)
            currentSession.setSpeakerVadEnabled(enabled)
            speakerVadEnabled = enabled
            notifyEvent(
                epoch,
                sid,
                DingqiaoEventCode.SPEAKER_VAD_CHANGED,
                "speaker vad ${if (enabled) "enabled" else "disabled"}.",
            )
        } catch (t: Throwable) {
            val disabled = runCatching {
                currentSession.setSpeakerVadEnabled(false)
            }.isSuccess
            // A failed rollback leaves native state unknown. Preserve the last confirmed public
            // Speaker VAD state; partial delivery remains governed only by the caller's setting.
            speakerVadEnabled = if (disabled) false else speakerVadBeforeToggle
            if (disabled) currentSession.setTargetSpeakerEnabled(voiceprintEnabled)
            notifyError(
                epoch,
                sid,
                (t as? DingqiaoEngineException)?.errorCode ?: DingqiaoErrorCode.RECOGNITION_ERROR,
                t.message ?: "setSpeakerVadEnabled failed",
            )
        }
    }

    override fun isBusy(): Boolean = listening

    override fun shutdown() {
        val calledFromCallback = lifecycleCallbackLock.isHeldByCurrentThread
        val deferred = lifecycleCallbackLock.withLock {
            synchronized(this) { requestShutdownLocked(force = false) }
        }
        awaitDeferredShutdown(deferred, calledFromCallback)
    }

    internal fun invalidateFromRuntime() {
        val calledFromCallback = lifecycleCallbackLock.isHeldByCurrentThread
        val deferred = lifecycleCallbackLock.withLock {
            synchronized(this) { requestShutdownLocked(force = true) }
        }
        awaitDeferredShutdown(deferred, calledFromCallback)
    }

    private fun requestShutdownLocked(force: Boolean): Boolean {
        if (!force && staleCallbackTargetsReplacement()) return false
        if (destroyed.get()) return false
        if ((listening && finishRequested) || terminalCallbackInProgress) {
            shutdownRequested = true
            return true
        }
        completeShutdownLocked()
        return false
    }

    private fun awaitDeferredShutdown(deferred: Boolean, calledFromCallback: Boolean) {
        if (!deferred || calledFromCallback) return
        if (shutdownComplete.await(SHUTDOWN_DRAIN_TIMEOUT_SECONDS, TimeUnit.SECONDS)) return
        lifecycleCallbackLock.withLock {
            synchronized(this) { completeShutdownLocked() }
        }
    }

    private fun completeShutdownLocked() {
        if (!destroyed.compareAndSet(false, true)) return
        try {
            val shutdownEpoch = activeEpoch
            try {
                tearDownSession(shutdownEpoch)
            } catch (_: Throwable) {
            }
            // Diarization owns independent ONNX native calls. Runtime/model release must not
            // cross an in-flight call even after the public session has been invalidated.
            runCatching {
                diarizationQuiescent.await(SHUTDOWN_DRAIN_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            }
            try {
                engine?.close()
            } catch (_: Throwable) {
            }
            engine = null
            try {
                enhancePipeline?.close()
            } catch (_: Throwable) {
            }
        } finally {
            try {
                onShutdown(this)
            } finally {
                shutdownComplete.countDown()
            }
        }
    }

    /**
     * recognizer / VAD / 声纹模型是 engine 级资源。vadEnd 与 speaker VAD 窗口等纯运行时阈值通过
     * [com.amphion.asr.SessionConfig] 逐会话生效；改变 short/long 模式或 short 模式的
     * endpointMaxUtteranceMs 时才重建 recognizer，并由 Runtime 的配置兼容性检查隔离复用。
     */
    private fun buildEngine(startParams: StartParams? = null) {
        val rule3Policy = DingqiaoEngineConfig.rule3Policy(createParams, startParams)
        if (startParams == null) preloadedEngine?.let {
            engine = it
            activeRule3Policy = rule3Policy
            return
        }
        val lang = DingqiaoEngineConfig.mapLanguage(createParams.language)
        val config = DingqiaoEngineConfig.buildAsrConfig(createParams, speakerModelPath, startParams)
        engine = AmphionRuntime.create(appContext, lang, config)
        activeRule3Policy = rule3Policy
    }

    private fun ensureRecognizerConfig(startParams: StartParams) {
        val requested = DingqiaoEngineConfig.rule3Policy(createParams, startParams)
        if (requested == activeRule3Policy) return
        val previous = engine
        buildEngine(startParams)
        previous?.close()
    }

    private fun createAsrCallback(sessionId: String, epoch: Long): AsrCallback = object : AsrCallback {
        override fun onSpeechBegin() {
            synchronized(this@DingqiaoRecognitionEngine) {
                if (!ownsSessionLocked(epoch, sessionId)) return
                speechActive = true
                notifyEvent(epoch, sessionId, DingqiaoEventCode.SPEECH_BEGIN, "speech started.")
            }
        }

        override fun onInitialSilenceTimeout() {
            synchronized(this@DingqiaoRecognitionEngine) {
                if (!ownsSessionLocked(epoch, sessionId) || finishRequested) return
                val ownedSession = session ?: return
                finishRequested = true
                requestSpeakerDiarizationFinishLocked()
                ownedSession.stop()
            }
        }

        override fun onPartial(text: String) {
            if (!enablePartial) return
            dispatchResult(
                epoch = epoch,
                sessionId = sessionId,
                asrResult = AsrResult(text = text),
                isFinal = false,
                isLast = false,
            )
        }

        override fun onEndpoint() {
            synchronized(this@DingqiaoRecognitionEngine) {
                if (!ownsSessionLocked(epoch, sessionId)) return
                if (speechActive) {
                    speechActive = false
                    notifyEvent(epoch, sessionId, DingqiaoEventCode.SPEECH_END, "speech stopped.")
                }
            }
        }

        override fun onDebug(message: String) {
            notifyEvent(epoch, sessionId, DingqiaoEventCode.SPEAKER_VAD_DEBUG, message)
        }

        override fun onFinal(result: AsrResult) {
            deliverFinal(epoch, sessionId, result)
        }

        override fun onFinalRejected(result: AsrResult) {
            notifyEvent(
                epoch,
                sessionId,
                DingqiaoEventCode.SPEAKER_VAD_REJECTED,
                "speaker vad rejected final; score=${result.speakerScore ?: "n/a"}",
            )
            if (RejectedFinalLifecycle.completesSession(result.isLast)) {
                deliverFinal(
                    epoch,
                    sessionId,
                    AsrResult(text = "", speakerScore = result.speakerScore, isLast = true),
                )
            } else {
                dispatchResult(
                    epoch = epoch,
                    sessionId = sessionId,
                    asrResult = AsrResult(text = ""),
                    isFinal = true,
                    isLast = false,
                    speakerSimilarity = result.speakerScore,
                )
            }
        }

        override fun onError(error: AsrError) {
            if (!ownsSession(epoch, sessionId)) return
            val errorEpoch = tearDownSession(epoch) ?: return
            notifyError(
                errorEpoch,
                sessionId,
                DingqiaoErrorCode.RECOGNITION_ERROR,
                "${error.code}: ${error.message}",
            )
        }

        override fun onSessionStopped() {
            synchronized(this@DingqiaoRecognitionEngine) {
                if (!ownsSessionLocked(epoch, sessionId)) return
                if (finishRequested) {
                    // SessionImpl.stop() 的 onSessionStopped 可能早于后处理后的 onFinal 到达。
                    // 先短暂等待真实 final；若底层没有产出 final（例如强制达到 maxAudioDuration 时），
                    // 再补一个空的 isLast final + onComplete，保证所有正常终止路径都能闭环并释放 busy。
                    scheduleStoppedFallback(epoch, sessionId)
                    return
                }
                tearDownSession(epoch)
            }
        }
    }

    private fun scheduleStoppedFallback(epoch: Long, sessionId: String) {
        stopFallbackExecutor.schedule({
            val shouldComplete = synchronized(this@DingqiaoRecognitionEngine) {
                ownsSessionLocked(epoch, sessionId) && finishRequested && !completeSent
            }
            if (!shouldComplete) return@schedule
            enqueueTerminalResult(
                epoch = epoch,
                sessionId = sessionId,
                asrResult = AsrResult(text = "", isLast = true),
            )
        }, STOP_FALLBACK_DELAY_MS, TimeUnit.MILLISECONDS)
    }

    private fun deliverFinal(epoch: Long, sessionId: String, result: AsrResult) {
        if (!ownsSession(epoch, sessionId) || completeSent) return
        val outputText = PoliceEnhancementPolicy.finalText(
            rawText = result.text,
            enabled = policeEnhancementEnabled,
        ) { rawText ->
            injectedTextEnhancer?.invoke(rawText) ?: enhancePipeline!!.enhance(rawText).text
        }
        val diarization = synchronized(this) { speakerDiarizationSession }
        if (diarization != null) {
            val payload = resultPayload(
                asrResult = result,
                isFinal = true,
                isLast = result.isLast,
                enhancedText = outputText,
                speakerSimilarity = result.speakerScore,
            )
            val decorated = diarization.observeAsrFinal(payload, result)
            if (result.isLast) {
                synchronized(this) {
                    if (!ownsSessionLocked(epoch, sessionId) || completeSent) return
                    if (!diarizationTerminalClaimed) {
                        if (!callbackEpoch.claimTerminal(epoch)) return
                        diarizationTerminalClaimed = true
                    }
                    speakerDiarizationFinishBarrier?.resolveAsr(decorated)
                }
            } else {
                dispatchPayload(epoch, sessionId, decorated)
                diarization.asrFinalDelivered(result)
            }
        } else if (result.isLast) {
            enqueueTerminalResult(epoch, sessionId, result, outputText)
        } else {
            dispatchResult(
                epoch = epoch,
                sessionId = sessionId,
                asrResult = result,
                isFinal = true,
                isLast = false,
                enhancedText = outputText,
                speakerSimilarity = result.speakerScore,
            )
        }
    }

    private fun enqueueTerminalResult(
        epoch: Long,
        sessionId: String,
        asrResult: AsrResult,
        enhancedText: String? = null,
    ) {
        val diarization = synchronized(this) { speakerDiarizationSession }
        if (diarization != null) {
            val terminalResult = if (asrResult.isLast) asrResult else asrResult.copy(isLast = true)
            deliverFinal(epoch, sessionId, terminalResult)
            return
        }
        synchronized(this) {
            if (!ownsSessionLocked(epoch, sessionId) || completeSent) return
            if (!callbackEpoch.claimTerminal(epoch)) return
        }
        val payload = resultPayload(
            asrResult = asrResult,
            isFinal = true,
            isLast = true,
            enhancedText = enhancedText,
            speakerSimilarity = asrResult.speakerScore,
        )
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val completionListener = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId)) return@execute
                    val captured = listener
                    if (tearDownSession(epoch) == null) return@execute
                    completeSent = true
                    terminalCallbackInProgress = true
                    terminalCallbackSessionId = sessionId
                    captured
                }
                try {
                    callbackInvocation.withEpoch(epoch) {
                        if (DiagnosticsModule.isBuildEnabled()) {
                            DiagnosticsModule.record(
                                sessionId,
                                "CALLBACK_RESULT",
                                mapOf(
                                    "isFinal" to true,
                                    "isLast" to true,
                                    "text" to payload.result,
                                    "speakerSimilarity" to payload.speakerSimilarity,
                                ),
                            )
                        }
                        runCatching { completionListener?.onResult(sessionId, payload) }
                    }
                } finally {
                    callbackInvocation.withEpoch(epoch) {
                        if (DiagnosticsModule.isBuildEnabled()) {
                            DiagnosticsModule.record(sessionId, "CALLBACK_COMPLETE")
                        }
                        runCatching { completionListener?.onComplete(sessionId, "recognize complete") }
                    }
                    synchronized(this@DingqiaoRecognitionEngine) {
                        if (terminalCallbackSessionId == sessionId) {
                            terminalCallbackSessionId = null
                        }
                        terminalCallbackInProgress = false
                        if (shutdownRequested) {
                            completeShutdownLocked()
                        }
                    }
                }
            }
        }
    }

    private fun completeSpeakerDiarizationSession(
        epoch: Long,
        sessionId: String,
        output: DiarizationFinishOutput<SpeechRecognitionResult, SpeakerDiarizationResult>,
    ) {
        val completion = synchronized(this) {
            if (!ownsSessionLocked(epoch, sessionId) || completeSent) return
            if (!diarizationTerminalClaimed) {
                if (!callbackEpoch.claimTerminal(epoch)) return
                diarizationTerminalClaimed = true
            }
            val diarization = speakerDiarizationSession ?: return
            var result = output.speaker ?: diarization.bestResult(
                SpeakerDiarizationDegradedReason.FINISH_TIMEOUT,
                "speaker diarization finish timeout",
            )
            if (output.degraded && !result.degraded) {
                result = result.copy(
                    degraded = true,
                    degradedReason = SpeakerDiarizationDegradedReason.FINISH_TIMEOUT,
                    degradedMessage = "speaker diarization finish timeout",
                )
            }
            Triple(diarization.decoratePayload(output.asr), result.copy(isSessionFinal = true), listener)
        }
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId)) return@execute
                    val current = completion.third
                    if (tearDownSession(epoch) == null) return@execute
                    completeSent = true
                    terminalCallbackInProgress = true
                    terminalCallbackSessionId = sessionId
                    current
                }
                try {
                    callbackInvocation.withEpoch(epoch) {
                        if (DiagnosticsModule.isBuildEnabled()) {
                            DiagnosticsModule.record(
                                sessionId,
                                "CALLBACK_RESULT",
                                mapOf(
                                    "isFinal" to true,
                                    "isLast" to true,
                                    "text" to completion.first.result,
                                    "speakerSimilarity" to completion.first.speakerSimilarity,
                                    "speakerDiarizationDegraded" to completion.second.degraded,
                                    "speakerCount" to completion.second.speakerCount,
                                ),
                            )
                        }
                        runCatching { captured?.onResult(sessionId, completion.first) }
                        runCatching { captured?.onSpeakerDiarizationResult(sessionId, completion.second) }
                    }
                } finally {
                    callbackInvocation.withEpoch(epoch) {
                        if (DiagnosticsModule.isBuildEnabled()) {
                            DiagnosticsModule.record(sessionId, "CALLBACK_COMPLETE")
                        }
                        runCatching { captured?.onComplete(sessionId, "recognize complete") }
                    }
                    synchronized(this@DingqiaoRecognitionEngine) {
                        if (terminalCallbackSessionId == sessionId) terminalCallbackSessionId = null
                        terminalCallbackInProgress = false
                        if (shutdownRequested) completeShutdownLocked()
                    }
                }
            }
        }
    }

    private fun createSpeakerDiarizationTimeoutLastResult() = SpeechRecognitionResult(
        isFinal = true,
        isLast = true,
        result = "",
    )

    private fun requestSpeakerDiarizationFinishLocked() {
        speakerDiarizationFinishBarrier?.begin()
        speakerDiarizationSession?.finish()
    }

    private fun dispatchDiarizationWindow(
        epoch: Long,
        sessionId: String,
        result: SpeakerDiarizationResult,
    ) {
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId) || completeSent) return@execute
                    listener
                }
                callbackInvocation.withEpoch(epoch) {
                    captured?.onSpeakerDiarizationResult(sessionId, result)
                }
            }
        }
    }

    private fun dispatchDiarizationUpdate(
        epoch: Long,
        sessionId: String,
        update: SpeakerDiarizationUpdate,
    ) {
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId) || completeSent) return@execute
                    listener
                }
                callbackInvocation.withEpoch(epoch) {
                    captured?.onSpeakerDiarizationUpdate(sessionId, update)
                }
            }
        }
    }

    private fun dispatchPayload(epoch: Long, sessionId: String, payload: SpeechRecognitionResult) {
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId) || completeSent) return@execute
                    listener
                }
                callbackInvocation.withEpoch(epoch) { captured?.onResult(sessionId, payload) }
            }
        }
    }

    private fun dispatchResult(
        epoch: Long,
        sessionId: String,
        asrResult: AsrResult,
        isFinal: Boolean,
        isLast: Boolean,
        enhancedText: String? = null,
        speakerSimilarity: Float? = null,
    ) {
        if (!ownsSession(epoch, sessionId) || completeSent) return
        val payload = resultPayload(
            asrResult,
            isFinal,
            isLast,
            enhancedText,
            speakerSimilarity,
        )
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId) || completeSent) return@execute
                    // Recheck at the public callback boundary so enablePartialResult=false also
                    // suppresses a partial that was already queued by the native callback.
                    if (!isFinal && !enablePartial) return@execute
                    listener
                }
                callbackInvocation.withEpoch(epoch) {
                    if (DiagnosticsModule.isBuildEnabled()) {
                        DiagnosticsModule.record(
                            sessionId,
                            "CALLBACK_RESULT",
                            mapOf(
                                "isFinal" to isFinal,
                                "isLast" to isLast,
                                "text" to payload.result,
                                "speakerSimilarity" to payload.speakerSimilarity,
                            ),
                        )
                    }
                    captured?.onResult(sessionId, payload)
                }
            }
        }
    }

    private fun resultPayload(
        asrResult: AsrResult,
        isFinal: Boolean,
        isLast: Boolean,
        enhancedText: String?,
        speakerSimilarity: Float?,
    ): SpeechRecognitionResult {
        val text = if (isFinal) enhancedText ?: asrResult.text else asrResult.text
        val begin = asrResult.timestamps.firstOrNull()?.let { (it * 1000f).toInt() }
        val end = asrResult.timestamps.lastOrNull()?.let { (it * 1000f).toInt() }
        return SpeechRecognitionResult(
            isFinal = isFinal,
            isLast = isLast,
            result = text,
            beginTime = begin,
            endTime = end,
            speakerSimilarity = if (isFinal) speakerSimilarity else null,
        )
    }

    private fun configureVoiceprint(session: AsrSession) {
        val needsVoiceprint = voiceprintEnabled || speakerVadEnabled
        if (!needsVoiceprint) {
            session.setTargetSpeakerEnabled(false)
            return
        }
        val embedding = voiceprintStore.loadMergedEmbedding(voiceprintIds)
            ?: throw IllegalStateException("voiceprint not found")
        session.setTargetSpeaker(embedding)
        session.setTargetSpeakerEnabled(needsVoiceprint)
        session.setSpeakerVadEnabled(speakerVadEnabled)
    }

    private fun validateVoiceprintParams(params: StartParams) {
        val speakerVad = DingqiaoEngineConfig.enableSpeakerVad(params)
        val voiceprint = DingqiaoEngineConfig.enableVoiceprintVerification(params)
        val ids = DingqiaoEngineConfig.voiceprintIds(params)
        if (!voiceprint && !speakerVad && ids.isEmpty()) return
        requireSpeakerModel("voiceprint capability")
        require(ids.isNotEmpty()) {
            "voiceprintIds required when enableVoiceprintVerification=true or enableSpeakerVad=true"
        }
        for (id in ids) {
            if (!voiceprintStore.exists(id)) {
                throw DingqiaoEngineException(
                    DingqiaoErrorCode.VOICEPRINT_NOT_FOUND,
                    "voiceprint not found: $id",
                )
            }
        }
    }

    private fun validateSpeakerDiarizationConfig(config: SpeakerDiarizationConfig?) {
        if (config == null) return
        require(config.maxSpeakers in 1..4) {
            "SpeakerDiarizationConfig.maxSpeakers must be in [1, 4]"
        }
    }

    private fun requireSpeakerModel(capability: String) {
        if (speakerModelPath.isNullOrBlank() || !java.io.File(speakerModelPath).isFile) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.START_LISTENING_FAILED,
                "speaker model not found; $capability requires $DINGQIAO_SPEAKER_MODEL_FILENAME",
            )
        }
    }

    @Synchronized
    private fun tearDownSession(expectedEpoch: Long): Long? {
        if (!callbackEpoch.isCurrent(expectedEpoch)) return null
        val oldSession = session
        val oldDiarization = speakerDiarizationSession
        val oldBarrier = speakerDiarizationFinishBarrier
        listening = false
        activeSessionId = null
        finishRequested = false
        policeEnhancementEnabled = true
        speechActive = false
        speakerDiarizationSession = null
        speakerDiarizationFinishBarrier = null
        diarizationTerminalClaimed = false
        val idleEpoch = callbackEpoch.invalidate()
        activeEpoch = idleEpoch
        try {
            oldSession?.close()
        } catch (_: Throwable) {
        }
        session = null
        oldBarrier?.cancel()
        if (oldDiarization != null) {
            val quiescent = CountDownLatch(1)
            diarizationQuiescent = quiescent
            oldDiarization.cancel { quiescent.countDown() }
        } else {
            diarizationQuiescent = CountDownLatch(0)
        }
        return idleEpoch
    }

    @Synchronized
    private fun ownsSession(epoch: Long, sessionId: String): Boolean =
        ownsSessionLocked(epoch, sessionId)

    private fun ownsSessionLocked(epoch: Long, sessionId: String): Boolean =
        !destroyed.get() &&
            callbackEpoch.isCurrent(epoch) &&
            listening &&
            activeEpoch == epoch &&
            activeSessionId == sessionId

    private fun ensureAlive() {
        if (destroyed.get()) {
            throw DingqiaoEngineException(DingqiaoErrorCode.ENGINE_DESTROYED, "engine destroyed")
        }
    }

    private fun notifyStart(epoch: Long, sessionId: String) {
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId)) return@execute
                    listener
                }
                callbackInvocation.withEpoch(epoch) {
                    if (DiagnosticsModule.isBuildEnabled()) {
                        DiagnosticsModule.record(sessionId, "CALLBACK_START")
                    }
                    captured?.onStart(sessionId, "startListening success.")
                }
            }
        }
    }

    private fun notifyEvent(epoch: Long, sessionId: String, code: Int, message: String) {
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (!ownsSessionLocked(epoch, sessionId)) return@execute
                    listener
                }
                callbackInvocation.withEpoch(epoch) {
                    if (DiagnosticsModule.isBuildEnabled()) {
                        DiagnosticsModule.record(
                            sessionId,
                            "CALLBACK_EVENT",
                            mapOf("eventCode" to code, "message" to message),
                        )
                    }
                    captured?.onEvent(sessionId, code, message)
                }
            }
        }
    }

    private fun notifyError(epoch: Long, sessionId: String, code: Int, message: String) {
        callbackExecutor.execute {
            lifecycleCallbackLock.withLock {
                val captured = synchronized(this@DingqiaoRecognitionEngine) {
                    if (destroyed.get() || !callbackEpoch.isCurrent(epoch)) return@execute
                    listener
                }
                callbackInvocation.withEpoch(epoch) {
                    if (DiagnosticsModule.isBuildEnabled()) {
                        DiagnosticsModule.record(
                            sessionId,
                            "CALLBACK_ERROR",
                            mapOf("errorCode" to code, "message" to message),
                        )
                    }
                    captured?.onError(sessionId, code, message)
                }
            }
        }
    }

    private fun staleCallbackTargetsReplacement(): Boolean =
        callbackInvocation.isStaleForActiveSession(activeEpoch, listening)

    private fun String.requireValidId() {
        require(isNotBlank() && matches(SESSION_ID_PATTERN)) {
            "sessionId must be non-empty alphanumeric/underscore/dash"
        }
    }

    companion object {
        private val SESSION_ID_PATTERN = Regex("""^[A-Za-z0-9_-]+$""")
        private val sharedExecutor: ExecutorService = Executors.newSingleThreadExecutor { r ->
            Thread(r, "dingqiao-callback").apply { isDaemon = true }
        }
        private val stopFallbackExecutor: ScheduledExecutorService =
            Executors.newSingleThreadScheduledExecutor { r ->
                Thread(r, "dingqiao-stop-fallback").apply { isDaemon = true }
            }
        private const val STOP_FALLBACK_DELAY_MS = 1_500L
        private const val SHUTDOWN_DRAIN_TIMEOUT_SECONDS = 60L
        private const val SPEAKER_DIARIZATION_FINISH_TIMEOUT_MS = 10_000L

        fun create(
            appContext: Context,
            params: CreateEngineParams,
            voiceprintStore: VoiceprintStore,
            speakerModelPath: String?,
            onShutdown: (SpeechRecognitionEngine) -> Unit,
        ): DingqiaoRecognitionEngine = DingqiaoRecognitionEngine(
            appContext = appContext,
            createParams = params,
            voiceprintStore = voiceprintStore,
            speakerModelPath = speakerModelPath,
            callbackExecutor = sharedExecutor,
            onShutdown = onShutdown,
        )
    }
}

internal class DingqiaoEngineException(
    val errorCode: Int,
    override val message: String,
    cause: Throwable? = null,
) : RuntimeException(message, cause)
