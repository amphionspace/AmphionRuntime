package com.amphion.dingqiao.demo

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean

class AudioRecorder(
    private val sampleRate: Int = 16000,
    private val onPcm: (ShortArray) -> Unit,
    private val onError: (String) -> Unit,
    gainDb: Float = 10f,
    private val audioSource: DemoAudioSource = DemoAudioSource.VOICE_RECOGNITION,
) {

    private val gainFactor: Float = if (gainDb == 0f) 1f else Math.pow(10.0, gainDb / 20.0).toFloat()
    private val running = AtomicBoolean(false)
    private var thread: Thread? = null
    private var record: AudioRecord? = null
    private val statsLock = Any()
    private var stats = AudioRecorderStats()

    @SuppressLint("MissingPermission")
    fun start() {
        if (!running.compareAndSet(false, true)) return

        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBuf <= 0) {
            running.set(false)
            onError("AudioRecord.getMinBufferSize failed: $minBuf")
            return
        }

        val bufBytes = (minBuf * 2).coerceAtLeast(sampleRate / 5 * 2)
        val r = AudioRecord(
            androidAudioSource(audioSource),
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufBytes,
        )
        if (r.state != AudioRecord.STATE_INITIALIZED) {
            running.set(false)
            onError("AudioRecord init failed")
            r.release()
            return
        }
        record = r
        synchronized(statsLock) {
            stats = AudioRecorderStats(bufferSizeBytes = bufBytes)
        }

        try {
            r.startRecording()
        } catch (t: Throwable) {
            running.set(false)
            onError("startRecording failed: ${t.message}")
            r.release()
            record = null
            return
        }

        val readShorts = sampleRate / 10
        thread = Thread({
            val buf = ShortArray(readShorts)
            var lastCallbackMs = 0L
            while (running.get()) {
                val callbackStartMs = android.os.SystemClock.elapsedRealtime()
                val n = try {
                    r.read(buf, 0, buf.size)
                } catch (t: Throwable) {
                    if (running.get()) onError("read failed: ${t.message}")
                    break
                }
                if (n > 0) {
                    val out = buf.copyOf(n)
                    if (gainFactor != 1f) applyGain(out, gainFactor)
                    onPcm(out)
                    val callbackEndMs = android.os.SystemClock.elapsedRealtime()
                    synchronized(statsLock) {
                        val gap = if (lastCallbackMs == 0L) 0L else callbackStartMs - lastCallbackMs
                        stats = stats.copy(
                            callbackCount = stats.callbackCount + 1,
                            totalBytes = stats.totalBytes + n * 2L,
                            maxCallbackGapMs = maxOf(stats.maxCallbackGapMs, gap),
                            lateCallbackCount = stats.lateCallbackCount + if (gap > LATE_CALLBACK_MS) 1 else 0,
                            maxCallbackWorkMs = maxOf(stats.maxCallbackWorkMs, callbackEndMs - callbackStartMs),
                        )
                    }
                    lastCallbackMs = callbackStartMs
                } else if (n < 0) {
                    if (running.get()) Log.w("AudioRecorder", "read returned $n")
                    break
                }
            }
            try {
                r.stop()
            } catch (_: Throwable) {
            }
            try {
                r.release()
            } catch (_: Throwable) {
            }
            record = null
        }, "dingqiao-mic").also { it.isDaemon = true; it.start() }
    }

    fun stop(): AudioRecorderStats {
        running.set(false)
        // Unblock a device read before waiting. The recorder thread remains the sole owner that
        // releases AudioRecord, so once join returns no PCM callback can arrive after tail flush.
        try {
            record?.stop()
        } catch (_: Throwable) {
        }
        // Do not flush the framing tail until every already-read sample has passed through onPcm.
        // AudioRecord.stop() above unblocks read(), so this wait is bounded by the current callback.
        thread?.join()
        thread = null
        return synchronized(statsLock) { stats }
    }

    private companion object {
        const val LATE_CALLBACK_MS = 200L

        fun androidAudioSource(source: DemoAudioSource): Int = when (source) {
            DemoAudioSource.MIC -> MediaRecorder.AudioSource.MIC
            DemoAudioSource.VOICE_RECOGNITION -> MediaRecorder.AudioSource.VOICE_RECOGNITION
            DemoAudioSource.VOICE_COMMUNICATION -> MediaRecorder.AudioSource.VOICE_COMMUNICATION
        }

        fun applyGain(samples: ShortArray, factor: Float) {
            var i = 0
            while (i < samples.size) {
                val v = (samples[i].toInt() * factor).toInt()
                samples[i] = when {
                    v > 32767 -> 32767
                    v < -32768 -> -32768
                    else -> v.toShort()
                }
                i++
            }
        }
    }
}

data class AudioRecorderStats(
    val overflowCount: Int = 0,
    val callbackCount: Int = 0,
    val totalBytes: Long = 0,
    val bufferSizeBytes: Int = 0,
    val maxCallbackGapMs: Long = 0,
    val lateCallbackCount: Int = 0,
    val maxCallbackWorkMs: Long = 0,
)
