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
) {

    private val gainFactor: Float = if (gainDb == 0f) 1f else Math.pow(10.0, gainDb / 20.0).toFloat()
    private val running = AtomicBoolean(false)
    private var thread: Thread? = null
    private var record: AudioRecord? = null

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
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
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
            while (running.get()) {
                val n = try {
                    r.read(buf, 0, buf.size)
                } catch (t: Throwable) {
                    onError("read failed: ${t.message}")
                    break
                }
                if (n > 0) {
                    val out = buf.copyOf(n)
                    if (gainFactor != 1f) applyGain(out, gainFactor)
                    onPcm(out)
                } else if (n < 0) {
                    Log.w("AudioRecorder", "read returned $n")
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

    fun stop() {
        running.set(false)
        thread?.join(500)
        thread = null
    }

    private companion object {
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
