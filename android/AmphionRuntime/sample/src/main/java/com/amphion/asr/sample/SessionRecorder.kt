package com.amphion.asr.sample

import android.content.Context
import android.util.Log
import java.io.BufferedWriter
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStreamWriter
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 调试落盘工具：把一次"开始识别 -> 停止识别"期间的 PCM 与 ASR 事件落到磁盘。
 *
 * 目录布局（externalFilesDir 在 Scoped Storage 下无需额外权限，便于 adb pull）：
 * ```
 * <externalFilesDir>/asr-debug/<yyyy-MM-dd_HHmmss>/
 *   audio.wav        # mono / 16 kHz / 16-bit PCM
 *   transcript.txt   # 每行一个事件，格式：yyyy-MM-dd HH:mm:ss.SSS  TAG  payload
 * ```
 *
 * 写入失败只 log warn，不影响主路径录音 / 识别。
 *
 * 不是线程安全的"原子"实现，但内部串行化了 wav / txt 写入；调用方仍应在录音线程串行调用
 * [appendPcm]，回调线程串行调用 [logEvent]，[close] 可在任意线程。
 */
class SessionRecorder private constructor(
    val dir: File,
    val audioPath: File,
    val transcriptPath: File,
    private val sampleRate: Int,
) {

    private val wav: RandomAccessFile = RandomAccessFile(audioPath, "rw")
    private val txt: BufferedWriter = BufferedWriter(
        OutputStreamWriter(FileOutputStream(transcriptPath, /* append = */ true), Charsets.UTF_8)
    )
    private val tsFmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
    private val pcmBuf = ByteBuffer.allocate(PCM_BUF_BYTES).order(ByteOrder.LITTLE_ENDIAN)
    private var totalSamples: Long = 0
    private var closed = false
    private val lock = Any()

    init {
        wav.setLength(0)
        writeHeader(0)
    }

    /** 追加一段 16-bit PCM 到 wav。每个 sample 写 2 字节（小端）。 */
    fun appendPcm(samples: ShortArray) {
        if (samples.isEmpty()) return
        synchronized(lock) {
            if (closed) return
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

    /** 写一行事件。[text] 可空（如 SESSION_START / ENDPOINT 这种纯标签）。 */
    fun logEvent(tag: String, text: String? = null) {
        synchronized(lock) {
            if (closed) return
            try {
                val sb = StringBuilder(64)
                    .append(tsFmt.format(Date()))
                    .append("  ").append(tag)
                if (!text.isNullOrEmpty()) {
                    sb.append("  ").append(text.replace("\n", "\\n"))
                }
                sb.append('\n')
                txt.write(sb.toString())
                txt.flush()
            } catch (t: IOException) {
                Log.w(TAG, "logEvent failed: ${t.message}")
            }
        }
    }

    /** 关闭文件并补齐 WAV header；幂等。 */
    fun close() {
        synchronized(lock) {
            if (closed) return
            closed = true
            try {
                wav.seek(0)
                writeHeader(totalSamples)
                wav.fd.sync()
                wav.close()
            } catch (t: IOException) {
                Log.w(TAG, "close wav failed: ${t.message}")
            }
            try {
                txt.flush()
                txt.close()
            } catch (t: IOException) {
                Log.w(TAG, "close txt failed: ${t.message}")
            }
        }
    }

    /** 录到目前为止的样本数（毫秒可由调用方 / 32 * 2 估算）。 */
    val sampleCount: Long
        get() = synchronized(lock) { totalSamples }

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
        header.putShort(1)
        header.putShort(1)
        header.putInt(sampleRate)
        header.putInt(byteRate)
        header.putShort(2)
        header.putShort(16)
        header.put("data".toByteArray(Charsets.US_ASCII))
        header.putInt(dataBytes)
        wav.write(header.array(), 0, 44)
    }

    companion object {
        private const val TAG = "SessionRecorder"
        private const val PCM_BUF_BYTES = 8192
        private const val MAX_DATA_BYTES = 0x7FFFFFFFL // 不超过 Int 上限即可

        /**
         * 在 externalFilesDir/asr-debug/<timestamp>/ 下创建 audio.wav + transcript.txt。
         *
         * 任何阶段失败都返回 null（调用方应继续走识别主路径而不要抛）。
         */
        fun create(ctx: Context, sampleRate: Int = 16000): SessionRecorder? {
            return try {
                val base = ctx.getExternalFilesDir(null) ?: ctx.filesDir
                val parent = File(base, "asr-debug")
                if (!parent.isDirectory && !parent.mkdirs()) {
                    Log.w(TAG, "cannot mkdir ${parent.absolutePath}")
                    return null
                }
                val stamp = SimpleDateFormat("yyyy-MM-dd_HHmmss", Locale.US).format(Date())
                val dir = File(parent, stamp)
                if (!dir.isDirectory && !dir.mkdirs()) {
                    Log.w(TAG, "cannot mkdir ${dir.absolutePath}")
                    return null
                }
                SessionRecorder(
                    dir = dir,
                    audioPath = File(dir, "audio.wav"),
                    transcriptPath = File(dir, "transcript.txt"),
                    sampleRate = sampleRate,
                )
            } catch (t: Throwable) {
                Log.w(TAG, "create failed: ${t.message}")
                null
            }
        }
    }
}
