package com.amphion.dingqiao.diarization

import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

internal data class DiarizationFinishInput<T>(val degraded: Boolean, val value: T)
internal data class DiarizationFinishOutput<A, S>(val asr: A, val speaker: S?, val degraded: Boolean)

/** Coordinates the ASR tail and diarization tail without blocking finish(). */
internal class SpeakerDiarizationFinishBarrier<A : Any, S : Any>(
    private val timeoutMs: Long,
    private val scheduler: ScheduledExecutorService,
    private val onReady: (DiarizationFinishOutput<A, S>) -> Unit,
    private val timeoutAsrFallback: (() -> A)? = null,
) {
    private var started = false
    private var completed = false
    private var asrReady = false
    private var speakerReady = false
    private var degraded = false
    private var asrValue: A? = null
    private var speakerValue: S? = null
    private var timeout: ScheduledFuture<*>? = null

    init { require(timeoutMs > 0) }

    @Synchronized
    fun begin() {
        if (started || completed) return
        started = true
        timeout = scheduler.schedule({
            synchronized(this) {
                if (completed) return@synchronized
                speakerReady = true
                degraded = true
                if (!asrReady) timeoutAsrFallback?.let {
                    asrValue = it()
                    asrReady = true
                }
                tryCompleteLocked()
            }
        }, timeoutMs, TimeUnit.MILLISECONDS)
    }

    @Synchronized
    fun resolveAsr(value: A) {
        if (completed || asrReady) return
        asrReady = true
        asrValue = value
        tryCompleteLocked()
    }

    @Synchronized
    fun resolveSpeaker(result: DiarizationFinishInput<S>) {
        if (completed || speakerReady) return
        speakerReady = true
        speakerValue = result.value
        degraded = result.degraded
        tryCompleteLocked()
    }

    @Synchronized
    fun cancel() {
        completed = true
        timeout?.cancel(false)
        timeout = null
    }

    private fun tryCompleteLocked() {
        if (completed || !asrReady || !speakerReady) return
        completed = true
        timeout?.cancel(false)
        timeout = null
        val output = DiarizationFinishOutput(checkNotNull(asrValue), speakerValue, degraded)
        onReady(output)
    }
}
