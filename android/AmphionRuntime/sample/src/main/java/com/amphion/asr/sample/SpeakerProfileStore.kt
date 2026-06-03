package com.amphion.asr.sample

import android.content.Context
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 单目标说话人的本地档案：多段注册录音（WAV）+ 一份声纹向量（target.emb）。
 *
 * 布局（app 私有目录，卸载即清，不需存储权限）：
 * ```
 * filesDir/speaker/
 *   segments/seg_<timestampMs>.wav   每段注册录音，16k mono 16bit
 *   target.emb                       [dim:int32][float32 * dim]，已 L2 归一的声纹
 * ```
 *
 * 声纹是所有段 embedding 的均值：增删任何一段后都应重新 enroll 覆盖 target.emb，否则
 * target.emb 与 segments 不一致。本类只负责存取，重算时机由页面决定。
 */
internal class SpeakerProfileStore(context: Context) {

    private val root = File(context.filesDir, "speaker")
    private val segmentsDir = File(root, "segments")
    private val embFile = File(root, "target.emb")
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun listSegments(): List<File> =
        segmentsDir.listFiles { f -> f.isFile && f.name.endsWith(".wav") }
            ?.sortedBy { it.name }
            ?: emptyList()

    fun segmentCount(): Int = listSegments().size

    fun addSegment(pcm: ShortArray, sampleRate: Int = 16000): File {
        segmentsDir.mkdirs()
        val f = File(segmentsDir, "seg_${System.currentTimeMillis()}.wav")
        WavIo.write(f, pcm, sampleRate)
        return f
    }

    fun deleteSegment(file: File): Boolean = file.delete()

    fun readSegmentFloat(file: File): FloatArray {
        val pcm = WavIo.readPcm(file)
        return FloatArray(pcm.size) { pcm[it] / 32768f }
    }

    fun saveEmbedding(emb: FloatArray) {
        root.mkdirs()
        val buf = ByteBuffer.allocate(4 + emb.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(emb.size)
        for (v in emb) buf.putFloat(v)
        embFile.writeBytes(buf.array())
    }

    fun loadEmbedding(): FloatArray? {
        if (!embFile.exists()) return null
        return try {
            val bytes = embFile.readBytes()
            if (bytes.size < 4) return null
            val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val dim = buf.int
            if (dim <= 0 || bytes.size < 4 + dim * 4) return null
            FloatArray(dim) { buf.float }
        } catch (t: Throwable) {
            null
        }
    }

    fun hasEmbedding(): Boolean = embFile.exists()

    fun clearEmbedding() {
        embFile.delete()
    }

    /**
     * 目标人判定阈值（余弦相似度）：段末打分 score >= 阈值才判为目标。端上可调、持久化。
     * 读取时 clamp 到 [[THRESHOLD_MIN], [THRESHOLD_MAX]]，防越界配置回灌（负阈值=接受所有，无意义）。
     */
    fun getThreshold(): Float =
        prefs.getFloat(KEY_THRESHOLD, DEFAULT_THRESHOLD).coerceIn(THRESHOLD_MIN, THRESHOLD_MAX)

    fun setThreshold(value: Float) {
        prefs.edit().putFloat(KEY_THRESHOLD, value.coerceIn(THRESHOLD_MIN, THRESHOLD_MAX)).apply()
    }

    companion object {
        /** 端上默认阈值；沿用此前 sample 硬编码的保守点，避免行为漂移。 */
        const val DEFAULT_THRESHOLD = 0.40f

        /** UI 可调区间：余弦相似度的有效判定区，负阈值无意义故从 0 起。 */
        const val THRESHOLD_MIN = 0.0f
        const val THRESHOLD_MAX = 1.0f

        private const val PREFS_NAME = "amphion_speaker"
        private const val KEY_THRESHOLD = "target_threshold"
    }
}
