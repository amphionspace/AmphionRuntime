package com.amphion.dingqiao

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

/**
 * 声纹持久化：按 voiceprintId 存储 embedding 与样本元数据。
 *
 * 布局（[workPath]/voiceprints/）：
 * ```
 * voiceprints/
 *   {voiceprintId}/
 *     embedding.bin     [dim:int32][float32 * dim]
 *     meta.json         {"samples":{"vp-id":"sample1.pcm",...}}
 * ```
 */
internal class VoiceprintStore(private val workPath: File) {

    private val root = File(workPath, "voiceprints")

    fun speakerModelPath(): File = File(workPath, DINGQIAO_SPEAKER_MODEL_FILENAME)

    fun saveVoiceprint(samplePaths: List<String>, embedding: FloatArray): VoiceprintRegisterResult {
        val voiceprintId = "vp-${UUID.randomUUID()}"
        val dir = File(root, voiceprintId)
        dir.mkdirs()
        writeEmbedding(File(dir, "embedding.bin"), embedding)
        File(dir, "meta.json").writeText(
            """{"voiceprintId":"$voiceprintId","sample":"${File(samplePaths.first()).name}"}""",
        )
        return VoiceprintRegisterResult(
            voiceprintId = mapOf(voiceprintId to File(samplePaths.first()).name),
            status = DingqiaoVoiceprintStatus.SUCCESS,
        )
    }

    fun deleteVoiceprint(voiceprintId: String): Boolean {
        val dir = File(root, voiceprintId)
        if (!dir.isDirectory) return false
        dir.listFiles()?.forEach { it.delete() }
        return dir.delete()
    }

    fun exists(voiceprintId: String): Boolean =
        File(root, voiceprintId).isDirectory && loadEmbedding(voiceprintId) != null

    fun loadEmbedding(voiceprintId: String): FloatArray? {
        val file = File(root, "$voiceprintId/embedding.bin")
        if (!file.isFile) return null
        return readEmbedding(file)
    }

    fun loadMergedEmbedding(voiceprintIds: List<String>): FloatArray? {
        val embeddings = voiceprintIds.mapNotNull { loadEmbedding(it) }
        if (embeddings.isEmpty()) return null
        if (embeddings.size == 1) return embeddings.first()
        val dim = embeddings.first().size
        if (embeddings.any { it.size != dim }) return null
        val sum = FloatArray(dim)
        for (emb in embeddings) {
            for (i in sum.indices) {
                sum[i] = sum[i] + emb[i]
            }
        }
        val count = embeddings.size.toFloat()
        for (i in sum.indices) {
            sum[i] = sum[i] / count
        }
        return l2Normalize(sum)
    }

    private fun writeEmbedding(file: File, emb: FloatArray) {
        file.parentFile?.mkdirs()
        val buf = ByteBuffer.allocate(4 + emb.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        buf.putInt(emb.size)
        for (v in emb) buf.putFloat(v)
        file.writeBytes(buf.array())
    }

    private fun readEmbedding(file: File): FloatArray? {
        return try {
            val bytes = file.readBytes()
            if (bytes.size < 4) return null
            val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val dim = buf.int
            if (dim <= 0 || bytes.size < 4 + dim * 4) return null
            FloatArray(dim) { buf.float }
        } catch (_: Throwable) {
            null
        }
    }

    private fun l2Normalize(v: FloatArray): FloatArray {
        var sum = 0.0
        for (x in v) sum += x * x
        val norm = kotlin.math.sqrt(sum).toFloat().coerceAtLeast(1e-12f)
        return FloatArray(v.size) { v[it] / norm }
    }
}
