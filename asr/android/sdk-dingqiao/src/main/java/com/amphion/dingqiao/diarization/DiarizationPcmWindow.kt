package com.amphion.dingqiao.diarization

import kotlin.math.max
import kotlin.math.roundToInt

/**
 * 角色分离用的近期 PCM 环形缓冲，按**绝对样本位置**索引。与鸿蒙 `DiarizationPcmWindow.ts` 同一契约。
 *
 * 为什么需要它：声纹身份要按发言段算嵌入，而发言段是在块提交（9.92 s）时才由 Sortformer
 * 报出来的，[SpeakerDiarizationSession.append] 原先只是把 PCM 转发给推理客户端、不留存。
 * 这里分流一份，供身份判定按轨道时间回取音频。
 *
 * 契约里最重要的一条：**取不到就返回 null，绝不返回部分或错位的音频**。嵌入拿到错位音频
 * 会安静地判错身份，比直接说"这段没法判"糟得多。
 */
internal class DiarizationPcmWindow(
    sampleRate: Int,
    retainSeconds: Double = RETAIN_SECONDS,
) {
    private val sampleRate = max(1, sampleRate)
    private val capacity = max(1, (this.sampleRate * max(0.001, retainSeconds)).roundToInt())
    private val buffer = ShortArray(capacity)
    /** 自 reset 以来写入的总样本数，即绝对位置的上界。 */
    private var written = 0L

    /** 追加一段 int16 LE PCM。字节数为奇数时丢弃末尾那个不完整样本。 */
    fun append(pcm: ByteArray) {
        val samples = pcm.size / BYTES_PER_SAMPLE
        for (index in 0 until samples) {
            val lo = pcm[index * 2].toInt() and 0xff
            val hi = pcm[index * 2 + 1].toInt()
            buffer[((written + index) % capacity).toInt()] = ((hi shl 8) or lo).toShort()
        }
        written += samples
    }

    /** 仍可取回的最早绝对样本位置。 */
    fun earliestSample(): Long = max(0L, written - capacity)

    fun totalSamples(): Long = written

    /**
     * 按毫秒区间取回音频，归一化为 [-1, 1] 的 FloatArray。
     *
     * 区间必须**完整落在**仍保留的范围内；越界、已被覆盖、或区间为空都返回 null。
     */
    fun slice(beginMs: Long, endMs: Long): FloatArray? {
        val begin = Math.round(beginMs * sampleRate / 1000.0)
        val end = Math.round(endMs * sampleRate / 1000.0)
        if (end <= begin || begin < 0) return null
        if (begin < earliestSample() || end > written) return null
        val out = FloatArray((end - begin).toInt())
        for (index in out.indices) {
            out[index] = buffer[((begin + index) % capacity).toInt()] / 32768f
        }
        return out
    }

    /** 会话结束时清空。 */
    fun reset() {
        written = 0
        buffer.fill(0)
    }

    companion object {
        private const val BYTES_PER_SAMPLE = 2
        /** 默认保留时长。发言段最远来自刚提交的那个块（9.92 s），30 s 留足余量给收尾路径。 */
        const val RETAIN_SECONDS = 30.0
    }
}
