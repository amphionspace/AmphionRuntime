package com.amphion.dingqiao.diarization

import com.amphion.dingqiao.SpeakerDiarizationDegradedReason
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** 一段发声的会话时间，`end` 是开区间端点。 */
internal data class TimeSpan(val begin: Long, val end: Long)

/** 一次引擎报告，帧号已折算成会话毫秒。与鸿蒙 `SortformerLocalEvent` 同字段。 */
internal data class SortformerLocalEvent(
    val kind: String,
    val beginTime: Long,
    val endTime: Long,
    val inferenceMs: Double,
    /** 每个槽位（4 个）内的发声区间，单位毫秒，端点为 [begin, end)。 */
    val runs: List<List<TimeSpan>>,
) {
    val preview: Boolean get() = kind == "preview"
}

internal data class SortformerLocalFeedResult(
    val jobId: String,
    /** 引擎已消费到的音频，单位采样点。 */
    val audioEndSample: Long,
    /** 前端已产出的最后一个 mel 帧对应的会话时间，毫秒。 */
    val melEndTime: Long,
    val events: List<SortformerLocalEvent>,
    /** 原生调用的墙钟耗时。 */
    val inferenceWallMs: Double,
    val flushed: Boolean,
)

internal interface SortformerLocalObserver {
    fun onFeedResult(result: SortformerLocalFeedResult)
    fun onDrained()
    fun onDegraded(reason: SpeakerDiarizationDegradedReason, message: String)
}

/**
 * Sortformer 链路的端侧增量执行器。PCM 在内存里排队，按序交给同一个原生引擎，同一时刻只有一次
 * 调用在飞，所以说话人缓存严格按音频顺序推进。与鸿蒙 `SortformerLocalClient.ets` 同一套语义，
 * 只是用单线程执行器代替 Promise 串行。
 */
internal class SortformerLocalClient(
    private val observer: SortformerLocalObserver,
    private val openInference: () -> SortformerEngine,
    private val diagnostic: ((String, Map<String, Any?>) -> Unit)? = null,
) {
    private val worker = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "amphion-sortformer-client").apply { isDaemon = true }
    }
    private val lock = Object()
    private var inference: SortformerEngine? = null
    private var loadFailed = false
    private val pending = ArrayDeque<ShortArray>()
    private var pendingSamples = 0
    private var fedSamples = 0L
    private var nextJobId = 1
    private var inFlight = false
    private var finishing = false
    private var flushQueued = false
    private var flushed = false
    private var stopped = false
    private var closed = false
    private var degraded = false
    private val drainedNotified = AtomicBoolean(false)
    private val quiescentCallbacks = mutableListOf<() -> Unit>()

    init {
        worker.execute {
            try {
                val opened = openInference()
                synchronized(lock) {
                    if (closed) {
                        opened.close()
                    } else {
                        inference = opened
                    }
                }
            } catch (error: Throwable) {
                synchronized(lock) { loadFailed = true }
                fail(
                    SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
                    "speaker diarization model unavailable: ${error.message}",
                )
            }
            pump()
        }
    }

    fun append(audio: ByteArray) {
        var behindSeconds = -1L
        synchronized(lock) {
            if (closed || finishing || degraded || stopped) return
            val usable = audio.size - audio.size % 2
            if (usable <= 0) return
            val samples = ShortArray(usable / 2)
            for (index in samples.indices) {
                val low = audio[index * 2].toInt() and 0xFF
                val high = audio[index * 2 + 1].toInt()
                samples[index] = ((high shl 8) or low).toShort()
            }
            pending.addLast(samples)
            pendingSamples += samples.size
            if (pendingSamples > MAX_PENDING_SAMPLES) {
                behindSeconds = Math.round(pendingSamples.toDouble() / SAMPLE_RATE)
            }
        }
        // 观察者回调一律在锁外，避免它回调回本客户端时重入。
        if (behindSeconds >= 0) {
            fail(
                SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT,
                "speaker diarization fell $behindSeconds s behind the audio",
            )
            return
        }
        pump()
    }

    /** 还没交给引擎的音频加上在飞的那一次，按整秒计。 */
    fun pendingWindowCount(): Int = synchronized(lock) {
        if (closed || degraded || stopped) return 0
        Math.ceil(pendingSamples.toDouble() / SAMPLE_RATE).toInt() + if (inFlight) 1 else 0
    }

    fun finish() {
        synchronized(lock) {
            if (closed || finishing) return
            finishing = true
        }
        pump()
        maybeNotifyDrained()
    }

    fun cancel(onQuiescent: (() -> Unit)? = null) {
        synchronized(lock) {
            if (onQuiescent != null) quiescentCallbacks.add(onQuiescent)
            if (!closed) {
                closed = true
                pending.clear()
                pendingSamples = 0
            }
        }
        closeWhenQuiescent()
    }

    fun cleanup(onQuiescent: (() -> Unit)? = null) = cancel(onQuiescent)

    /** 收尾超时：保留已送出的结果，不再发起新调用，在飞的那次结果丢弃。 */
    fun stopInference() {
        synchronized(lock) {
            if (closed) return
            stopped = true
            pending.clear()
            pendingSamples = 0
        }
    }

    private fun pump() {
        val job: Triple<String, FloatArray, Boolean>
        synchronized(lock) {
            if (closed || degraded || stopped || inFlight) return
            val engine = inference ?: run {
                if (loadFailed) maybeNotifyDrained()
                return
            }
            if (flushed) {
                maybeNotifyDrained()
                return
            }
            val flush = finishing && !flushQueued
            if (!flush && pendingSamples < FEED_MIN_SAMPLES) return
            val samples = FloatArray(pendingSamples)
            var offset = 0
            for (part in pending) {
                for (index in part.indices) samples[offset + index] = part[index] / 32768.0f
                offset += part.size
            }
            pending.clear()
            fedSamples += pendingSamples
            pendingSamples = 0
            if (flush) flushQueued = true
            val id = "f%08d".format(nextJobId)
            nextJobId += 1
            inFlight = true
            job = Triple(id, samples, flush)
            // engine 在锁内取出，execute 在 worker 线程上用它。
            worker.execute { execute(engine, job.first, job.second, job.third) }
        }
    }

    private fun execute(
        engine: SortformerEngine,
        jobId: String,
        samples: FloatArray,
        flush: Boolean,
    ) {
        val startedNs = System.nanoTime()
        try {
            val result = engine.feed(samples, flush)
            val wallMs = (System.nanoTime() - startedNs) / 1_000_000.0
            val dropped = synchronized(lock) {
                inFlight = false
                if (flush) flushed = true
                closed || stopped || degraded
            }
            if (dropped) {
                closeWhenQuiescent()
                return
            }
            deliver(jobId, result, wallMs, flush)
            if (flush) maybeNotifyDrained() else pump()
        } catch (error: Throwable) {
            synchronized(lock) { inFlight = false }
            fail(
                SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE,
                "speaker diarization inference failed: ${error.message}",
            )
        }
    }

    private fun deliver(
        jobId: String,
        result: SortformerFeedResult,
        wallMs: Double,
        flush: Boolean,
    ) {
        val events = result.events.map { event ->
            SortformerLocalEvent(
                kind = event.kind,
                beginTime = event.beginFrame * 10L,
                endTime = (event.beginFrame + event.frames) * 10L,
                inferenceMs = event.inferenceMs,
                runs = event.runs.map { slot ->
                    slot.map { run -> TimeSpan(run.begin * 10L, run.end * 10L) }
                },
            )
        }
        diagnostic?.let { record ->
            val behind = synchronized(lock) { fedSamples + pendingSamples - result.samples }
            record(
                "DIARIZATION_QUEUE",
                mapOf(
                    "jobId" to jobId,
                    "pendingJobs" to synchronized(lock) {
                        Math.ceil(pendingSamples.toDouble() / SAMPLE_RATE).toInt()
                    },
                    "nativeCallsInFlight" to 1,
                    "completedThroughSample" to result.samples,
                    "audioDelayMs" to maxOf(0L, behind / 16),
                    "elapsedMs" to wallMs,
                    "melFrames" to result.melFrames,
                    "events" to events.size,
                    "flush" to flush,
                ),
            )
        }
        observer.onFeedResult(
            SortformerLocalFeedResult(
                jobId = jobId,
                audioEndSample = result.samples,
                melEndTime = result.melFrames * 10L,
                events = events,
                inferenceWallMs = wallMs,
                flushed = flush,
            ),
        )
    }

    private fun maybeNotifyDrained() {
        val ready = synchronized(lock) {
            !inFlight && pendingSamples == 0 && (flushed || loadFailed || degraded || stopped)
        }
        if (ready && drainedNotified.compareAndSet(false, true)) observer.onDrained()
        closeWhenQuiescent()
    }

    private fun fail(reason: SpeakerDiarizationDegradedReason, message: String) {
        val first = synchronized(lock) {
            if (degraded) return@synchronized false
            degraded = true
            pending.clear()
            pendingSamples = 0
            true
        }
        if (!first) return
        observer.onDegraded(reason, message)
        maybeNotifyDrained()
    }

    private fun closeWhenQuiescent() {
        val callbacks: List<() -> Unit>
        synchronized(lock) {
            if (!closed || inFlight) return
            inference?.close()
            inference = null
            callbacks = quiescentCallbacks.toList()
            quiescentCallbacks.clear()
        }
        worker.shutdown()
        runCatching { worker.awaitTermination(1, TimeUnit.SECONDS) }
        callbacks.forEach { it() }
    }

    internal companion object {
        const val SAMPLE_RATE = 16_000

        /** 至少积这么多采样点才交给引擎：20 ms 的生产者不必每秒跨 JNI 五十次。
         *  引擎只在块与预览边界动作，所以批量不改变任何结果。 */
        const val FEED_MIN_SAMPLES = SAMPLE_RATE / 2

        /** 允许落后麦克风的积压上限，超过即判定会话停滞，而不是无声增长。 */
        const val MAX_PENDING_SAMPLES = SAMPLE_RATE * 600
    }
}
