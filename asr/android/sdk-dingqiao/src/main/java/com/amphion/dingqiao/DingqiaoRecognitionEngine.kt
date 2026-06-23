package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrError
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import com.amphion.asr.AmphionRuntime
import com.amphion.police.PoliceEnhancePipeline
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
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
    private var currentAsrConfig: AsrConfig? = null

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
    private var voiceprintIds: List<String> = emptyList()
    private var speechStarted = false

    init {
        try {
            rebuildEngine(startParams = null)
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
            validateVoiceprintParams(params)

            maxAudioDurationMs = DingqiaoEngineConfig.maxAudioDurationMs(params)
            enablePartial = DingqiaoEngineConfig.enablePartialResult(params)
            voiceprintEnabled = DingqiaoEngineConfig.enableVoiceprintVerification(params)
            voiceprintIds = DingqiaoEngineConfig.voiceprintIds(params)
            finishRequested = false
            completeSent = false
            audioMsWritten = 0L
            speechStarted = false
            activeSessionId = params.sessionId
            listening = true

            val eng = ensureEngineForStart(params)
            val s = eng.newSession(createAsrCallback(params.sessionId))
            session = s
            configureVoiceprint(s)
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
                "audio frame must be $DINGQIAO_AUDIO_FRAME_BYTES or $DINGQIAO_AUDIO_FRAME_BYTES_40MS bytes",
            )
            return
        }
        val samples = PcmIo.bytesToShortsLE(audio)
        audioMsWritten += samples.size * 1000L / 16000
        if (audioMsWritten > maxAudioDurationMs) {
            notifyError(sessionId, DingqiaoErrorCode.MAX_AUDIO_DURATION, "max audio duration exceeded")
            return
        }
        session?.acceptPcmShort(samples)
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

    private fun ensureEngineForStart(params: StartParams): AsrEngine {
        val desired = DingqiaoEngineConfig.buildAsrConfig(createParams, speakerModelPath, params)
        val current = engine
        if (current != null && currentAsrConfig == desired) {
            return current
        }
        return rebuildEngine(params)
    }

    private fun rebuildEngine(startParams: StartParams?): AsrEngine {
        val lang = DingqiaoEngineConfig.mapLanguage(createParams.language)
        val config = DingqiaoEngineConfig.buildAsrConfig(createParams, speakerModelPath, startParams)
        try {
            engine?.close()
        } catch (_: Throwable) {
        }
        return AmphionRuntime.create(appContext, lang, config).also {
            engine = it
            currentAsrConfig = config
        }
    }

    private fun createAsrCallback(sessionId: String): AsrCallback = object : AsrCallback {
        override fun onPartial(text: String) {
            if (!enablePartial) return
            if (!speechStarted && text.isNotEmpty()) {
                speechStarted = true
                notifyEvent(sessionId, DingqiaoEventCode.SPEECH_BEGIN, "speech started.")
            }
            dispatchResult(
                sessionId = sessionId,
                asrResult = AsrResult(text = text),
                isFinal = false,
                isLast = false,
            )
        }

        override fun onEndpoint() {
            notifyEvent(sessionId, DingqiaoEventCode.SPEECH_END, "speech stopped.")
        }

        override fun onFinal(result: AsrResult) {
            deliverFinal(sessionId, result)
        }

        override fun onFinalRejected(result: AsrResult) {
            deliverFinal(sessionId, result)
        }

        override fun onError(error: AsrError) {
            notifyError(sessionId, DingqiaoErrorCode.RECOGNITION_ERROR, "${error.code}: ${error.message}")
            tearDownSession()
        }

        override fun onSessionStopped() {
            if (finishRequested) {
                // SessionImpl.stop() 的 onSessionStopped 可能早于后处理后的 onFinal 到达。
                // 若这里提前 tearDownSession()，会关闭 postprocessor 并移除回调队列，
                // 导致业务收不到 onResult(isFinal=true, isLast=true)，主动停止就无法闭环。
                return
            }
            if (listening) {
                tearDownSession()
            }
        }
    }

    private fun deliverFinal(sessionId: String, result: AsrResult) {
        val enhanced = enhancePipeline.enhance(result.text)
        val isLast = finishRequested
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
        if (!voiceprintEnabled) {
            session.setTargetSpeakerEnabled(false)
            return
        }
        val embedding = voiceprintStore.loadMergedEmbedding(voiceprintIds)
            ?: throw IllegalStateException("voiceprint not found")
        session.setTargetSpeaker(embedding)
        session.setTargetSpeakerEnabled(true)
    }

    private fun validateVoiceprintParams(params: StartParams) {
        if (!DingqiaoEngineConfig.enableVoiceprintVerification(params)) return
        val ids = DingqiaoEngineConfig.voiceprintIds(params)
        require(ids.isNotEmpty()) { "voiceprintIds required when enableVoiceprintVerification=true" }
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
        speechStarted = false
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
