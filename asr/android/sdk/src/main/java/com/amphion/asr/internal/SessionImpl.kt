package com.amphion.asr.internal

import android.os.Handler
import android.os.HandlerThread
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrError
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.AsrResult
import com.amphion.asr.SessionConfig
import com.amphion.asr.SpeakerVadConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerResult
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.Vad
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.exp

/**
 * 单次识别会话：一条 native [OnlineStream] + 三条专用线程。
 *
 * 线程：
 * - decoder thread "asr-decode-<id>"：串行 acceptWaveform + decode + getResult
 * - postprocess thread "asr-postprocess-<id>"：ASR final 出来之后串行做 ITN -> 标点
 *   （由 [PostProcessor] 自管）
 * - callback thread "asr-callback-<id>"：串行 dispatch 业务 callback
 *
 * 业务录音线程 -> SDK decoder -> SDK postprocess -> SDK callback -> 业务主线程，
 * 整条单链上不会出现"先收到原文 final，然后再被异步替换"的 UI 抖动。
 *
 * 指标采集：[MetricsCollector] 在关键时序点累积；onFinal 同帧构造 [com.amphion.asr.AmphionMetrics]
 * 同时打 logcat + 经回调线程 dispatch；session close 再打一份 SESSION 维度。
 */
internal class SessionImpl(
    private val engineImpl: EngineImpl,
    private val recognizer: OnlineRecognizer,
    private val vad: Vad?,
    private val sampleRate: Int,
    private val callback: AsrCallback,
    private val sessionId: Int,
    private val startupBundle: EngineStartupBundle?,
    private val sessionConfig: SessionConfig? = null,
) {

    private val closed = AtomicBoolean(false)
    private val stopped = AtomicBoolean(false)
    private val decoderSubmissionFence = DecoderSubmissionFence()

    private val decoderThread = HandlerThread("asr-decode-$sessionId").apply { start() }
    private val decoderHandler = Handler(decoderThread.looper)

    private val callbackThread = HandlerThread("asr-callback-$sessionId").apply { start() }
    private val callbackHandler = Handler(callbackThread.looper)
    private val finalCallbackOrderGate = FinalCallbackOrderGate()

    @Volatile
    private var stream: OnlineStream

    @Volatile
    private var lastPartialText: String = ""

    @Volatile
    private var currentHotwords: String = engineImpl.engineHotwords

    // -------- 目标说话人门控（形态A 输出门控）状态 --------

    /** 运行时开关；与 updateHotwords 同源可随时切换。decoder 线程读、业务线程写，故 @Volatile。 */
    @Volatile
    private var targetSpeakerEnabled: Boolean =
        engineImpl.targetSpeakerConfig?.enabledByDefault ?: false

    /** 目标说话人 VAD 开关：目标人离场时提前 endpoint。 */
    @Volatile
    private var speakerVadEnabled: Boolean =
        (sessionConfig?.speakerVad ?: engineImpl.targetSpeakerConfig?.speakerVad)
            ?.enabledByDefault ?: false

    /** 已注册目标向量（已 L2 归一）；null = 未注册。 */
    @Volatile
    private var targetEmbedding: FloatArray? = null

    /** 声纹打分器；decoder 线程独占，首次开关开启时懒加载。 */
    private var speakerVerifier: SpeakerVerifier? = null

    /** 生效的 speaker VAD 配置：优先会话级 [sessionConfig] 覆盖，否则回落 engine 级。 */
    private val effectiveSpeakerVad: SpeakerVadConfig?
        get() = sessionConfig?.speakerVad ?: engineImpl.targetSpeakerConfig?.speakerVad

    private val speakerPcmBuffers = SpeakerPcmBuffers(UTT_MAX_SAMPLES)
    private val effectiveSpeechBuffer = EffectiveSpeechBuffer(sampleRate, UTT_MAX_SAMPLES)
    private val recognizerResetGeneration = RecognizerResetGeneration()
    private val agcProcessor = StreamingAgcProcessor(sampleRate)

    /** speaker vad 打分终点按 native segment 的绝对 sample 位置推进，不依赖调用方 PCM 分块。 */
    private var svScoreScheduler: SpeakerVadScoreScheduler? = null

    /** speaker vad 状态：当前 speech 段内是否已经确认目标人出现。 */
    private var svTargetConfirmed = false

    /** speaker vad 状态：目标人确认后，连续低于阈值的窗口数量。 */
    private var svBelowCount = 0

    /** speaker vad 状态：当前 utterance 是否已被判为连续非目标，应在 final 阶段拒绝。 */
    private var svRejectCurrentUtterance = false

    /** speaker vad 状态：最近一次窗口相似度，供 rejected final 携带分数。 */
    private var svLastScore: Float? = null

    private val metrics = MetricsCollector(
        sessionId = sessionId,
        language = engineImpl.asrLanguage,
    )

    @Volatile
    private var startupBundlePending: EngineStartupBundle? = startupBundle

    // -------- VAD pipeline 状态（仅当 [vad] 非空且 [activeEpSilenceMs] > 0 时使用） --------

    /** silero VAD 的窗口大小，必须按窗口对齐喂入；当前 SDK 只用 silero。 */
    private val vadWindowSize: Int = VAD_WINDOW_SIZE

    /** VAD 检测到 speech 后多少毫秒静音就主动 endpoint；0 = 禁用主动 endpoint，只做 onset 日志。 */
    private val activeEpSilenceMs: Int =
        sessionConfig?.endpointSilenceMs ?: engineImpl.vadConfig.activeEndpointSilenceMs

    /** 首次起音前允许处理的真实 PCM 时长；0 = 禁用。 */
    private val initialSilenceTimeoutSamples: Long =
        ((sessionConfig?.initialSilenceTimeoutMs ?: 0).toLong() * sampleRate / 1000L)

    /** 声纹等慢证据场景的一次性确认窗口；没有声纹能力时忽略，并钳制到声纹最短片段。 */
    private val initialSilenceConfirmationGraceSamples: Long = run {
        val requestedMs = (sessionConfig?.initialSilenceConfirmationGraceMs ?: 0).toLong()
        val maxMs = engineImpl.targetSpeakerConfig
            ?.let { (it.minSegSec * 1000).toLong().coerceAtLeast(0L) }
            ?: 0L
        minOf(requestedMs, maxMs) * sampleRate / 1000L
    }

    /** 首次 speech onset 前已经送入 VAD 的完整窗口样本数。 */
    private var initialSilenceSamples: Long = 0L

    /** 当前超时判定边界；只有阈值附近存在连续声学活动时才会扩展一次。 */
    private var initialSilenceDeadlineSamples: Long = initialSilenceTimeoutSamples

    private var initialSilenceGraceGranted: Boolean = false

    /** 一旦检测到过 speech，本会话不再触发首段静音超时。 */
    private var initialSpeechDetected: Boolean = false

    /** 防止超时回调和后续排队音频重复触发生命周期结束。 */
    @Volatile
    private var initialSilenceTimeoutSent: Boolean = false

    /** 声能只触发有界确认，不会直接或永久标记 speech。 */
    private val initialAcousticActivity = if (
        initialSilenceTimeoutSamples > 0L && initialSilenceConfirmationGraceSamples > 0L
    ) InitialAcousticActivityTracker(sampleRate) else null

    /** 当前是否处于 speech 段内（VAD onset 后 → 主动 endpoint / hard restart 之间）。 */
    @Volatile
    private var vadSpeechActive: Boolean = false

    /** speech 段后已累计的尾部静音毫秒数。 */
    @Volatile
    private var trailingSilenceMs: Int = 0

    /** 不足 [vadWindowSize] 的余数 PCM；下次 feed 时拼回；只在 decoder 线程访问。 */
    private var vadCarry: FloatArray = FloatArray(0)

    private val postProcessor: PostProcessor =
        PostProcessor(
            sessionId = sessionId,
            itn = engineImpl.sharedItn,
            punctuation = engineImpl.sharedPunctuation,
            onProcessed = { processed, postProcessMs -> dispatchFinal(processed, postProcessMs) },
            onError = { err -> postError(err) },
        )

    init {
        stream = when (val r = NativeGuard.run("recognizer.createStream") {
            recognizer.createStream(hotwords = currentHotwords)
        }) {
            is NativeResult.Ok -> r.value
            is NativeResult.Err -> {
                quitThreadsQuietly()
                throw IllegalStateException("Failed to create stream: ${r.error.message}", r.error.cause)
            }
        }
        // 把每个 session 实际生效的热词打出来；空字符串说明这个 session 不带热词
        // （sherpa-onnx native 端会跟 recognizer 自己 init 时 encoded 的 hotwords_ 合并）
        val activeWordsPreview = if (currentHotwords.isEmpty()) {
            "<none>"
        } else {
            currentHotwords.split('\n').filter { it.isNotBlank() }.let { all ->
                "${all.size} word(s): ${all.take(5).joinToString(" / ")}" +
                    if (all.size > 5) " /..." else ""
            }
        }
        Logger.i(
            "Session #$sessionId stream created: hotwords=$activeWordsPreview " +
                "(engine score=${engineImpl.engineHotwordsScore})",
        )
        callbackHandler.post {
            safeCallback { callback.onSessionStarted() }
        }
        // 与 Harmony zhen 配置对齐：首次 stream 不做合成静音预热。ORT Session 已在 engine
        // 创建阶段完成，直接接收调用方真实 PCM，避免 session ready 后再排入额外 decode 工作。
        if (INITIAL_STREAM_WARMUP_DURATION_MS > 0) {
            decoderHandler.post { warmUpEncoder(INITIAL_STREAM_WARMUP_DURATION_MS) }
        }
    }

    val isClosed: Boolean
        get() = closed.get()

    // -------- public 方法（被 AsrSession 转发） --------

    fun acceptPcmFloat(samples: FloatArray) {
        val accepted = decoderSubmissionFence.submitActive {
            // 16-bit PCM 单声道：每个 sample 2 字节
            metrics.onPcmAccepted(samples.size * 2)
            val copy = samples.copyOf()
            decoderHandler.post {
                processAgc("agc.process") { agcProcessor.process(copy) }
            }
        }
        if (!accepted) {
            Logger.d("acceptPcmFloat dropped (closed=${closed.get()}, stopped=${stopped.get()})")
        }
    }

    fun acceptPcmShort(samples: ShortArray) {
        if (closed.get() || stopped.get()) return
        val floats = FloatArray(samples.size)
        var i = 0
        while (i < samples.size) {
            floats[i] = samples[i] / 32768f
            i++
        }
        acceptPcmFloat(floats)
    }

    fun updateHotwords(words: List<String>, score: Float) {
        if (closed.get()) {
            Logger.w("updateHotwords ignored: session closed")
            return
        }
        if (score != engineImpl.engineHotwordsScore) {
            Logger.w(
                "updateHotwords: requested score=$score differs from engine-level " +
                    "score=${engineImpl.engineHotwordsScore}; only the latter is honored. " +
                    "Recreate AsrEngine to truly change score.",
            )
        }
        val newHotwords = words.filter { it.isNotBlank() }.joinToString("\n")
        if (newHotwords == currentHotwords) {
            Logger.d("updateHotwords: identical, no-op")
            return
        }
        val submitted = decoderSubmissionFence.submitActive {
            decoderHandler.post {
                if (!processAgc("agc.flush(updateHotwords)") { agcProcessor.flush() }) {
                    return@post
                }
                val r = NativeGuard.run("recognizer.createStream(updateHotwords)") {
                    recognizer.createStream(hotwords = newHotwords)
                }
                when (r) {
                    is NativeResult.Ok -> {
                        val old = stream
                        stream = r.value
                        currentHotwords = newHotwords
                        lastPartialText = ""
                        NativeGuard.runQuietly("oldStream.release") { old.release() }
                        // 与 hardRestart 同源逻辑：stream 切换后 VAD 状态也要回到初始
                        NativeGuard.runQuietly("vad.reset(updateHotwords)") { vad?.reset() }
                        vadSpeechActive = false
                        trailingSilenceMs = 0
                        vadCarry = FloatArray(0)
                        resetSpeakerVadState()
                        speakerPcmBuffers.clearAll()
                        effectiveSpeechBuffer.reset()
                        Logger.i("updateHotwords applied: ${words.size} words")
                    }
                    is NativeResult.Err -> {
                        Logger.w("updateHotwords failed, keep old stream: ${r.error.message}")
                        postError(r.error)
                    }
                }
            }
        }
        if (!submitted) Logger.w("updateHotwords ignored: session stopped")
    }

    // -------- 目标说话人门控 public 方法（被 AsrSession 转发） --------

    fun setTargetSpeaker(embedding: FloatArray) {
        if (closed.get()) return
        targetEmbedding = embedding.copyOf()
        Logger.i("session $sessionId target speaker embedding set: dim=${embedding.size}")
    }

    fun clearTargetSpeaker() {
        targetEmbedding = null
        Logger.i("session $sessionId target speaker embedding cleared")
    }

    fun setTargetSpeakerEnabled(enabled: Boolean) {
        if (closed.get()) {
            Logger.w("setTargetSpeakerEnabled ignored: session closed")
            return
        }
        if (engineImpl.targetSpeakerConfig == null) {
            Logger.w(
                "setTargetSpeakerEnabled($enabled) ignored: AsrConfig.targetSpeaker not configured",
            )
            return
        }
        targetSpeakerEnabled = enabled
        // 懒加载 verifier 放到 decoder 线程：既不阻塞业务线程，又与段末打分共线程保证可见性。
        if (enabled) decoderHandler.post { ensureVerifier() }
    }

    fun setSpeakerVadEnabled(enabled: Boolean) {
        if (closed.get()) {
            Logger.w("setSpeakerVadEnabled ignored: session closed")
            return
        }
        val speakerVad = effectiveSpeakerVad
        if (speakerVad == null) {
            Logger.w(
                "setSpeakerVadEnabled($enabled) ignored: TargetSpeakerConfig.speakerVad not configured",
            )
            return
        }
        speakerVadEnabled = enabled
        decoderHandler.post {
            resetSpeakerVadState()
            if (enabled) ensureVerifier()
        }
    }

    fun stop() {
        decoderSubmissionFence.submitStop {
            stopped.set(true)
            decoderHandler.post {
                val agcOk = processAgc("agc.flush(stop)") { agcProcessor.flush() }
                if (agcOk) {
                    val r = NativeGuard.run("stream.inputFinished+drain") {
                        appendFinalTailSilence(FINAL_TAIL_SILENCE_MS)
                        stream.inputFinished()
                        drainDecoder(isFinal = true, restartAfterFinal = false, isLastFinal = true)
                    }
                    if (r is NativeResult.Err) {
                        postError(r.error)
                    }
                }
                // VAD 状态与 stream 同步：用户手动 stop 等价于一段语音结束
                NativeGuard.runQuietly("vad.reset(stop)") { vad?.reset() }
                vadSpeechActive = false
                trailingSilenceMs = 0
                vadCarry = FloatArray(0)
                resetSpeakerVadState()
                speakerPcmBuffers.clearAll()
                effectiveSpeechBuffer.reset()
                agcProcessor.close()
                if (finalCallbackOrderGate.requestStopped()) postSessionStopped()
            }
        }
    }

    fun close() {
        val closing = decoderSubmissionFence.submitClose {
            closed.set(true)
            decoderHandler.removeCallbacksAndMessages(null)
            decoderHandler.post {
                NativeGuard.runQuietly("stream.release") { stream.release() }
                // VAD 是 per-engine 共享的，session 关闭只 reset（清内部 buffer），不 release
                NativeGuard.runQuietly("vad.reset(close)") { vad?.reset() }
                resetSpeakerVadState()
                speakerPcmBuffers.clearAll()
                effectiveSpeechBuffer.reset()
                agcProcessor.close()
                decoderThread.quitSafely()
            }
        }
        if (!closing) return
        engineImpl.unregister(this)

        try { postProcessor.close() } catch (_: Throwable) {}

        // 派发 SESSION 维度指标（在 callback 线程上执行）
        val sessionMetrics = metrics.snapshotSession()
        metrics.emit(sessionMetrics, callback, callbackHandler)

        callbackHandler.removeCallbacksAndMessages(null)
        callbackHandler.post {
            callbackThread.quitSafely()
        }
        Logger.d("session $sessionId closed")
    }

    /** Native AGC failures become SDK errors instead of terminating the decoder Looper. */
    private inline fun processAgc(
        operation: String,
        frames: () -> List<ProcessedAudioFrame>,
    ): Boolean {
        return when (val result = NativeGuard.run(operation, frames)) {
            is NativeResult.Ok -> {
                result.value.forEach { frame -> feedAndDecode(frame) }
                true
            }
            is NativeResult.Err -> {
                postError(result.error)
                false
            }
        }
    }

    /**
     * 同步等待 decoder thread 真正退出。
     *
     * [EngineImpl.close] 在释放 per-engine vad 之前调用本方法，确保 decoder 线程上
     * 没有「正在执行的 feedAndDecode」还会去碰 vad 的 native pointer——否则会出现
     * SIGSEGV 0x0 in `Vad.isSpeechDetected`（参见 0.2.2 之前的崩溃 backtrace）。
     *
     * 时序保证：
     * 1. close() 已经 post 了 stream.release + vad.reset + decoderThread.quitSafely() 任务
     * 2. quitSafely 让 looper 处理完当前队列里所有消息后退出，从而保证 feedAndDecode 当前
     *    那一次循环跑完才让 vad 进入「随时可被 release」状态
     * 3. Thread.join(timeout) 等到 thread 真正退出（状态 TERMINATED）才返回
     *
     * @param timeoutMs 最长等待毫秒数；超时返回 false（病态 hang 时不无限阻塞 close 流程）
     */
    internal fun awaitDecoderQuit(timeoutMs: Long): Boolean {
        return try {
            decoderThread.join(timeoutMs)
            !decoderThread.isAlive
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }
    }

    // -------- decoder loop --------

    private fun warmUpEncoder(durationMs: Int) {
        if (closed.get()) return
        val n = (sampleRate.toLong() * durationMs / 1000L).toInt().coerceAtLeast(0)
        if (n == 0) return
        val silence = FloatArray(n)
        val r = NativeGuard.run("warmUpEncoder") {
            stream.acceptWaveform(silence, sampleRate)
            while (recognizer.isReady(stream)) {
                recognizer.decode(stream)
            }
            recognizer.reset(stream)
        }
        when (r) {
            is NativeResult.Ok -> {
                lastPartialText = ""
                Logger.i("session $sessionId encoder warm-up done: ${durationMs}ms silence, $n samples")
            }
            is NativeResult.Err -> Logger.w("session $sessionId encoder warm-up failed: ${r.error.message}")
        }
    }

    private fun appendFinalTailSilence(durationMs: Int) {
        val n = (sampleRate.toLong() * durationMs / 1000L).toInt().coerceAtLeast(0)
        if (n == 0) return
        // 用户松手通常正好卡在语音末尾；SDK 内部补尾静音，给流式模型足够右上下文完成 final。
        stream.acceptWaveform(FloatArray(n), sampleRate)
    }

    private fun feedAndDecode(frame: ProcessedAudioFrame) {
        var offset = 0
        val initialDecisionChunkSamples = (sampleRate / INITIAL_DECISION_CHUNKS_PER_SECOND).coerceAtLeast(1)
        while (offset < frame.raw.size && !closed.get() && !initialSilenceTimeoutSent) {
            val remaining = frame.raw.size - offset
            var chunkSize = if (!initialSpeechDetected && initialSilenceTimeoutSamples > 0L) {
                minOf(remaining, initialDecisionChunkSamples)
            } else {
                remaining
            }
            if (speakerVadEnabled) {
                effectiveSpeakerVad?.let { speakerVad ->
                    chunkSize = minOf(
                        chunkSize,
                        speakerVadScoreScheduler(speakerVad).samplesUntilNextScore(),
                    )
                }
            }
            val raw = frame.raw.copyOfRange(offset, offset + chunkSize)
            val processed = frame.processed.copyOfRange(offset, offset + chunkSize)
            if (!feedChunkAndDecode(raw, processed)) break
            offset += chunkSize
        }
    }

    /** Fixed slices prevent audio after an armed deadline from changing the decision at that deadline. */
    private fun feedChunkAndDecode(rawSamples: FloatArray, processedSamples: FloatArray): Boolean {
        if (closed.get() || initialSilenceTimeoutSent) return false
        check(rawSamples.size == processedSamples.size) { "raw/processed PCM size mismatch" }

        if (!initialSpeechDetected) initialAcousticActivity?.observe(rawSamples)

        if (targetSpeakerEnabled || speakerVadEnabled) effectiveSpeechBuffer.observe(rawSamples)
        speakerPcmBuffers.observe(
            rawSamples,
            captureSpeakerVad = speakerVadEnabled,
            captureFallback = targetSpeakerEnabled,
        )

        // 保持 PCM 全量进 ASR，让 partial 实时性不受 VAD 抖动影响。VAD 只做 gate
        // + 主动 endpoint（更敏感的尾静音切分），它们与 sherpa endpoint 规则并存：
        // 谁先触发以谁为准。
        val resetGenerationBefore = recognizerResetGeneration.snapshot()
        val asrR = NativeGuard.run("stream.acceptWaveform+drain") {
            stream.acceptWaveform(processedSamples, sampleRate)
            drainDecoder(isFinal = false)
        }
        if (asrR is NativeResult.Err) {
            postError(asrR.error)
            return false
        }

        val v = vad ?: return true
        if (recognizerResetGeneration.changedSince(resetGenerationBefore)) {
            resetVadGateState()
            return true
        }

        // silero 保持使用调用方原始 PCM，避免 AGC 改变 VAD/endpoint 分段。acceptWaveform
        // 强约束 windowSize=512；按 chunk 切片喂入，剩余样本进 vadCarry 等下次拼回。
        val merged = if (vadCarry.isEmpty()) rawSamples else vadCarry + rawSamples
        var i = 0
        var anySpeech = false
        var anySilence = false
        while (i + vadWindowSize <= merged.size) {
            val win = merged.copyOfRange(i, i + vadWindowSize)
            NativeGuard.runQuietly("vad.acceptWaveform") { v.acceptWaveform(win) }
            if (v.isSpeechDetected()) anySpeech = true else anySilence = true
            i += vadWindowSize
        }
        vadCarry = if (i < merged.size) merged.copyOfRange(i, merged.size) else FloatArray(0)

        when {
            anySpeech -> {
                effectiveSpeechBuffer.confirmSpeech()
                // 任何一个窗口看到 speech，就把累计静音清零。中间夹杂少量静音窗口
                // （正常说话时 vad 在 0.5 阈值附近抖动）不会被误判成结束。
                if (!vadSpeechActive) {
                    vadSpeechActive = true
                    Logger.d("session $sessionId VAD speech onset")
                    callbackHandler.post {
                        safeCallback { callback.onSpeechBegin() }
                    }
                }
                initialSpeechDetected = true
                trailingSilenceMs = 0
            }
            !initialSpeechDetected && !initialSilenceTimeoutSent && initialSilenceTimeoutSamples > 0L -> {
                initialSilenceSamples += i.toLong()
                if (
                    initialSilenceSamples >= initialSilenceDeadlineSamples &&
                    !initialSilenceGraceGranted &&
                    initialSilenceConfirmationGraceSamples > 0L &&
                    (initialAcousticActivity?.hasRecentActivity() == true ||
                        initialAcousticActivity?.hasSpeechLikeActivity() == true)
                ) {
                    initialSilenceGraceGranted = true
                    initialSilenceDeadlineSamples += initialSilenceConfirmationGraceSamples
                    Logger.d(
                        "session $sessionId initial silence confirmation grace granted: " +
                            "deadlineSamples=$initialSilenceDeadlineSamples",
                    )
                } else if (initialSilenceSamples >= initialSilenceDeadlineSamples) {
                    if (initialSilenceGraceGranted &&
                        initialAcousticActivity?.hasRecentSpeechLikeActivity() == true
                    ) {
                        initialSpeechDetected = true
                        initialSilenceSamples = 0L
                        Logger.d("session $sessionId initial silence disarmed by speech-like acoustic activity")
                        return true
                    }
                    if (initialSilenceGraceGranted) {
                        val probe = probeInitialSpeechAtTimeout()
                        if (probe == true) return true
                        if (probe == null) return false
                    }
                    initialSilenceTimeoutSent = true
                    Logger.i("session $sessionId VAD initial silence timeout")
                    callbackHandler.post {
                        safeCallback { callback.onInitialSilenceTimeout() }
                    }
                    return false
                }
            }
            anySilence && vadSpeechActive -> {
                // 仅在曾经有 speech 之后才累计静音；进入主动 endpoint 判定。
                trailingSilenceMs += (processedSamples.size * 1000L / sampleRate).toInt()
                if (activeEpSilenceMs > 0 && trailingSilenceMs >= activeEpSilenceMs) {
                    Logger.d(
                        "session $sessionId VAD active endpoint after ${trailingSilenceMs}ms silence",
                    )
                    vadSpeechActive = false
                    trailingSilenceMs = 0
                    triggerVadActiveEndpoint()
                }
            }
        }
        maybeTriggerSpeakerVadEndpoint(rawSamples.size)
        return true
    }

    /**
     * 声学活动只说明“可能有人说话”。有界确认窗结束时强制刷新 ASR：有 text/token 时保留为
     * non-last final 并继续 session；仍为空才允许上层按初始静音结束。
     */
    private fun probeInitialSpeechAtTimeout(): Boolean? {
        val r = NativeGuard.run("initialSilence.inputFinished+probe") {
            appendFinalTailSilence(INITIAL_SILENCE_PROBE_TAIL_MS)
            stream.inputFinished()
            drainDecoder(isFinal = true, postEndpointOnEndpoint = false, suppressEmptyFinal = true)
        }
        return when (r) {
            is NativeResult.Ok -> r.value
            is NativeResult.Err -> {
                postError(r.error)
                null
            }
        }
    }

    /**
     * VAD 检测到 speech 后尾静音 ≥ [activeEpSilenceMs] 时调用：复用 stop 路径的
     * inputFinished + drain(isFinal=true)，让当前 stream 出 final 并按结果决定硬/软重启。
     */
    private fun triggerVadActiveEndpoint() {
        if (vad == null) return
        val r = NativeGuard.run("vad.activeEndpoint") {
            stream.inputFinished()
            drainDecoder(isFinal = true)
        }
        if (r is NativeResult.Err) {
            postError(r.error)
            return
        }
        vadCarry = FloatArray(0)
        resetSpeakerVadState()
    }

    /**
     * 目标说话人离场时调用：主动派发 endpoint 事件，再复用 inputFinished + final flush 路径。
     */
    private fun triggerSpeakerVadEndpoint() {
        if (vad == null) return
        postEndpoint()
        val r = NativeGuard.run("speakerVad.activeEndpoint") {
            stream.inputFinished()
            drainDecoder(isFinal = true, postEndpointOnEndpoint = false)
        }
        if (r is NativeResult.Err) {
            postError(r.error)
            return
        }
        vadCarry = FloatArray(0)
        resetSpeakerVadState()
    }

    /**
     * 解出当前 stream 的所有结果并 dispatch；isFinal=true 时把当前残留文本作为 final 发出。
     */
    private fun drainDecoder(
        isFinal: Boolean,
        postEndpointOnEndpoint: Boolean = true,
        restartAfterFinal: Boolean = true,
        isLastFinal: Boolean = false,
        suppressEmptyFinal: Boolean = false,
    ): Boolean {
        while (recognizer.isReady(stream)) {
            recognizer.decode(stream)
        }

        if (recognizer.isEndpoint(stream)) {
            metrics.onEndpointDetected()
            val r = recognizer.getResult(stream)
            markInitialSpeechDetected(r)
            val hasEvidence = r.text.isNotEmpty() || r.tokens.isNotEmpty()
            metrics.onRawFinalReady()
            if (postEndpointOnEndpoint) postEndpoint()
            val finalResult = prepareFinal(toAsrResult(r), hasEvidence, isLastFinal)
            if ((!suppressEmptyFinal || hasEvidence) && finalResult != null) {
                postFinalToProcessor(finalResult)
            }
            if (restartAfterFinal) restartStreamAfterUtterance(r) else lastPartialText = ""
            return hasEvidence
        }

        val r = recognizer.getResult(stream)
        markInitialSpeechDetected(r)
        val hasEvidence = r.text.isNotEmpty() || r.tokens.isNotEmpty()
        if (isFinal) {
            metrics.onRawFinalReady()
            val finalResult = prepareFinal(toAsrResult(r), hasEvidence, isLastFinal)
            if ((!suppressEmptyFinal || hasEvidence) && finalResult != null) {
                postFinalToProcessor(finalResult)
            }
            if (restartAfterFinal) restartStreamAfterUtterance(r) else lastPartialText = ""
        } else if (r.text != lastPartialText) {
            lastPartialText = r.text
            postPartial(toAsrResult(r))
        }
        return hasEvidence
    }

    private fun markInitialSpeechDetected(result: OnlineRecognizerResult) {
        if (result.text.isEmpty() && result.tokens.isEmpty()) return
        initialSpeechDetected = true
        initialSilenceSamples = 0L
    }

    /**
     * endpoint / VAD 切句后是否硬重启 stream。
     *
     * 软 reset 会保留 encoder cache。连续短指令（如「创建一个警单」「打开警信」）快速重复时，
     * cache 仍停留在上一句尾部的「持续语音」偏置，下一句开头容易被解成 blank（只剩「信」「创建」等残片）。
     * 有实际解码内容时一律硬重启 + 静音预热，与 session 冷启动同理。
     */
    private fun shouldHardRestartAfter(r: OnlineRecognizerResult): Boolean {
        return r.text.isNotBlank() || r.tokens.isNotEmpty()
    }

    private fun restartStreamAfterUtterance(r: OnlineRecognizerResult) {
        if (shouldHardRestartAfter(r)) {
            hardRestartStream()
        } else {
            NativeGuard.runQuietly("recognizer.reset") { recognizer.reset(stream) }
            NativeGuard.runQuietly("vad.reset") { vad?.reset() }
            resetSpeakerVadState()
        }
        recognizerResetGeneration.markReset()
        lastPartialText = ""
    }

    private fun hardRestartStream() {
        if (closed.get()) return
        val r = NativeGuard.run("recognizer.createStream(hardRestart)") {
            recognizer.createStream(hotwords = currentHotwords)
        }
        when (r) {
            is NativeResult.Ok -> {
                val old = stream
                stream = r.value
                NativeGuard.runQuietly("oldStream.release") { old.release() }
                // stream 重建意味着上一段已结束；同步 reset VAD 让 onset 重新走
                NativeGuard.runQuietly("vad.reset(hardRestart)") { vad?.reset() }
                vadSpeechActive = false
                trailingSilenceMs = 0
                vadCarry = FloatArray(0)
                resetSpeakerVadState()
                Logger.i("session $sessionId hard-restarted stream after long utterance")
                warmUpEncoder(RESTART_STREAM_WARMUP_DURATION_MS)
            }
            is NativeResult.Err -> {
                Logger.w(
                    "session $sessionId hard restart failed, fallback to soft reset: ${r.error.message}",
                )
                NativeGuard.runQuietly("recognizer.reset(hardRestartFallback)") {
                    recognizer.reset(stream)
                }
                resetSpeakerVadState()
            }
        }
    }

    private fun toAsrResult(r: OnlineRecognizerResult): AsrResult {
        val tokenList = r.tokens.toList()
        val tsList = r.timestamps.toList()
        val probList = r.ysProbs.toList()
        val confidence = if (probList.isNotEmpty()) {
            val mean = probList.sum() / probList.size
            exp(mean.toDouble()).toFloat().coerceIn(0.0f, 1.0f)
        } else {
            1.0f
        }
        return AsrResult(
            text = r.text,
            confidence = confidence,
            tokens = tokenList,
            timestamps = tsList,
            tokenConfidences = probList.map { exp(it.toDouble()).toFloat().coerceIn(0.0f, 1.0f) },
        )
    }

    // -------- 目标说话人门控（decoder 线程） --------

    /**
     * 段末门控：对 utterance 缓冲打分并给 [raw] 打标（speakerScore / isTargetSpeaker），或原样放行。
     * 调用后必清空 utterance 缓冲。
     *
     * 放行（返回不带 speaker 字段的 raw）的情况：开关关闭 / 未注册目标 / 无 ASR 语音证据 /
     * extractor 技术上无法产生 embedding。真正"过滤非目标"由 [dispatchFinal] 依据
     * isTargetSpeaker==false 改派
     * onFinalRejected 完成；这里只负责打分与打标，保证 metrics / 后处理时序与未启用时一致。
     */
    private fun prepareFinal(raw: AsrResult, hasEvidence: Boolean, isLast: Boolean): AsrResult? {
        val terminal = raw.copy(isLast = isLast)
        val boundary = effectiveSpeechBuffer.resolveFinal(terminal.text, hasEvidence, isLast)
        if (!boundary.publish) {
            if (speakerVadEnabled) speakerPcmBuffers.clearNativeSegment()
            return null
        }
        val fallbackSamples = if (targetSpeakerEnabled) {
            speakerPcmBuffers.fallbackSamples()
        } else {
            FloatArray(0)
        }
        speakerPcmBuffers.clearAll()

        if (speakerVadEnabled && svRejectCurrentUtterance) {
            val score = svLastScore.takeIf { hasEvidence }
            return terminal.copy(speakerScore = score, isTargetSpeaker = false)
        }
        if (speakerVadEnabled && !svTargetConfirmed) {
            val score = svLastScore.takeIf { hasEvidence }
            return terminal.copy(speakerScore = score, isTargetSpeaker = false)
        }
        if (!targetSpeakerEnabled) return terminal
        val target = targetEmbedding ?: return terminal
        val verifier = ensureVerifier() ?: return terminal
        val minSamples = engineImpl.targetSpeakerConfig
            ?.let { speakerScoreMinimumSamples(it.minSegSec, sampleRate) }
            ?: Int.MAX_VALUE
        val selection = selectSpeakerScoreSamples(
            boundary.samples,
            fallbackSamples,
            minSamples,
            hasEvidence,
        )
        Logger.d(
            "session $sessionId " + speakerScoreSelectionDiagnostic(
                selection,
                boundary.samples.size,
                fallbackSamples.size,
                minSamples,
                sampleRate,
                hasEvidence,
            ),
        )
        if (selection.source == SpeakerScoreSource.UTTERANCE) {
            postDebug(
                "speaker score fallback: effectiveSpeech=" +
                    "${boundary.samples.size * 1000L / sampleRate}ms, " +
                    "utterancePcm=${fallbackSamples.size * 1000L / sampleRate}ms",
            )
        }
        if (selection.samples.isEmpty()) return terminal
        val score = verifier.segmentScore(selection.samples, target) ?: return terminal
        val threshold = engineImpl.targetSpeakerConfig?.threshold ?: DEFAULT_TS_THRESHOLD
        return terminal.copy(speakerScore = score, isTargetSpeaker = score >= threshold)
    }

    /** 懒加载声纹打分器（仅 decoder 线程）。extractor 不可用时返回 null（门控降级为放行）。 */
    private fun ensureVerifier(): SpeakerVerifier? {
        speakerVerifier?.let { return it }
        val tsc = engineImpl.targetSpeakerConfig ?: return null
        val extractor = engineImpl.obtainSpeakerExtractor() ?: run {
            Logger.w("session $sessionId target speaker enabled but extractor unavailable; gating disabled")
            return null
        }
        return SpeakerVerifier(
            extractor = extractor,
            sampleRate = sampleRate,
            winSec = tsc.winSec,
            hopSec = tsc.hopSec,
        ).also { speakerVerifier = it }
    }

    /**
     * 目标说话人 VAD：speech-active 期间按固定 hop 对 utterance 尾窗做声纹打分。
     *
     * 状态机分两段：
     * 1. 先看到目标人（score >= threshold），确认当前 speech 段确实属于目标人；
     * 2. 确认后若连续低于阈值，认为目标人离场，主动 endpoint。
     */
    private fun maybeTriggerSpeakerVadEndpoint(samplesInChunk: Int): Boolean {
        if (!speakerVadEnabled) return false
        val speakerVad = effectiveSpeakerVad ?: return false
        if (!speakerVadScoreScheduler(speakerVad).observe(samplesInChunk)) return false
        val target = targetEmbedding ?: return false
        val verifier = ensureVerifier() ?: return false

        val winSamples = (speakerVad.winSec * sampleRate).toInt().coerceAtLeast(1)

        val scoreStartNs = System.nanoTime()
        val score = verifier.windowScore(speakerPcmBuffers.speakerVadTail(winSamples), target)
            ?: return false
        svLastScore = score
        val scoreElapsedMs = (System.nanoTime() - scoreStartNs) / 1_000_000.0
        val scoreAudioMs = winSamples * 1000.0 / sampleRate
        val scoreRtf = scoreElapsedMs / scoreAudioMs
        if (!svTargetConfirmed) {
            if (score >= speakerVad.threshold) {
                svTargetConfirmed = true
                svBelowCount = 0
                Logger.d("session $sessionId speaker vad target confirmed: score=$score")
                postSpeakerVadDebug("target_confirmed", score, speakerVad.threshold, scoreElapsedMs, scoreRtf)
            } else {
                svBelowCount += 1
                if (svBelowCount >= speakerVad.consecutiveBelow) {
                    svRejectCurrentUtterance = true
                    postSpeakerVadDebug("pre_target_endpoint", score, speakerVad.threshold, scoreElapsedMs, scoreRtf)
                    Logger.d(
                        "session $sessionId speaker vad pre-target endpoint: score=$score " +
                            "threshold=${speakerVad.threshold} belowCount=$svBelowCount",
                    )
                    if (vadSpeechActive) {
                        vadSpeechActive = false
                        trailingSilenceMs = 0
                    }
                    triggerSpeakerVadEndpoint()
                    return true
                }
                postSpeakerVadDebug("waiting_target", score, speakerVad.threshold, scoreElapsedMs, scoreRtf)
            }
            return false
        }

        if (score < speakerVad.threshold) {
            svBelowCount += 1
            if (vadSpeechActive && svBelowCount >= speakerVad.consecutiveBelow) {
                postSpeakerVadDebug("endpoint", score, speakerVad.threshold, scoreElapsedMs, scoreRtf)
                Logger.d(
                    "session $sessionId speaker vad endpoint: score=$score " +
                        "threshold=${speakerVad.threshold} belowCount=$svBelowCount",
                )
                vadSpeechActive = false
                trailingSilenceMs = 0
                triggerSpeakerVadEndpoint()
                return true
            }
            postSpeakerVadDebug("below", score, speakerVad.threshold, scoreElapsedMs, scoreRtf)
        } else {
            svBelowCount = 0
            postSpeakerVadDebug("target_active", score, speakerVad.threshold, scoreElapsedMs, scoreRtf)
        }
        return false
    }

    private fun speakerVadScoreScheduler(config: SpeakerVadConfig): SpeakerVadScoreScheduler {
        val windowSamples = (config.winSec * sampleRate).toInt().coerceAtLeast(1)
        val hopSamples = (config.hopSec * sampleRate).toInt().coerceAtLeast(1)
        val current = svScoreScheduler
        if (current != null &&
            current.windowSamples == windowSamples &&
            current.hopSamples == hopSamples
        ) {
            return current
        }
        return SpeakerVadScoreScheduler(windowSamples, hopSamples).also { svScoreScheduler = it }
    }

    private fun postSpeakerVadDebug(
        state: String,
        score: Float,
        threshold: Float,
        inferMs: Double,
        rtf: Double,
    ) {
        val msg = String.format(
            Locale.US,
            "speaker_vad state=%s score=%.3f threshold=%.2f inferMs=%.1f rtf=%.3f confirmed=%s below=%d",
            state,
            score,
            threshold,
            inferMs,
            rtf,
            svTargetConfirmed,
            svBelowCount,
        )
        Logger.i("session $sessionId $msg")
        Logger.metric("kind=SPEAKER_VAD sessionId=$sessionId $msg")
        callbackHandler.post {
            safeCallback { callback.onDebug(msg) }
        }
    }

    private fun resetSpeakerVadState() {
        svScoreScheduler?.reset()
        svTargetConfirmed = false
        svBelowCount = 0
        svRejectCurrentUtterance = false
        svLastScore = null
    }

    // -------- callback dispatch --------

    private fun postPartial(result: AsrResult) {
        // Speaker VAD only corrects committed finals. Partials remain speculative; the public
        // adapter still applies the caller's enablePartialResult setting at delivery time.
        callbackHandler.post {
            metrics.onPartialDispatched()
            safeCallback { callback.onPartial(result) }
        }
    }

    /**
     * 把 ASR final 投递到 PostProcessor；处理完后由 PostProcessor 调 [dispatchFinal] 出 callback。
     * 如果 ITN / 标点都没启用，PostProcessor 的处理是 no-op，链路一致但不增加耗时。
     */
    private fun postFinalToProcessor(raw: AsrResult) {
        finalCallbackOrderGate.onFinalQueued()
        postProcessor.postFinal(raw)
    }

    private fun dispatchFinal(processed: AsrResult, postProcessMs: Long) {
        // 在 postprocess 线程同步抓 metrics 快照（utterance 维度）；startupBundle 仅第一段非 null
        val bundleForThisUtterance = startupBundlePending
        startupBundlePending = null
        val utteranceMetrics = metrics.snapshotUtterance(postProcessMs, bundleForThisUtterance)
        metrics.emit(utteranceMetrics, callback, callbackHandler)

        callbackHandler.post {
            safeCallback {
                // 目标说话人门控：被判为非目标的段改派 onFinalRejected（不再触发 onFinal）。
                if (processed.isTargetSpeaker == false) {
                    callback.onFinalRejected(processed)
                } else {
                    callback.onFinal(processed)
                }
            }
        }
        if (finalCallbackOrderGate.onFinalEnqueued()) postSessionStopped()
    }

    private fun postSessionStopped() {
        callbackHandler.post {
            safeCallback { callback.onSessionStopped() }
        }
    }

    private fun postEndpoint() {
        callbackHandler.post {
            safeCallback { callback.onEndpoint() }
        }
    }

    private fun postError(error: AsrError) {
        callbackHandler.post {
            safeCallback { callback.onError(error) }
        }
    }

    private fun postDebug(message: String) {
        callbackHandler.post {
            safeCallback { callback.onDebug(message) }
        }
    }

    private fun resetVadGateState() {
        NativeGuard.runQuietly("vad.reset(streamBoundary)") { vad?.reset() }
        vadSpeechActive = false
        trailingSilenceMs = 0
        vadCarry = FloatArray(0)
        resetSpeakerVadState()
    }

    private inline fun safeCallback(block: () -> Unit) {
        try {
            block()
        } catch (t: Throwable) {
            Logger.e("user callback threw: ${t.message}", t)
        }
    }

    private fun quitThreadsQuietly() {
        try { decoderThread.quitSafely() } catch (_: Throwable) {}
        try { callbackThread.quitSafely() } catch (_: Throwable) {}
    }

    private companion object {
        /** Initial-silence decisions advance in fixed 20 ms slices, independent of caller chunk size. */
        const val INITIAL_DECISION_CHUNKS_PER_SECOND = 50

        /** 首次 stream 不预热；与 Harmony zhen 真机 A/B 后的默认策略一致。 */
        const val INITIAL_STREAM_WARMUP_DURATION_MS = 0

        /** 句间硬重启仍需恢复 encoder cache，避免连续短指令吞掉下一句开头。 */
        const val RESTART_STREAM_WARMUP_DURATION_MS = 800

        /** 保持 vadBegin 强制探测的既有 500 ms 合成输入，不随手动 finish 的尾上下文调整。 */
        const val INITIAL_SILENCE_PROBE_TAIL_MS = 500

        /**
         * 手动 stop 经常正好落在语音末尾。zh-en encoder 每个 chunk 约 640 ms；补足两个完整
         * chunk，保证无论当前 chunk 相位如何都还有两次解码机会。这里是合成输入，不是墙钟等待。
         */
        const val FINAL_TAIL_SILENCE_MS = 1280

        /**
         * silero VAD 强约束：必须按窗口对齐喂入 [Vad.acceptWaveform]。
         * 16 kHz 下 512 个 sample = 32 ms。本 SDK 锁 silero，常量值与 EngineImpl 一致。
         */
        const val VAD_WINDOW_SIZE = 512

        /** utterance 缓冲上限（25s @16k）；endpoint rule3 20s 会先强制 final，此为防御性上限。 */
        const val UTT_MAX_SAMPLES = 25 * 16000

        /** 目标说话人默认阈值兜底（与 TargetSpeakerConfig.threshold 默认一致）。 */
        const val DEFAULT_TS_THRESHOLD = 0.30f

        @Suppress("unused")
        const val SESSION_ALREADY_CLOSED_CODE = AsrErrorCode.SESSION_ALREADY_CLOSED
    }
}
