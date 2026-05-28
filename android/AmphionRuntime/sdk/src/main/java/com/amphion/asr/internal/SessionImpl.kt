package com.amphion.asr.internal

import android.os.Handler
import android.os.HandlerThread
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrError
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.AsrResult
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerResult
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.Vad
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
) {

    private val closed = AtomicBoolean(false)
    private val stopped = AtomicBoolean(false)

    private val decoderThread = HandlerThread("asr-decode-$sessionId").apply { start() }
    private val decoderHandler = Handler(decoderThread.looper)

    private val callbackThread = HandlerThread("asr-callback-$sessionId").apply { start() }
    private val callbackHandler = Handler(callbackThread.looper)

    @Volatile
    private var stream: OnlineStream

    @Volatile
    private var lastPartialText: String = ""

    @Volatile
    private var currentHotwords: String = engineImpl.engineHotwords

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
    private val activeEpSilenceMs: Int = engineImpl.vadConfig.activeEndpointSilenceMs

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
        // streaming zipformer 的 encoder 在 stream 刚创建时 left-context cache 全 0，
        // 直接送真实音频会让前 ~2s 的 hypothesis 全部坍缩到 blank，导致「第一句被吞」。
        // 这里在 decoder 线程上抢先投递一段静音 PCM，让 encoder 把 cache 跑起来；
        // 由于 sherpa-onnx 默认 reset_encoder=false（online-recognizer.h:115）+ 当前
        // result 为空时不会触发 SetStates，所以紧跟的 recognizer.reset 只清 decoder hyps，
        // encoder buffer 保留 → 下一段真实 PCM 第一个 chunk 起就能拿到正常 logits。
        decoderHandler.post { warmUpEncoder(WARMUP_DURATION_MS) }
    }

    val isClosed: Boolean
        get() = closed.get()

    // -------- public 方法（被 AsrSession 转发） --------

    fun acceptPcmFloat(samples: FloatArray) {
        if (closed.get() || stopped.get()) {
            Logger.d("acceptPcmFloat dropped (closed=${closed.get()}, stopped=${stopped.get()})")
            return
        }
        // 16-bit PCM 单声道：每个 sample 2 字节
        metrics.onPcmAccepted(samples.size * 2)
        val copy = samples.copyOf()
        decoderHandler.post { feedAndDecode(copy) }
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
        decoderHandler.post {
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
                    Logger.i("updateHotwords applied: ${words.size} words")
                }
                is NativeResult.Err -> {
                    Logger.w("updateHotwords failed, keep old stream: ${r.error.message}")
                    postError(r.error)
                }
            }
        }
    }

    fun stop() {
        if (closed.get()) return
        if (!stopped.compareAndSet(false, true)) return
        decoderHandler.post {
            val r = NativeGuard.run("stream.inputFinished+drain") {
                stream.inputFinished()
                drainDecoder(isFinal = true)
            }
            if (r is NativeResult.Err) {
                postError(r.error)
            }
            // VAD 状态与 stream 同步：用户手动 stop 等价于一段语音结束
            NativeGuard.runQuietly("vad.reset(stop)") { vad?.reset() }
            vadSpeechActive = false
            trailingSilenceMs = 0
            vadCarry = FloatArray(0)
            callbackHandler.post {
                safeCallback { callback.onSessionStopped() }
            }
        }
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return
        engineImpl.unregister(this)

        decoderHandler.removeCallbacksAndMessages(null)
        decoderHandler.post {
            NativeGuard.runQuietly("stream.release") { stream.release() }
            // VAD 是 per-engine 共享的，session 关闭只 reset（清内部 buffer），不 release
            NativeGuard.runQuietly("vad.reset(close)") { vad?.reset() }
            decoderThread.quitSafely()
        }

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

    private fun feedAndDecode(samples: FloatArray) {
        if (closed.get()) return

        // 保持 PCM 全量进 ASR，让 partial 实时性不受 VAD 抖动影响。VAD 只做 gate
        // + 主动 endpoint（更敏感的尾静音切分），它们与 sherpa endpoint 规则并存：
        // 谁先触发以谁为准。
        val asrR = NativeGuard.run("stream.acceptWaveform+drain") {
            stream.acceptWaveform(samples, sampleRate)
            drainDecoder(isFinal = false)
        }
        if (asrR is NativeResult.Err) {
            postError(asrR.error)
            return
        }

        // drainDecoder 已经处理了 endpoint，stream 可能已被重建（hardRestart）
        // 这种情况下当前 chunk 仍按 onset 路径继续判定，与已 reset 的状态一致。

        val v = vad ?: return

        // silero 的 acceptWaveform 强约束 windowSize=512；按 chunk 切片喂入，剩余样本
        // 进 vadCarry 等下次拼回。两次 chunk 的 VAD speech/silence 状态由 v 自己维护。
        val merged = if (vadCarry.isEmpty()) samples else vadCarry + samples
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
                // 任何一个窗口看到 speech，就把累计静音清零。中间夹杂少量静音窗口
                // （正常说话时 vad 在 0.5 阈值附近抖动）不会被误判成结束。
                if (!vadSpeechActive) {
                    vadSpeechActive = true
                    Logger.d("session $sessionId VAD speech onset")
                }
                trailingSilenceMs = 0
            }
            anySilence && vadSpeechActive -> {
                // 仅在曾经有 speech 之后才累计静音；进入主动 endpoint 判定。
                trailingSilenceMs += (samples.size * 1000L / sampleRate).toInt()
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
    }

    /**
     * VAD 检测到 speech 后尾静音 ≥ [activeEpSilenceMs] 时调用：复用 stop 路径的
     * inputFinished + drain(isFinal=true) + reset 三件套，让当前 stream 出 final。
     * 不走 hardRestart：tokens < HARD_RESTART_TOKEN_THRESHOLD 时 soft reset 已经足够，
     * encoder cache 偏置只在长 utterance 后才显现。
     */
    private fun triggerVadActiveEndpoint() {
        val v = vad ?: return
        val r = NativeGuard.run("vad.activeEndpoint") {
            stream.inputFinished()
            drainDecoder(isFinal = true)
            recognizer.reset(stream)
            v.reset()
        }
        if (r is NativeResult.Err) {
            postError(r.error)
            return
        }
        lastPartialText = ""
        vadCarry = FloatArray(0)
    }

    /**
     * 解出当前 stream 的所有结果并 dispatch；isFinal=true 时把当前残留文本作为 final 发出。
     */
    private fun drainDecoder(isFinal: Boolean) {
        while (recognizer.isReady(stream)) {
            recognizer.decode(stream)
        }

        if (recognizer.isEndpoint(stream)) {
            metrics.onEndpointDetected()
            val r = recognizer.getResult(stream)
            metrics.onRawFinalReady()
            postEndpoint()
            postFinalToProcessor(toAsrResult(r))
            // 长 utterance 后做硬重启而不是软 reset：
            // 软 reset 只清 decoder hyps、保留 encoder cache（reset_encoder=false 默认），
            // 经历 ~10s 的长 utterance 后 encoder cache 内部 norm/偏置进入"持续语音"状态，
            // 紧跟的 600-800ms 短词会被解成 CTC blank，partial 一个不出。
            if (shouldHardRestartAfter(r)) {
                hardRestartStream()
            } else {
                recognizer.reset(stream)
            }
            lastPartialText = ""
            return
        }

        val r = recognizer.getResult(stream)
        if (isFinal) {
            metrics.onRawFinalReady()
            postFinalToProcessor(toAsrResult(r))
            NativeGuard.runQuietly("recognizer.reset") { recognizer.reset(stream) }
            lastPartialText = ""
        } else if (r.text != lastPartialText) {
            lastPartialText = r.text
            postPartial(toAsrResult(r))
        }
    }

    private fun shouldHardRestartAfter(r: OnlineRecognizerResult): Boolean {
        return r.tokens.size >= HARD_RESTART_TOKEN_THRESHOLD
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
                Logger.i("session $sessionId hard-restarted stream after long utterance")
                warmUpEncoder(WARMUP_DURATION_MS)
            }
            is NativeResult.Err -> {
                Logger.w(
                    "session $sessionId hard restart failed, fallback to soft reset: ${r.error.message}",
                )
                NativeGuard.runQuietly("recognizer.reset(hardRestartFallback)") {
                    recognizer.reset(stream)
                }
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

    // -------- callback dispatch --------

    private fun postPartial(result: AsrResult) {
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
        postProcessor.postFinal(raw)
    }

    private fun dispatchFinal(processed: AsrResult, postProcessMs: Long) {
        // 在 postprocess 线程同步抓 metrics 快照（utterance 维度）；startupBundle 仅第一段非 null
        val bundleForThisUtterance = startupBundlePending
        startupBundlePending = null
        val utteranceMetrics = metrics.snapshotUtterance(postProcessMs, bundleForThisUtterance)
        metrics.emit(utteranceMetrics, callback, callbackHandler)

        callbackHandler.post {
            safeCallback { callback.onFinal(processed) }
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
        /** 静音预热 encoder 的时长（ms）。≈ 2.5 chunk @chunk_size=32, 16kHz。 */
        const val WARMUP_DURATION_MS = 800

        /**
         * endpoint 后判断「是否硬重启 stream」的 token 阈值。20 个 token ≈ 10s 持续语音。
         * 超过这个量级 encoder cache 偏置会让紧跟的短词被解成 blank，硬重启可解决。
         */
        const val HARD_RESTART_TOKEN_THRESHOLD = 20

        /**
         * silero VAD 强约束：必须按窗口对齐喂入 [Vad.acceptWaveform]。
         * 16 kHz 下 512 个 sample = 32 ms。本 SDK 锁 silero，常量值与 EngineImpl 一致。
         */
        const val VAD_WINDOW_SIZE = 512

        @Suppress("unused")
        const val SESSION_ALREADY_CLOSED_CODE = AsrErrorCode.SESSION_ALREADY_CLOSED
    }
}
