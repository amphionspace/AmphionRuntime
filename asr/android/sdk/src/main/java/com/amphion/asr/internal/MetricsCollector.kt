package com.amphion.asr.internal

import android.os.Handler
import android.os.SystemClock
import com.amphion.asr.AmphionMetrics
import com.amphion.asr.AmphionMetricsKind
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrLanguage
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * Per-session 指标采集器。
 *
 * 时间基准：[SystemClock.elapsedRealtime]（不受系统挂起影响、单调递增）。所有外部调用
 * 必须在「事件真实发生的线程」触发，[MetricsCollector] 不做线程绑定假设；构造 [AmphionMetrics]
 * 与派发是 caller 安排的。
 *
 * 数据流：[SessionImpl] 调 [onPcmAccepted] / [onPartialDispatched] / [onEndpointDetected] /
 * [onRawFinalReady] 累积当前 utterance 状态；[PostProcessor] 完成后 [SessionImpl] 调
 * [snapshotUtterance] 拿一份 [AmphionMetrics]，dispatch 之后状态清零进入下一段。
 *
 * Engine 启动期信息（[EngineStartupBundle]）只附带在第一段 utterance 上；后续段 / SESSION
 * 维度都是 -1 sentinel。
 */
internal class MetricsCollector(
    private val sessionId: Int,
    private val language: AsrLanguage,
) {

    @Volatile
    private var firstPcmElapsed: Long = -1L

    @Volatile
    private var firstPartialElapsed: Long = -1L

    @Volatile
    private var endpointElapsed: Long = -1L

    @Volatile
    private var rawFinalElapsed: Long = -1L

    private val pcmBytesInUtterance = AtomicLong(0L)

    private val utteranceCount = AtomicInteger(0)
    private val totalPcmBytes = AtomicLong(0L)

    private val rtfHistory: MutableList<Float> = ArrayList()
    private val rtfHistoryLock = Any()

    @Volatile
    private var peakNativeRssMb: Int = -1

    /** 上一段结束时记录的 RSS（MB），用来算 delta。-1 表示首段。 */
    @Volatile
    private var lastReportedRssMb: Int = -1

    fun onPcmAccepted(bytes: Int) {
        if (firstPcmElapsed < 0) {
            firstPcmElapsed = SystemClock.elapsedRealtime()
        }
        pcmBytesInUtterance.addAndGet(bytes.toLong())
        totalPcmBytes.addAndGet(bytes.toLong())
    }

    fun onPartialDispatched() {
        if (firstPartialElapsed < 0) {
            firstPartialElapsed = SystemClock.elapsedRealtime()
        }
    }

    fun onEndpointDetected() {
        endpointElapsed = SystemClock.elapsedRealtime()
    }

    fun onRawFinalReady() {
        rawFinalElapsed = SystemClock.elapsedRealtime()
    }

    /**
     * 构造一份 utterance 维度的 [AmphionMetrics]；构造完后内部 utterance 状态被清零，
     * 准备进入下一段。Engine 启动期信息通过 [startupBundle] 显式传入（仅第一段非 null）。
     */
    fun snapshotUtterance(
        postProcessMs: Long,
        startupBundle: EngineStartupBundle?,
    ): AmphionMetrics {
        val now = SystemClock.elapsedRealtime()
        val firstPcm = if (firstPcmElapsed < 0L) now else firstPcmElapsed
        val pcmBytes = pcmBytesInUtterance.get()
        val utteranceDurationMs = if (pcmBytes > 0L) {
            pcmBytes * 1000L / SAMPLE_RATE / BYTES_PER_SAMPLE
        } else {
            -1L
        }
        val decodeDurationMs = if (rawFinalElapsed > 0L) rawFinalElapsed - firstPcm else -1L
        val firstPartialMs = if (firstPartialElapsed > 0L) firstPartialElapsed - firstPcm else -1L
        val endpointMs = if (endpointElapsed > 0L) now - endpointElapsed else -1L
        val e2eMs = if (firstPcmElapsed > 0L) now - firstPcmElapsed else -1L
        val rtf = if (decodeDurationMs > 0L && utteranceDurationMs > 0L) {
            decodeDurationMs.toFloat() / utteranceDurationMs.toFloat()
        } else {
            -1f
        }

        val rssMbNow = ProcessRssReader.readNativeRssMb()
        val rssDelta = if (lastReportedRssMb >= 0 && rssMbNow >= 0) {
            rssMbNow - lastReportedRssMb
        } else {
            0
        }
        if (rssMbNow >= 0) {
            lastReportedRssMb = rssMbNow
            if (rssMbNow > peakNativeRssMb) peakNativeRssMb = rssMbNow
        }

        val idx = utteranceCount.incrementAndGet()
        synchronized(rtfHistoryLock) {
            if (rtf > 0f) rtfHistory.add(rtf)
        }

        val metrics = AmphionMetrics(
            kind = AmphionMetricsKind.UTTERANCE,
            language = language,
            sessionId = sessionId,
            assetInstallMs = startupBundle?.assetInstallMs ?: -1L,
            assetTotalBytes = startupBundle?.assetTotalBytes ?: -1L,
            engineReadyMs = startupBundle?.engineReadyMs ?: -1L,
            nativeRssMbAtReady = startupBundle?.nativeRssMbAtReady ?: -1,
            utteranceIndex = idx,
            utteranceDurationMs = utteranceDurationMs,
            decodeDurationMs = decodeDurationMs,
            postProcessMs = postProcessMs,
            firstPartialLatencyMs = firstPartialMs,
            endpointToFinalLatencyMs = endpointMs,
            utteranceE2eLatencyMs = e2eMs,
            rtf = rtf,
            nativeRssMbDelta = rssDelta,
            nativeRssMb = rssMbNow,
            pcmBytesAccepted = pcmBytes,
        )

        // reset utterance 状态
        firstPcmElapsed = -1L
        firstPartialElapsed = -1L
        endpointElapsed = -1L
        rawFinalElapsed = -1L
        pcmBytesInUtterance.set(0L)

        return metrics
    }

    /** 构造 session 维度的 [AmphionMetrics]（在 session close 时调一次）。 */
    fun snapshotSession(): AmphionMetrics {
        val rtfSnapshot = synchronized(rtfHistoryLock) { rtfHistory.toList() }
        val avg = if (rtfSnapshot.isNotEmpty()) rtfSnapshot.sum() / rtfSnapshot.size else -1f
        val p95 = computeP95(rtfSnapshot)
        val rssNow = ProcessRssReader.readNativeRssMb()
        val peak = maxOf(peakNativeRssMb, rssNow)
        return AmphionMetrics(
            kind = AmphionMetricsKind.SESSION,
            language = language,
            sessionId = sessionId,
            totalUtterances = utteranceCount.get(),
            totalPcmBytes = totalPcmBytes.get(),
            avgRtf = avg,
            p95Rtf = p95,
            peakNativeRssMb = peak,
            nativeRssMb = rssNow,
        )
    }

    /** 把 [metrics] 同时写到 logcat 与业务回调。在 caller 决定的线程上执行（一般是 callback thread）。 */
    fun emit(metrics: AmphionMetrics, callback: AsrCallback, callbackHandler: Handler) {
        Logger.metric(metrics.toLogLine())
        callbackHandler.post {
            try {
                callback.onMetrics(metrics)
            } catch (t: Throwable) {
                Logger.e("user onMetrics threw: ${t.message}", t)
            }
        }
    }

    private fun computeP95(xs: List<Float>): Float {
        if (xs.isEmpty()) return -1f
        if (xs.size < 5) return xs.max()
        val sorted = xs.sorted()
        val idx = (sorted.size * 0.95f).toInt().coerceAtMost(sorted.size - 1)
        return sorted[idx]
    }

    private companion object {
        const val SAMPLE_RATE = 16000
        const val BYTES_PER_SAMPLE = 2
    }
}
