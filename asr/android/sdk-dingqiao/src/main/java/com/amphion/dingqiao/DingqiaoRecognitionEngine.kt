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
    private val terminalResultQueued = AtomicBoolean(false)

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

    override fun setListener(listener: RecognitionListener?) {
        this.listener = listener
    }

    @Synchronized
    override fun startListening(params: StartParams) {
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
            terminalResultQueued.set(false)
            audioMsWritten = 0L
            speechActive = false

            val eng = engine
                ?: throw DingqiaoEngineException(
                    DingqiaoErrorCode.START_LISTENING_FAILED,
                    "engine not ready",
                )
            val sessionConfig = DingqiaoEngineConfig.buildSessionConfig(params, speakerModelPath)
            val s = eng.newSession(createAsrCallback(params.sessionId, epoch), sessionConfig)
            // session 必须在 listening=true 之前对外可见：否则录音线程早到的 writeAudio
            // 会落到 session==null 的空安全调用上被静默丢弃，导致首字丢失。
            session = s
            configureVoiceprint(s)
            activeSessionId = params.sessionId
            listening = true
            notifyStart(epoch, params.sessionId)
        } catch (t: Throwable) {
            if (!callbackEpoch.isCurrent(epoch)) return
            val errorEpoch = tearDownSession(epoch) ?: return
            val code = (t as? DingqiaoEngineException)?.errorCode
                ?: DingqiaoErrorCode.START_LISTENING_FAILED
            notifyError(errorEpoch, params.sessionId, code, t.message ?: "startListening failed")
        }
    }

    override fun writeAudio(sessionId: String, audio: ByteArray) {
        ensureAlive()
        if (!listening) {
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

    override fun finish(sessionId: String) {
        ensureAlive()
        if (!listening || sessionId != activeSessionId) {
            notifyError(callbackEpoch.current(), sessionId, DingqiaoErrorCode.FINISH_FAILED, "finish failed")
            return
        }
        finishRequested = true
        session?.stop()
    }

    override fun cancel(sessionId: String) {
        ensureAlive()
        if (!listening || sessionId != activeSessionId) {
            notifyError(callbackEpoch.current(), sessionId, DingqiaoErrorCode.CANCEL_FAILED, "cancel failed")
            return
        }
        finishRequested = false
        tearDownSession(activeEpoch)
    }

    override fun setSpeakerVadEnabled(enabled: Boolean) {
        ensureAlive()
        speakerVadEnabled = enabled
        val currentSession = session ?: return
        val sid = activeSessionId ?: return
        val epoch = activeEpoch
        try {
            if (enabled) {
                val embedding = voiceprintStore.loadMergedEmbedding(voiceprintIds)
                    ?: throw DingqiaoEngineException(
                        DingqiaoErrorCode.VOICEPRINT_NOT_FOUND,
                        "voiceprint not found for speaker VAD",
                    )
                currentSession.setTargetSpeaker(embedding)
            }
            currentSession.setSpeakerVadEnabled(enabled)
            notifyEvent(
                epoch,
                sid,
                DingqiaoEventCode.SPEAKER_VAD_CHANGED,
                "speaker vad ${if (enabled) "enabled" else "disabled"}.",
            )
        } catch (t: Throwable) {
            speakerVadEnabled = false
            notifyError(
                epoch,
                sid,
                (t as? DingqiaoEngineException)?.errorCode ?: DingqiaoErrorCode.RECOGNITION_ERROR,
                t.message ?: "setSpeakerVadEnabled failed",
            )
        }
    }

    override fun isBusy(): Boolean = listening

    @Synchronized
    override fun shutdown() {
        if (!destroyed.compareAndSet(false, true)) return
        tearDownSession(activeEpoch)
        try {
            engine?.close()
        } catch (_: Throwable) {
        }
        engine = null
        try {
            enhancePipeline.close()
        } catch (_: Throwable) {
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
            if (!ownsSession(epoch, sessionId)) return
            speechActive = true
            notifyEvent(epoch, sessionId, DingqiaoEventCode.SPEECH_BEGIN, "speech started.")
        }

        override fun onInitialSilenceTimeout() {
            if (!ownsSession(epoch, sessionId) || finishRequested) return
            finishRequested = true
            session?.stop()
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
            if (!ownsSession(epoch, sessionId)) return
            if (speechActive) {
                speechActive = false
                notifyEvent(epoch, sessionId, DingqiaoEventCode.SPEECH_END, "speech stopped.")
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
            if (!ownsSession(epoch, sessionId)) return
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

    private fun scheduleStoppedFallback(epoch: Long, sessionId: String) {
        stopFallbackExecutor.schedule({
            if (!ownsSession(epoch, sessionId) || !finishRequested || completeSent) return@schedule
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
        if (!ownsSession(epoch, sessionId) || completeSent) return
        if (!terminalResultQueued.compareAndSet(false, true)) return
        val payload = resultPayload(
            asrResult = asrResult,
            isFinal = true,
            isLast = true,
            enhancedText = enhancedText,
            speakerSimilarity = asrResult.speakerScore,
        )
        callbackExecutor.execute {
            if (!ownsSession(epoch, sessionId)) return@execute
            runCatching {
                callbackEpoch.invokeThenIfCurrent(
                    epoch,
                    callback = { listener?.onResult(sessionId, payload) },
                    followUp = {
                        // The listener may cancel this session and publish a replacement synchronously.
                        // Only the still-owning generation may close and complete the old session.
                        if (ownsSession(epoch, sessionId)) {
                            completeSent = true
                            val completionListener = listener
                            if (tearDownSession(epoch) != null) {
                                runCatching {
                                    completionListener?.onComplete(sessionId, "recognize complete")
                                }
                            }
                        }
                    },
                )
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
            if (ownsSession(epoch, sessionId) && !completeSent) {
                listener?.onResult(sessionId, payload)
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
        session.setTargetSpeakerEnabled(voiceprintEnabled)
        session.setSpeakerVadEnabled(speakerVadEnabled)
    }

    private fun validateVoiceprintParams(params: StartParams) {
        val speakerVad = DingqiaoEngineConfig.enableSpeakerVad(params)
        val voiceprint = DingqiaoEngineConfig.enableVoiceprintVerification(params)
        if (!voiceprint && !speakerVad) return
        if (speakerVad && speakerModelPath.isNullOrBlank()) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.START_LISTENING_FAILED,
                "speaker model not found; enableSpeakerVad requires ${DINGQIAO_SPEAKER_MODEL_FILENAME}",
            )
        }
        val ids = DingqiaoEngineConfig.voiceprintIds(params)
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

    @Synchronized
    private fun tearDownSession(expectedEpoch: Long): Long? {
        if (!callbackEpoch.isCurrent(expectedEpoch)) return null
        val oldSession = session
        listening = false
        activeSessionId = null
        finishRequested = false
        speechActive = false
        terminalResultQueued.set(false)
        val idleEpoch = callbackEpoch.invalidate()
        activeEpoch = idleEpoch
        try {
            oldSession?.close()
        } catch (_: Throwable) {
        }
        session = null
        return idleEpoch
    }

    private fun ownsSession(epoch: Long, sessionId: String): Boolean =
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
            if (ownsSession(epoch, sessionId)) {
                listener?.onStart(sessionId, "startListening success.")
            }
        }
    }

    private fun notifyEvent(epoch: Long, sessionId: String, code: Int, message: String) {
        callbackExecutor.execute {
            if (ownsSession(epoch, sessionId)) {
                listener?.onEvent(sessionId, code, message)
            }
        }
    }

    private fun notifyError(epoch: Long, sessionId: String, code: Int, message: String) {
        callbackExecutor.execute {
            if (!destroyed.get() && callbackEpoch.isCurrent(epoch)) {
                listener?.onError(sessionId, code, message)
            }
        }
    }

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
        ): DingqiaoRecognitionEngine = DingqiaoRecognitionEngine(
            appContext = appContext,
            createParams = params,
            voiceprintStore = voiceprintStore,
            speakerModelPath = speakerModelPath,
            callbackExecutor = sharedExecutor,
        )
    }
}

internal class DingqiaoEngineException(
    val errorCode: Int,
    override val message: String,
    cause: Throwable? = null,
) : RuntimeException(message, cause)
