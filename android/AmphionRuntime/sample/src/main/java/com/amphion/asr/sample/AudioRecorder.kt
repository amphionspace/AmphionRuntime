package com.amphion.asr.sample

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 一个最小可用的录音线程：单声道、16kHz、16-bit PCM。
 *
 * 说明：SDK 自身不接管 AudioRecord，集成方需要自己负责录音权限和录音线程；
 * 这里给一个最简洁的参考实现。
 *
 * 回调契约：[onPcm] 收到的 ShortArray 是当帧的独立副本，调用方可安全持有、缓存或跨线程
 * 传递，不会被后续录音覆盖。
 *
 * @param gainDb 软增益（dB），默认 0；vivo/OPPO 等机型 VOICE_RECOGNITION 通道电平偏低
 *               （实测 dump RMS 约 -50 dBFS，比训练分布低 25-30 dB），导致英文清音/爆破音
 *               能量不足；典型值 +10dB 能让 streaming zipformer 在英文 BPE 路径下稳定 emit。
 *               每个 short 乘以 10^(gainDb/20) 后 clip 到 [-32768, 32767]。
 */
class AudioRecorder(
    private val sampleRate: Int = 16000,
    private val onPcm: (ShortArray) -> Unit,
    private val onError: (String) -> Unit,
    gainDb: Float = 0f,
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
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuf <= 0) {
            running.set(false)
            onError("AudioRecord.getMinBufferSize failed: $minBuf")
            return
        }

        val bufBytes = (minBuf * 2).coerceAtLeast(sampleRate / 5 * 2) // 至少 200ms
        val r = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufBytes
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

        val readShorts = sampleRate / 10  // 100ms
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
                    // 必须拷出独立数组再回调：onPcm 的实参可能被调用方跨回调持有（如声纹注册
                    // 把多帧攒进 list 后再合并）。若直接复用内部 buf，下一次 read 会就地覆盖它，
                    // 导致调用方攒到的每一帧都坍缩成「最后一帧」——表现为回放周期性电流声、声纹
                    // 严重失真。ASR 路径因为是同步消费、不跨回调持有引用，才侥幸没暴露此问题。
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
            } catch (_: Throwable) {}
            try {
                r.release()
            } catch (_: Throwable) {}
            record = null
        }, "asr-mic").also { it.isDaemon = true; it.start() }
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
