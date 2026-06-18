package com.amphion.asr.sample.eval

import android.util.Log
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 增量写入 16-bit PCM mono WAV 文件的工具类。
 *
 * 评估模式需要 per-recording 实例（一次 start..finalize = 一段独立 WAV），
 * 单一职责：只写 WAV，不做 transcript 日志。
 *
 * 用法：
 * ```
 * val w = WavWriter.create(file, sampleRate = 16000)
 * w?.appendPcm(samples)  // 多次调用
 * w?.finalize()           // 关闭并补 header（必须显式调用，否则 header data_size 为 0 不可播）
 * ```
 *
 * 线程安全：内部串行化所有写操作，调用方可在任意线程调用，但建议固定单线程（如录音线程）。
 * 失败处理：所有 IO 异常仅 log warn 并丢弃当次写入；不抛出，不影响主路径。
 */
class WavWriter private constructor(
    private val file: File,
    private val sampleRate: Int,
) {

    private val wav: RandomAccessFile = RandomAccessFile(file, "rw")
    private val pcmBuf = ByteBuffer.allocate(PCM_BUF_BYTES).order(ByteOrder.LITTLE_ENDIAN)
    private val lock = Any()
    private var totalSamples: Long = 0
    private var finalized = false

    init {
        wav.setLength(0)
        writeHeader(0)
    }

    /** 已写入的 16-bit PCM sample 数量。除以 sampleRate 得秒数。 */
    val sampleCount: Long
        get() = synchronized(lock) { totalSamples }

    /** 已写入的毫秒数。 */
    val durationMs: Long
        get() = synchronized(lock) {
            if (sampleRate <= 0) 0L else totalSamples * 1000L / sampleRate
        }

    /** 追加一段 16-bit PCM；空数组 no-op。 */
    fun appendPcm(samples: ShortArray) {
        if (samples.isEmpty()) return
        synchronized(lock) {
            if (finalized) return
            try {
                var off = 0
                val cap = pcmBuf.capacity() / 2
                while (off < samples.size) {
                    pcmBuf.clear()
                    val n = minOf(samples.size - off, cap)
                    for (i in 0 until n) pcmBuf.putShort(samples[off + i])
                    wav.write(pcmBuf.array(), 0, n * 2)
                    off += n
                    totalSamples += n.toLong()
                }
            } catch (t: IOException) {
                Log.w(TAG, "appendPcm failed: ${t.message}")
            }
        }
    }

    /** 写回正确的 WAV header（含 data 长度）并关闭文件。幂等。 */
    fun finalize() {
        synchronized(lock) {
            if (finalized) return
            finalized = true
            try {
                wav.seek(0)
                writeHeader(totalSamples)
                wav.fd.sync()
            } catch (t: IOException) {
                Log.w(TAG, "finalize header failed: ${t.message}")
            }
            try {
                wav.close()
            } catch (t: IOException) {
                Log.w(TAG, "close wav failed: ${t.message}")
            }
        }
    }

    private fun writeHeader(numSamples: Long) {
        val dataBytes = (numSamples * 2L).coerceAtMost(MAX_DATA_BYTES).toInt()
        val chunkSize = 36 + dataBytes
        val byteRate = sampleRate * 1 * 16 / 8
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray(Charsets.US_ASCII))
        header.putInt(chunkSize)
        header.put("WAVE".toByteArray(Charsets.US_ASCII))
        header.put("fmt ".toByteArray(Charsets.US_ASCII))
        header.putInt(16)
        header.putShort(1)  // PCM format
        header.putShort(1)  // mono
        header.putInt(sampleRate)
        header.putInt(byteRate)
        header.putShort(2)  // block align
        header.putShort(16) // bits per sample
        header.put("data".toByteArray(Charsets.US_ASCII))
        header.putInt(dataBytes)
        wav.write(header.array(), 0, 44)
    }

    companion object {
        private const val TAG = "WavWriter"
        private const val PCM_BUF_BYTES = 8192
        private const val MAX_DATA_BYTES = 0x7FFFFFFFL

        /**
         * 创建一个新的 WavWriter；失败返回 null（调用方应跳过本次录音）。
         * 不会自动创建父目录，请先 mkdirs。
         */
        fun create(file: File, sampleRate: Int = 16000): WavWriter? = try {
            WavWriter(file, sampleRate)
        } catch (t: Throwable) {
            Log.w(TAG, "create failed: ${t.message}")
            null
        }
    }
}
