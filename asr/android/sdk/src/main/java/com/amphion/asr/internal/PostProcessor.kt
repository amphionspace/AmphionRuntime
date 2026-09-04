package com.amphion.asr.internal

import android.os.Handler
import android.os.HandlerThread
import com.amphion.asr.AsrError
import com.amphion.asr.AsrResult

/**
 * ASR final 文本的后处理器：在 ASR final emit 之后，串行做 ITN（仅 ZH_EN）-> 标点 ->
 * 单次 onProcessed 回调，避免 sample 时代「先出原文 -> 再被异步替换」造成的 UI 抖动。
 *
 * 设计要点：
 *
 * - 单线程串行：postFinal 只追加任务到 [postProcessThread]，确保多个 final 顺序处理
 * - 失败降级：ITN 或标点任一阶段抛出，都降级成"上一阶段的结果"，不阻塞主路径
 * - 与 SessionImpl 的 callback thread 解耦：本 PostProcessor 不负责调用业务方 callback，
 *   只把"加工完毕的 AsrResult"返还给 SessionImpl，由后者投递到 callback thread
 */
internal class PostProcessor(
    private val sessionId: Int,
    private val itn: InternalWeitnEngine?,
    private val punctuation: InternalPunctuationEngine?,
    private val onProcessed: (AsrResult, Long) -> Unit,
    private val onError: (AsrError) -> Unit,
) : AutoCloseable {

    private val thread: HandlerThread =
        HandlerThread("asr-postprocess-$sessionId").apply { start() }
    private val handler: Handler = Handler(thread.looper)

    @Volatile
    private var accepting: Boolean = true

    @Volatile
    private var drained: Boolean = false

    /**
     * 把一个 ASR final 结果 [raw] 投递到后处理队列；处理完后调 [onProcessed]，
     * 同时把后处理实际耗时（毫秒）一并传出供 metrics 采集。
     */
    fun postFinal(raw: AsrResult) {
        if (!accepting || drained) {
            // close 已经进入排空阶段后不再接收新任务；直接走原文，避免吞掉 final。
            onProcessed(raw, 0L)
            return
        }
        handler.post {
            val started = android.os.SystemClock.elapsedRealtime()
            val processed = process(raw)
            val elapsed = android.os.SystemClock.elapsedRealtime() - started
            if (!drained) onProcessed(processed, elapsed)
        }
    }

    /**
     * 直接同步处理（仅供内部跑「无后处理」分支用，如 punct=false && itn=false 时
     * SessionImpl 完全不需要 PostProcessor）。
     */
    internal fun process(raw: AsrResult): AsrResult {
        var text = raw.text
        if (itn != null) {
            text = itn.normalize(text, onError)
        }
        if (punctuation != null) {
            text = punctuation.addPunctuation(text, onError)
        }
        val result = if (text === raw.text) raw else raw.copy(text = text)
        ResultAudioTimeline.transfer(raw, result)
        return result
    }

    override fun close() {
        if (!accepting) return
        accepting = false
        // 不移除已排队的 final：让 close 标记之前的任务自然处理并回调，避免 finish
        // 后 teardown 把真实语音 final 从后处理队列中丢弃。
        handler.post {
            drained = true
            thread.quitSafely()
        }
    }
}
