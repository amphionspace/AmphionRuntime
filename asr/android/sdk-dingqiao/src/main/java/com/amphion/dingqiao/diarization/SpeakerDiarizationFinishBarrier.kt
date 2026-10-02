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
    // On timeout, first ask diarization to freeze what it already inferred, and wait at
    // most this long for that result before completing without speaker results.
    private val salvageMs: Long = 0,
    private val onTimeout: () -> Unit = {},
) {
    private var started = false
    private var completed = false
    private var asrReady = false
    private var speakerReady = false
    private var degraded = false
    private var asrValue: A? = null
    private var speakerValue: S? = null
    private var timeout: ScheduledFuture<*>? = null

    init { require(timeoutMs > 0 && salvageMs >= 0) }

    @Synchronized
    fun begin() {
        if (started || completed) return
        started = true
        startTimeoutIfReadyLocked()
    }

    private fun startTimeoutIfReadyLocked() {
        // Diarization also waits for the real ASR tail. Its timeout must not include ASR backlog.
        if (!started || !asrReady || speakerReady || completed || timeout != null) return
        timeout = scheduler.schedule({
            val salvage = synchronized(this) {
                if (completed || speakerReady) return@schedule
                if (salvageMs > 0) {
                    timeout = scheduler.schedule({ expire() }, salvageMs, TimeUnit.MILLISECONDS)
                    true
                } else {
                    expireLocked()
                    false
                }
            }
            if (salvage) onTimeout()
        }, timeoutMs, TimeUnit.MILLISECONDS)
    }

    @Synchronized
    private fun expire() = expireLocked()

    private fun expireLocked() {
        if (completed || speakerReady) return
        speakerReady = true
        degraded = true
        // Only diarization may degrade on timeout. ASR must drain all accepted audio.
        tryCompleteLocked()
    }

    @Synchronized
    fun resolveAsr(value: A) {
        if (completed || asrReady) return
        asrReady = true
        asrValue = value
        startTimeoutIfReadyLocked()
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
