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

    private var audioMsWritten = 0L
    private var maxAudioDurationMs = 20_000L
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

    override fun startListening(params: StartParams) {
        ensureAlive()
        if (listening) {
            notifyError(params.sessionId, DingqiaoErrorCode.ENGINE_BUSY, "engine is busy")
            return
        }
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
            val sessionConfig = DingqiaoEngineConfig.buildSessionConfig(params, speakerModelPath)
            val s = eng.newSession(createAsrCallback(params.sessionId), sessionConfig)
            // session 必须在 listening=true 之前对外可见：否则录音线程早到的 writeAudio
            // 会落到 session==null 的空安全调用上被静默丢弃，导致首字丢失。
            session = s
            configureVoiceprint(s)
            activeSessionId = params.sessionId
            listening = true
            notifyStart(params.sessionId)
        } catch (t: Throwable) {
            listening = false
            activeSessionId = null
            session?.close()
            session = null
            val code = (t as? DingqiaoEngineException)?.errorCode
                ?: DingqiaoErrorCode.START_LISTENING_FAILED
            notifyError(params.sessionId, code, t.message ?: "startListening failed")
        }
    }

    override fun writeAudio(sessionId: String, audio: ByteArray) {
        ensureAlive()
        if (!listening) {
            notifyError(sessionId, DingqiaoErrorCode.NOT_LISTENING, "startListening not succeeded")
            return
        }
        if (sessionId != activeSessionId) {
            notifyError(sessionId, DingqiaoErrorCode.RECOGNITION_ERROR, "sessionId mismatch")
            return
        }
        if (audio.isEmpty()) return
        if (!DingqiaoEngineConfig.isSupportedAudioFrameBytes(audio.size)) {
            notifyError(
                sessionId,
                DingqiaoErrorCode.RECOGNITION_ERROR,
                "audio frame must be $DINGQIAO_AUDIO_FRAME_BYTES bytes",
            )
            return
        }
        if (finishRequested) return
        val samples = PcmIo.bytesToShortsLE(audio)
        audioMsWritten += samples.size * 1000L / 16000
        session?.acceptPcmShort(samples)
        if (!finishRequested && audioMsWritten >= maxAudioDurationMs) {
            // 达到单会话上限是正常的生命周期终止，不是错误：等价于自动 finish，
            // flush 出最终 onResult + onComplete 并清理会话，使引擎可被再次 startListening。
            finishRequested = true
            session?.stop()
        }
    }

    override fun finish(sessionId: String) {
        ensureAlive()
        if (!listening || sessionId != activeSessionId) {
            notifyError(sessionId, DingqiaoErrorCode.FINISH_FAILED, "finish failed")
            return
        }
        finishRequested = true
        session?.stop()
    }

    override fun cancel(sessionId: String) {
        ensureAlive()
        if (!listening || sessionId != activeSessionId) {
            notifyError(sessionId, DingqiaoErrorCode.CANCEL_FAILED, "cancel failed")
            return
        }
        finishRequested = false
        tearDownSession()
    }

    override fun setSpeakerVadEnabled(enabled: Boolean) {
        ensureAlive()
        speakerVadEnabled = enabled
        val currentSession = session ?: return
        val sid = activeSessionId ?: return
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
                sid,
                DingqiaoEventCode.SPEAKER_VAD_CHANGED,
                "speaker vad ${if (enabled) "enabled" else "disabled"}.",
            )
        } catch (t: Throwable) {
            speakerVadEnabled = false
            notifyError(
                sid,
                (t as? DingqiaoEngineException)?.errorCode ?: DingqiaoErrorCode.RECOGNITION_ERROR,
                t.message ?: "setSpeakerVadEnabled failed",
            )
        }
    }

    override fun isBusy(): Boolean = listening

    override fun shutdown() {
        if (!destroyed.compareAndSet(false, true)) return
        tearDownSession()
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

    private fun createAsrCallback(sessionId: String): AsrCallback = object : AsrCallback {
        override fun onSpeechBegin() {
            if (!listening || activeSessionId != sessionId) return
            speechActive = true
            notifyEvent(sessionId, DingqiaoEventCode.SPEECH_BEGIN, "speech started.")
        }

        override fun onInitialSilenceTimeout() {
            if (!listening || finishRequested || activeSessionId != sessionId) return
            finishRequested = true
            session?.stop()
        }

        override fun onPartial(text: String) {
            if (!enablePartial) return
            dispatchResult(
                sessionId = sessionId,
                asrResult = AsrResult(text = text),
                isFinal = false,
                isLast = false,
            )
        }

        override fun onEndpoint() {
            if (!listening || activeSessionId != sessionId) return
            if (speechActive) {
                speechActive = false
                notifyEvent(sessionId, DingqiaoEventCode.SPEECH_END, "speech stopped.")
            }
        }

        override fun onDebug(message: String) {
            notifyEvent(sessionId, DingqiaoEventCode.SPEAKER_VAD_DEBUG, message)
        }

        override fun onFinal(result: AsrResult) {
            deliverFinal(sessionId, result)
        }

        override fun onFinalRejected(result: AsrResult) {
            notifyEvent(
                sessionId,
                DingqiaoEventCode.SPEAKER_VAD_REJECTED,
                "speaker vad rejected final; score=${result.speakerScore ?: "n/a"}",
            )
            if (result.isLast) {
                dispatchResult(
                    sessionId = sessionId,
                    asrResult = AsrResult(text = ""),
                    isFinal = true,
                    isLast = true,
                )
                maybeComplete(sessionId)
                tearDownSession()
            }
        }

        override fun onError(error: AsrError) {
            notifyError(sessionId, DingqiaoErrorCode.RECOGNITION_ERROR, "${error.code}: ${error.message}")
            tearDownSession()
        }

        override fun onSessionStopped() {
            if (finishRequested) {
                // SessionImpl.stop() 的 onSessionStopped 可能早于后处理后的 onFinal 到达。
                // 先短暂等待真实 final；若底层没有产出 final（例如强制达到 maxAudioDuration 时），
                // 再补一个空的 isLast final + onComplete，保证所有正常终止路径都能闭环并释放 busy。
                scheduleStoppedFallback(sessionId)
                return
            }
            if (listening) {
                tearDownSession()
            }
        }
    }

    private fun scheduleStoppedFallback(sessionId: String) {
        stopFallbackExecutor.schedule({
            if (!listening || !finishRequested || completeSent || activeSessionId != sessionId) return@schedule
            dispatchResult(
                sessionId = sessionId,
                asrResult = AsrResult(text = ""),
                isFinal = true,
                isLast = true,
            )
            maybeComplete(sessionId)
            tearDownSession()
        }, STOP_FALLBACK_DELAY_MS, TimeUnit.MILLISECONDS)
    }

    private fun deliverFinal(sessionId: String, result: AsrResult) {
        if (!listening || activeSessionId != sessionId || completeSent) return
        val enhanced = enhancePipeline.enhance(result.text)
        val isLast = result.isLast
        dispatchResult(
            sessionId = sessionId,
            asrResult = result,
            isFinal = true,
            isLast = isLast,
            enhancedText = enhanced.text,
            speakerSimilarity = result.speakerScore,
        )
        if (isLast) {
            maybeComplete(sessionId)
            tearDownSession()
        }
    }

    private fun maybeComplete(sessionId: String) {
        if (completeSent) return
        completeSent = true
        notifyComplete(sessionId)
    }

    private fun dispatchResult(
        sessionId: String,
        asrResult: AsrResult,
        isFinal: Boolean,
        isLast: Boolean,
        enhancedText: String? = null,
        speakerSimilarity: Float? = null,
    ) {
        if (!listening || activeSessionId != sessionId || completeSent) return
        val text = if (isFinal) enhancedText ?: asrResult.text else asrResult.text
        val begin = asrResult.timestamps.firstOrNull()?.let { (it * 1000f).toInt() }
        val end = asrResult.timestamps.lastOrNull()?.let { (it * 1000f).toInt() }
        val payload = SpeechRecognitionResult(
            isFinal = isFinal,
            isLast = isLast,
            result = text,
            beginTime = begin,
            endTime = end,
            speakerSimilarity = if (isFinal) speakerSimilarity else null,
        )
        callbackExecutor.execute {
            listener?.onResult(sessionId, payload)
        }
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

    private fun tearDownSession() {
        listening = false
        activeSessionId = null
        finishRequested = false
        speechActive = false
        try {
            session?.close()
        } catch (_: Throwable) {
        }
        session = null
    }

    private fun ensureAlive() {
        if (destroyed.get()) {
            throw DingqiaoEngineException(DingqiaoErrorCode.ENGINE_DESTROYED, "engine destroyed")
        }
    }

    private fun notifyStart(sessionId: String) {
        callbackExecutor.execute {
            listener?.onStart(sessionId, "startListening success.")
        }
    }

    private fun notifyEvent(sessionId: String, code: Int, message: String) {
        callbackExecutor.execute {
            listener?.onEvent(sessionId, code, message)
        }
    }

    private fun notifyComplete(sessionId: String) {
        callbackExecutor.execute {
            listener?.onComplete(sessionId, "recognize complete")
        }
    }

    private fun notifyError(sessionId: String, code: Int, message: String) {
        callbackExecutor.execute {
            listener?.onError(sessionId, code, message)
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
