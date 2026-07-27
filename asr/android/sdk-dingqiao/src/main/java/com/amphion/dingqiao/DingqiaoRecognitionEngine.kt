package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import com.amphion.asr.AmphionRuntime
import com.amphion.police.PoliceEnhancePipeline
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
 * 声纹策略（鼎桥交付约定）：始终回调增强文本与 [SpeechRecognitionResult.speakerSimilarity]，
 * 不在 SDK 内丢弃非目标说话人结果。
 */
internal class DingqiaoRecognitionEngine(
    private val appContext: Context,
    private val createParams: CreateEngineParams,
    private val voiceprintStore: VoiceprintStore,
    private val speakerModelPath: String?,
    private val callbackExecutor: ExecutorService,
    private val onShutdown: (SpeechRecognitionEngine) -> Unit,
) : SpeechRecognitionEngine {

    /**
     * 鼎桥交付默认启用全国 V2 后处理（车牌/派出所/术语）。V2 仅在此处显式打开，三个 prefs 全局
     * 默认仍为 false（内部 sample 等不受影响）；如需回退到 V1，将下面三个 *V2Enabled 改回 false 即可。
     * normalize 默认全开、FST 默认关，与交付基线一致。
     */
    private val enhancePipeline: PoliceEnhancePipeline = PoliceEnhancePipeline.create(
        context = appContext,
        plateV2Enabled = true,
        stationV2Enabled = true,
        termsV2Enabled = true,
    )
    private val destroyed = AtomicBoolean(false)
    private val callbackEpoch = CallbackEpoch()
    private val lifecycleCallbackLock = ReentrantLock(true)
    private val callbackInvocation = CallbackInvocationContext()

    @Volatile
    private var listener: RecognitionListener? = null

    @Volatile
    private var engine: AsrEngine? = null

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
    private var voiceprintEnabled = false
    private var speakerVadEnabled = false
    private var voiceprintIds: List<String> = emptyList()
    private var speechActive = false

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

            maxAudioDurationMs = DingqiaoEngineConfig.maxAudioDurationMs(params)
            enablePartial = DingqiaoEngineConfig.enablePartialResult(params)
            voiceprintEnabled = DingqiaoEngineConfig.enableVoiceprintVerification(params)
            speakerVadEnabled = DingqiaoEngineConfig.enableSpeakerVad(params)
            voiceprintIds = DingqiaoEngineConfig.voiceprintIds(params)
            finishRequested = false
            completeSent = false
            audioMsWritten = 0L
            speechActive = false

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
        currentSession.acceptPcmShort(samples)
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
        tearDownSession(cancelledEpoch)
    }

    @Synchronized
    override fun setSpeakerVadEnabled(enabled: Boolean) {
        if (staleCallbackTargetsReplacement()) return
        ensureAlive()
        val currentSession = session ?: return
        val sid = activeSessionId ?: return
        val epoch = activeEpoch
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
            speakerVadEnabled = false
            currentSession.setTargetSpeakerEnabled(voiceprintEnabled)
            notifyError(
                epoch,
                sid,
                (t as? DingqiaoEngineException)?.errorCode ?: DingqiaoErrorCode.RECOGNITION_ERROR,
                t.message ?: "setSpeakerVadEnabled failed",
            )
        }
    }

    override fun isBusy(): Boolean = listening

    override fun shutdown() = lifecycleCallbackLock.withLock {
        synchronized(this) { shutdownLocked(force = false) }
    }

    internal fun invalidateFromRuntime() = lifecycleCallbackLock.withLock {
        synchronized(this) { shutdownLocked(force = true) }
    }

    private fun shutdownLocked(force: Boolean) {
        if (!force && staleCallbackTargetsReplacement()) return
        if (!destroyed.compareAndSet(false, true)) return
        try {
            val shutdownEpoch = activeEpoch
            try {
                tearDownSession(shutdownEpoch)
            } catch (_: Throwable) {
            }
            try {
                engine?.close()
            } catch (_: Throwable) {
            }
            engine = null
            try {
                enhancePipeline.close()
            } catch (_: Throwable) {
            }
        } finally {
            onShutdown(this)
        }
    }

    /**
     * 引擎只在 createEngine 阶段构建一次：recognizer / VAD / 声纹模型都是 engine 级资源，
     * 不随会话参数变化。vadEnd 与 speaker VAD 窗口等运行时阈值改为通过 [com.amphion.asr.SessionConfig]
     * 逐会话生效（见 [startListening]），因此启动识别恒走快路径，不再触发 native 冷重建。
     */
    private fun buildEngine() {
        val lang = DingqiaoEngineConfig.mapLanguage(createParams.language)
        val config = DingqiaoEngineConfig.buildAsrConfig(createParams, speakerModelPath)
        engine = AmphionRuntime.create(appContext, lang, config)
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
                enqueueTerminalResult(
                    epoch = epoch,
                    sessionId = sessionId,
                    asrResult = AsrResult(text = ""),
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
                asrResult = AsrResult(text = ""),
            )
        }, STOP_FALLBACK_DELAY_MS, TimeUnit.MILLISECONDS)
    }

    private fun deliverFinal(epoch: Long, sessionId: String, result: AsrResult) {
        if (!ownsSession(epoch, sessionId) || completeSent) return
        val enhanced = enhancePipeline.enhance(result.text)
        if (result.isLast) {
            enqueueTerminalResult(epoch, sessionId, result, enhanced.text)
        } else {
            dispatchResult(
                epoch = epoch,
                sessionId = sessionId,
                asrResult = result,
                isFinal = true,
                isLast = false,
                enhancedText = enhanced.text,
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
                    completeSent = true
                    terminalCallbackSessionId = sessionId
                    val captured = listener
                    if (tearDownSession(epoch) == null) return@execute
                    captured
                }
                try {
                    callbackInvocation.withEpoch(epoch) {
                        runCatching { completionListener?.onResult(sessionId, payload) }
                    }
                } finally {
                    callbackInvocation.withEpoch(epoch) {
                        runCatching { completionListener?.onComplete(sessionId, "recognize complete") }
                    }
                    synchronized(this@DingqiaoRecognitionEngine) {
                        if (terminalCallbackSessionId == sessionId) {
                            terminalCallbackSessionId = null
                        }
                    }
                }
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
                    listener
                }
                callbackInvocation.withEpoch(epoch) {
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
        listening = false
        activeSessionId = null
        finishRequested = false
        speechActive = false
        val idleEpoch = callbackEpoch.invalidate()
        activeEpoch = idleEpoch
        try {
            oldSession?.close()
        } catch (_: Throwable) {
        }
        session = null
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
