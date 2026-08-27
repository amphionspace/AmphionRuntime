package com.amphion.dingqiao.diarization

import android.content.Context
import com.amphion.dingqiao.DingqiaoSpeakerModelAssets
import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import java.io.File
import java.io.RandomAccessFile
import java.util.ArrayDeque
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
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
    val result: DiarizationWindowInferenceResult,
)

internal interface SpeakerDiarizationLocalObserver {
    fun onWindow(result: DiarizationLocalWindowResult)
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
 * ten-second window is in native inference at a time.
 */
internal class SpeakerDiarizationLocalClient(
    context: Context,
    workPath: File,
    private val observer: SpeakerDiarizationLocalObserver,
) {
    private val scheduler = DiarizationWindowScheduler(SAMPLE_RATE)
    private val queue = ArrayDeque<DiarizationLocalJob>()
    private val jobDir = File(File(workPath, "speaker-diarization-jobs"), "job-${System.nanoTime()}")
    private val spoolPath = File(jobDir, "audio.pcm")
    private val spool: RandomAccessFile
    private val executor: ExecutorService = Executors.newSingleThreadExecutor { task ->
        Thread(task, "amphion-diarization").apply { isDaemon = true }
    }
    private val timeoutExecutor: ScheduledExecutorService =
        Executors.newSingleThreadScheduledExecutor { task ->
            Thread(task, "amphion-diarization-watchdog").apply { isDaemon = true }
        }
    private var inference: SpeakerDiarizationInference? = null
    private var loadSettled = false
    private var nextJobId = 1
    private var active = false
    private var finishing = false
    private var closed = false
    private var degraded = false
    private var resourcesClosed = false
    private var drainedNotified = false
    private val quiescentCallbacks = mutableListOf<() -> Unit>()

    init {
        check(jobDir.mkdirs() || jobDir.isDirectory) { "cannot create ${jobDir.absolutePath}" }
        spool = RandomAccessFile(spoolPath, "rw")
        executor.execute {
            try {
                val (segmentation, embedding) =
                    DingqiaoSpeakerModelAssets.ensureDiarizationInstalled(context, workPath)
                val loaded = SpeakerDiarizationInference(
                    segmentation.absolutePath,
                    embedding.absolutePath,
                )
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
            spool.seek(spool.length())
            spool.write(audio)
            scheduler.acceptSamples(audio.size / 2).forEach(::submitLocked)
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
        if (!degraded) runCatching { submitLocked(scheduler.finish()) }.onFailure {
            failLocked(
                SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
                "speaker diarization finish failed: ${it.message ?: it.javaClass.simpleName}",
            )
        }
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
    fun checkpointDir(): File = jobDir

    private fun submitLocked(window: DiarizationInferenceWindow) {
        val sampleCount = minOf(WINDOW_SAMPLES.toLong(), window.realEndSample - window.startSample)
            .coerceAtLeast(0).toInt()
        val offsetSample = (window.realEndSample - sampleCount).coerceAtLeast(0)
        queue += DiarizationLocalJob(
            jobId = "w${nextJobId++.toString().padStart(8, '0')}",
            offsetBytes = offsetSample * 2,
            sampleCount = sampleCount,
            windowStartSample = (window.realEndSample - WINDOW_SAMPLES).coerceAtLeast(0),
            contentStartInWindowSample = WINDOW_SAMPLES - sampleCount,
            realEndSample = window.realEndSample,
            commitStartSample = window.commitStartSample,
            stableEndSample = window.stableEndSample,
            finalWindow = window.finalWindow,
        )
    }

    private fun pumpLocked() {
        if (closed || degraded || active || !loadSettled) return
        val job = queue.pollFirst()
        if (job == null) {
            maybeNotifyDrainedLocked()
            return
        }
        active = true
        executor.execute { execute(job) }
    }

    private fun execute(job: DiarizationLocalJob) {
        val watchdog = timeoutExecutor.schedule({
            val notify = synchronized(this) {
                if (!active || closed || degraded) false else {
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
                .process(samples)
            val deliver = synchronized(this) { !closed && !degraded }
            if (deliver) {
                observer.onWindow(
                    DiarizationLocalWindowResult(
                        job.jobId,
                        job.windowStartSample,
                        job.contentStartInWindowSample,
                        job.realEndSample,
                        job.commitStartSample,
                        job.stableEndSample,
                        job.finalWindow,
                        result,
                    ),
                )
            }
        } catch (t: Throwable) {
            synchronized(this) {
                if (!closed && !degraded) failLocked(
                    SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
                    "speaker diarization inference failed: ${t.message ?: t.javaClass.simpleName}",
                )
            }
        } finally {
            watchdog.cancel(false)
            synchronized(this) {
                active = false
                if (closed) closeWhenQuiescentLocked() else {
                    pumpLocked()
                    maybeNotifyDrainedLocked()
                }
            }
        }
    }

    private fun readWindow(job: DiarizationLocalJob): FloatArray {
        val bytes = ByteArray(job.sampleCount * 2)
        synchronized(this) {
            check(!closed) { "speaker diarization session is closed" }
            spool.seek(job.offsetBytes)
            spool.readFully(bytes)
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
        if (finishing && !active && queue.isEmpty() && !drainedNotified) {
            drainedNotified = true
            executor.execute { observer.onDrained() }
        }
    }

    private fun closeWhenQuiescentLocked() {
        if (!closed || !loadSettled || active || resourcesClosed) return
        resourcesClosed = true
        runCatching { inference?.close() }
        inference = null
        runCatching { spool.close() }
        spoolPath.delete()
        File(jobDir, "window-journal.jsonl").delete()
        File(jobDir, "embedding-index.jsonl").delete()
        File(jobDir, "embedding-index.bin").delete()
        File(jobDir, "speaker-registry.json").delete()
        jobDir.delete()
        executor.shutdown()
        timeoutExecutor.shutdown()
        val callbacks = quiescentCallbacks.toList()
        quiescentCallbacks.clear()
        callbacks.forEach { it() }
    }

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val WINDOW_SAMPLES = 160_000
        const val INFERENCE_TIMEOUT_MS = 10_000L
    }
}
