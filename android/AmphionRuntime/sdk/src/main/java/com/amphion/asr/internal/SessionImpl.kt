package com.amphion.asr.internal

import android.os.Handler
import android.os.HandlerThread
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerResult
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.Vad
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrError
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.AsrResult
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.exp

/**
 * SessionImpl：把官方 [OnlineStream] 包成单线程消费 + 单线程回调的会话。
 *
 * 线程：
 * - decoder thread "asr-decode-<id>"：串行执行 acceptWaveform + decode + getResult
 * - callback thread "asr-callback-<id>"：串行 dispatch 业务方回调
 *
 * 这样 业务方录音线程 → SDK decoder → SDK callback → 业务方主线程，是一条清晰单链。
 */
internal class SessionImpl(
    private val engineImpl: EngineImpl,
    private val recognizer: OnlineRecognizer,
    private val vad: Vad?,
    private val sampleRate: Int,
    private val callback: AsrCallback,
    private val sessionId: Int,
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

    /** 当前 session 的热词字符串（与 stream 绑定）；初始 = engine 的 engineHotwords。 */
    @Volatile
    private var currentHotwords: String = engineImpl.engineHotwords

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
        callbackHandler.post {
            safeCallback { callback.onSessionStarted() }
        }
        // streaming zipformer 的 encoder 在 stream 刚创建时 left-context cache 全 0，
        // 直接送真实音频会让前 ~2s 的 hypothesis 全部坍缩到 blank，导致「第一句被吞」。
        // 这里在 decoder 线程上抢先投递一段静音 PCM，让 encoder 把 cache 跑起来；
        // 由于 sherpa-onnx 默认 reset_encoder=false（online-recognizer.h:115）+ 当前
        // result 为空时不会触发 SetStates，所以紧跟的 recognizer.reset 只清 decoder hyps，
        // encoder buffer 保留 → 下一段真实 PCM 第一个 chunk 起就能拿到正常 logits。
        // 整段 800 ms 静音 ≈ 2.5 chunk（chunk_size=32@16k），与业务方点完按钮到张口的
        // 自然停顿重合，肉眼几乎无感知。
        decoderHandler.post { warmUpEncoder(WARMUP_DURATION_MS) }
    }

    val isClosed: Boolean
        get() = closed.get()

    // -------- public 方法（被 AsrSession 转发） --------

    fun acceptPcmFloat(samples: FloatArray, sampleRate: Int) {
        if (closed.get() || stopped.get()) {
            Logger.d("acceptPcmFloat dropped (closed=${closed.get()}, stopped=${stopped.get()})")
            return
        }
        if (sampleRate != this.sampleRate) {
            postError(AsrErrorCode.SAMPLE_RATE_MISMATCH,
                "expected sampleRate=${this.sampleRate}, got $sampleRate")
            return
        }
        // 拷贝一份再投递，避免业务方复用 buffer 造成数据竞争
        val copy = samples.copyOf()
        decoderHandler.post { feedAndDecode(copy) }
    }

    fun acceptPcmShort(samples: ShortArray, sampleRate: Int) {
        if (closed.get() || stopped.get()) return
        val floats = FloatArray(samples.size)
        var i = 0
        while (i < samples.size) {
            floats[i] = samples[i] / 32768f
            i++
        }
        acceptPcmFloat(floats, sampleRate)
    }

    fun updateHotwords(words: List<String>, score: Float) {
        if (closed.get()) {
            Logger.w("updateHotwords ignored: session closed")
            return
        }
        // score 不一致：仅日志，不报错（Engine 级 score 改不了）
        if (score != engineImpl.engineHotwordsScore) {
            Logger.w(
                "updateHotwords: requested score=$score differs from engine-level " +
                "score=${engineImpl.engineHotwordsScore}; the latter is the one actually applied. " +
                "Recreate AsrEngine to truly change score."
            )
        }
        val newHotwords = words.filter { it.isNotBlank() }.joinToString("\n")
        if (newHotwords == currentHotwords) {
            Logger.d("updateHotwords: identical, no-op")
            return
        }
        decoderHandler.post {
            // 思路：用同一个 recognizer 重新 createStream(newHotwords)；旧 stream release。
            // sherpa-onnx 的 createStream 接收 hotwords 字符串，会构造一个新的 ContextGraph，
            // 后续 acceptWaveform 都走新 graph。
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
            callbackHandler.post {
                safeCallback { callback.onSessionStopped() }
            }
        }
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return
        engineImpl.unregister(this)

        // 不再接受新任务；尽量 drain 完已经投递的任务
        decoderHandler.removeCallbacksAndMessages(null)
        decoderHandler.post {
            NativeGuard.runQuietly("stream.release") { stream.release() }
            decoderThread.quitSafely()
        }

        callbackHandler.removeCallbacksAndMessages(null)
        callbackHandler.post {
            callbackThread.quitSafely()
        }
        Logger.d("session $sessionId closed")
    }

    // -------- decoder loop --------

    /**
     * 用静音 PCM 预热 encoder：跑完所有 ready 的 chunk，然后 reset 清掉 decoder hyps，
     * 但保留 encoder state（依赖上游 `reset_encoder=false` 的默认）。
     *
     * 调用时机：构造期由 decoderHandler post，一定排在外部 [acceptPcmFloat] 之前。
     * 失败只 warn，不影响主流程；session 仍可识别，只是会回退到「第一句被吞」的原貌。
     */
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
            is NativeResult.Err -> {
                Logger.w("session $sessionId encoder warm-up failed: ${r.error.message}")
            }
        }
    }

    private fun feedAndDecode(samples: FloatArray) {
        if (closed.get()) return
        val r = NativeGuard.run("stream.acceptWaveform+drain") {
            stream.acceptWaveform(samples, sampleRate)
            drainDecoder(isFinal = false)
        }
        if (r is NativeResult.Err) {
            postError(r.error)
        }
    }

    /**
     * 解出当前 stream 的所有结果并 dispatch；isFinal=true 时把当前残留文本作为 final 发出。
     *
     * 注意：本方法内部已经被外层 [NativeGuard.run] 包住，所以 `recognizer.* / stream.*` 直接调用即可，
     * 任何 native 异常都会被外层捕获并归一为 [AsrErrorCode.NATIVE_CRASH]。
     */
    private fun drainDecoder(isFinal: Boolean) {
        // 反复 decode 直到 ready=false
        while (recognizer.isReady(stream)) {
            recognizer.decode(stream)
        }

        if (recognizer.isEndpoint(stream)) {
            val r = recognizer.getResult(stream)
            postEndpoint()
            postFinal(toAsrResult(r))
            recognizer.reset(stream)
            lastPartialText = ""
            return
        }

        val r = recognizer.getResult(stream)
        if (isFinal) {
            postFinal(toAsrResult(r))
            NativeGuard.runQuietly("recognizer.reset") { recognizer.reset(stream) }
            lastPartialText = ""
        } else if (r.text != lastPartialText) {
            lastPartialText = r.text
            postPartial(toAsrResult(r))
        }
    }

    /**
     * 把上游 [OnlineRecognizerResult] 翻成对外 [AsrResult]。
     *
     * sherpa-onnx 没有暴露稳定的 segment 置信度，目前用 ysProbs（log prob）的几何平均近似：
     *   confidence ≈ exp(mean(ysProbs))
     * 没数据则置 1.0，保持与旧签名 onFinal(text, 1.0f) 一致。
     */
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
            safeCallback { callback.onPartial(result) }
        }
    }

    private fun postFinal(result: AsrResult) {
        callbackHandler.post {
            safeCallback { callback.onFinal(result) }
        }
    }

    private fun postEndpoint() {
        callbackHandler.post {
            safeCallback { callback.onEndpoint() }
        }
    }

    private fun postError(code: Int, message: String, cause: Throwable? = null) {
        postError(AsrError(code, message, cause))
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
            // 业务方 callback 抛出异常，SDK 不让它扩散；只打日志
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
    }
}
