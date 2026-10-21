package com.amphion.dingqiao.diarization

import android.content.Context
import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import java.io.File
import java.io.RandomAccessFile
import java.util.ArrayDeque
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

internal data class DiarizationLocalWindowResult(
    val jobId: String,
    val windowStartSample: Long,
    val contentStartInWindowSample: Int,
    val realEndSample: Long,
    val commitStartSample: Long,
    val stableEndSample: Long,
    val finalWindow: Boolean,
    val result: NmnetDiarizationDelta,
)

internal interface SpeakerDiarizationLocalObserver {
    fun onWindow(result: DiarizationLocalWindowResult)
    fun onFlushed(delta: NmnetDiarizationDelta)
    fun onDrained()
    fun onDegraded(reason: SpeakerDiarizationDegradedReason, message: String)
}

private data class DiarizationLocalJob(
    val jobId: String,
    val offsetBytes: Long,
    val sampleCount: Int,
    val windowStartSample: Long,
    val contentStartInWindowSample: Int,
    val realEndSample: Long,
    val commitStartSample: Long,
    val stableEndSample: Long,
    val finalWindow: Boolean,
)

/**
 * Incremental on-device executor. PCM remains in the app sandbox and at most one bounded
 * twenty-second window is in native inference at a time.
 */
internal class SpeakerDiarizationLocalClient(
    context: Context,
    workPath: File,
    private val observer: SpeakerDiarizationLocalObserver,
    maxSpeakers: Int = 0,
    loadInference: () -> NmnetDiarizationInference = {
        NmnetDiarizationInference(context.assets, maxSpeakers)
    },
) {
    // One ordered 20 s / 2 s native lane owns history and overlap state.
    private val scheduler = DiarizationWindowScheduler(SAMPLE_RATE, windowMs = 20_000, hopMs = 2_000, rightContextMs = 18_000)
    private val queue = ArrayDeque<DiarizationLocalJob>()
    private val jobsRoot = File(workPath, "speaker-diarization-jobs")
    private val jobDir = File(jobsRoot, "job-${System.nanoTime()}")
    private val spool: DiarizationPcmSpool
    private val executor: ExecutorService = Executors.newSingleThreadExecutor { task ->
        Thread(task, "amphion-diarization").apply { isDaemon = true }
    }
    private val timeoutExecutor: ScheduledExecutorService =
        Executors.newSingleThreadScheduledExecutor { task ->
            Thread(task, "amphion-diarization-watchdog").apply { isDaemon = true }
        }
    private var inference: NmnetDiarizationInference? = null
    private var loadSettled = false
    private var nextJobId = 1
    private var active = false
    private var activeJobId: String? = null
    private var flushing = false
    private var finishWindowQueued = false
    private var finishing = false
    private var stopped = false
    private var closed = false
    private var degraded = false
    private var resourcesClosed = false
    private var drainedNotified = false
    private val quiescentCallbacks = mutableListOf<() -> Unit>()

    init {
        sweepStaleJobs(jobsRoot)
        check(jobDir.mkdirs() || jobDir.isDirectory) { "cannot create ${jobDir.absolutePath}" }
        spool = DiarizationPcmSpool(jobDir)
        executor.execute {
            try {
                val loaded = loadInference()
                synchronized(this) {
                    if (closed) loaded.close() else inference = loaded
                }
            } catch (t: Throwable) {
                synchronized(this) {
                    failLocked(
                        SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE,
                        "speaker diarization model load failed: ${t.message ?: t.javaClass.simpleName}",
                    )
                }
            } finally {
                synchronized(this) {
                    loadSettled = true
                    pumpLocked()
                    closeWhenQuiescentLocked()
                }
            }
        }
    }

    @Synchronized
    fun append(audio: ByteArray) {
        if (closed || finishing || degraded) return
        try {
            spool.append(audio)
            scheduler.acceptSamples(audio.size / 2, 0)
            pumpLocked()
        } catch (t: Throwable) {
            failLocked(
                SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
                "speaker diarization spool failed: ${t.message ?: t.javaClass.simpleName}",
            )
        }
    }

    @Synchronized
    fun finish() {
        if (closed || finishing) return
        finishing = true
        pumpLocked()
        maybeNotifyDrainedLocked()
    }

    @Synchronized
    fun cancel(onQuiescent: (() -> Unit)? = null) {
        onQuiescent?.let(quiescentCallbacks::add)
        if (!closed) {
            closed = true
            queue.clear()
            runCatching { spool.close() }
        }
        closeWhenQuiescentLocked()
    }

    fun cleanup(onQuiescent: (() -> Unit)? = null) = cancel(onQuiescent)

    /** Finish timeout: keep completed evidence, start no more windows, drop the in-flight one. */
    @Synchronized
    fun stopInference() {
        if (closed) return
        stopped = true
        queue.clear()
    }

    private fun submitLocked(window: DiarizationInferenceWindow?) {
        if (window == null) return
        val sampleCount = minOf(WINDOW_SAMPLES.toLong(), window.realEndSample - window.startSample)
            .coerceAtLeast(0).toInt()
        val offsetSample = window.startSample
        queue += DiarizationLocalJob(
            jobId = "w${nextJobId++.toString().padStart(8, '0')}",
            offsetBytes = offsetSample * 2,
            sampleCount = sampleCount,
            windowStartSample = window.startSample,
            contentStartInWindowSample = 0,
            realEndSample = window.realEndSample,
            commitStartSample = window.commitStartSample,
            stableEndSample = window.stableEndSample,
            finalWindow = window.finalWindow,
        )
    }

    private fun pumpLocked() {
        if (closed || degraded || stopped || active || !loadSettled) return
        if (!finishWindowQueued) {
            scheduler.takeAvailable((2 - queue.size).coerceAtLeast(0)).forEach(::submitLocked)
            if (finishing && !scheduler.hasAvailable() && queue.size < 2) {
                submitLocked(scheduler.finish())
                finishWindowQueued = true
            }
        }
        val job = queue.pollFirst()
        if (job == null) {
            maybeNotifyDrainedLocked()
            return
        }
        active = true
        activeJobId = job.jobId
        executor.execute { execute(job) }
    }

    private fun execute(job: DiarizationLocalJob) {
        val watchdog = timeoutExecutor.schedule({
            val notify = synchronized(this) {
                if (!active || activeJobId != job.jobId || closed || degraded || stopped) false else {
                    degraded = true
                    queue.clear()
                    true
                }
            }
            if (notify) observer.onDegraded(
                SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT,
                "speaker diarization inference timed out after ${INFERENCE_TIMEOUT_MS}ms",
            )
        }, INFERENCE_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        try {
            val samples = readWindow(job)
            val result = checkNotNull(inference) { "speaker diarization inference is unavailable" }
                .process(samples, job.sampleCount, job.windowStartSample / 32_000)
            val deliver = synchronized(this) { !closed && !degraded && !stopped && activeJobId == job.jobId }
            if (deliver) {
                observer.onWindow(
                    DiarizationLocalWindowResult(
                        job.jobId,
                        job.windowStartSample,
                        job.contentStartInWindowSample,
                        job.realEndSample,
                        job.commitStartSample,
                        result.rolesCommittedThroughSample,
                        job.finalWindow,
                        result,
                    ),
                )
            }
        } catch (t: Throwable) {
            synchronized(this) {
                if (!closed && !degraded && !stopped) failLocked(
                    if (t is java.io.IOException) SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE
                    else SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
                    "speaker diarization inference failed: ${t.message ?: t.javaClass.simpleName}",
                )
            }
        } finally {
            watchdog.cancel(false)
            synchronized(this) {
                active = false
                activeJobId = null
                if (!closed) runCatching {
                    spool.discardBefore(queue.peekFirst()?.offsetBytes ?: scheduler.nextWindowStartSample()?.times(2)
                        ?: maxOf(0, spool.endOffset - WINDOW_SAMPLES * 2))
                }.onFailure { failLocked(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
                    "diarization PCM cleanup failed: ${it.message}") }
                if (closed) closeWhenQuiescentLocked() else {
                    pumpLocked()
                    maybeNotifyDrainedLocked()
                }
            }
        }
    }

    private fun readWindow(job: DiarizationLocalJob): FloatArray {
        val bytes = synchronized(this) {
            check(!closed) { "speaker diarization session is closed" }
            spool.read(job.offsetBytes, job.sampleCount * 2)
        }
        val result = FloatArray(WINDOW_SAMPLES)
        var source = 0
        var destination = job.contentStartInWindowSample
        while (source + 1 < bytes.size) {
            val value = (bytes[source].toInt() and 0xff) or (bytes[source + 1].toInt() shl 8)
            result[destination++] = value.toShort() / 32768f
            source += 2
        }
        return result
    }

    private fun failLocked(reason: SpeakerDiarizationDegradedReason, message: String) {
        if (degraded || closed) return
        degraded = true
        queue.clear()
        executor.execute { observer.onDegraded(reason, message) }
        maybeNotifyDrainedLocked()
    }

    private fun maybeNotifyDrainedLocked() {
        if (!finishing || closed || active || queue.isNotEmpty() || drainedNotified || flushing || !loadSettled) return
        if (degraded || stopped) {
            drainedNotified = true
            executor.execute { if (synchronized(this) { !closed }) observer.onDrained() }
            return
        }
        if (!finishWindowQueued) return
        flushing = true
        executor.execute {
            try {
                val delta = checkNotNull(inference).finish()
                if (synchronized(this) { !closed && !stopped && !degraded }) observer.onFlushed(delta)
            } catch (t: Throwable) {
                synchronized(this) { if (!closed && !stopped) failLocked(
                    SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE, "NMNet flush failed: ${t.message}") }
            } finally {
                val notify = synchronized(this) {
                    flushing = false
                    val notify = !closed && !drainedNotified
                    if (notify) drainedNotified = true
                    closeWhenQuiescentLocked()
                    notify
                }
                if (notify) observer.onDrained()
            }
        }
    }

    private fun closeWhenQuiescentLocked() {
        if (!closed || !loadSettled || active || flushing || resourcesClosed) return
        resourcesClosed = true
        runCatching { inference?.close() }
        inference = null
        runCatching { spool.remove() }
        jobDir.delete()
        executor.shutdown()
        timeoutExecutor.shutdown()
        val callbacks = quiescentCallbacks.toList()
        quiescentCallbacks.clear()
        callbacks.forEach { it() }
    }

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val WINDOW_SAMPLES = 320_000
        const val INFERENCE_TIMEOUT_MS = 60_000L
        private val sweptJobRoots = ConcurrentHashMap.newKeySet<String>()

        // Job files are removed when a client becomes quiescent, which a killed process never
        // reaches. The first client of a process removes whatever earlier processes left.
        fun sweepStaleJobs(root: File) {
            if (sweptJobRoots.add(root.absolutePath)) root.listFiles()?.forEach { runCatching { it.deleteRecursively() } }
        }
    }
}
