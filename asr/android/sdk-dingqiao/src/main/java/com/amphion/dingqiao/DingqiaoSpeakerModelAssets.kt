package com.amphion.dingqiao

import android.content.Context
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

internal object DingqiaoSpeakerModelAssets {
    private const val ASSET_PATH = "amphion-dingqiao/$DINGQIAO_SPEAKER_MODEL_FILENAME"
    private const val MIN_BYTES = 30L * 1024L * 1024L
    private const val SEGMENTATION_FILENAME = "pyannote-segmentation-3.0.onnx"
    private const val SEGMENTATION_ASSET_PATH = "amphion-dingqiao/$SEGMENTATION_FILENAME"
    private const val SEGMENTATION_MIN_BYTES = 5L * 1024L * 1024L
    private const val SORTFORMER_DIRNAME = "sortformer-66M-4spk"
    private const val SORTFORMER_ASSET_DIR = "amphion-dingqiao/$SORTFORMER_DIRNAME"

    // 大小取交付清单 sortformer_diarization_v1.json 的 sizeBytes，用作安装完整性下限。
    private val SORTFORMER_ASSETS = listOf(
        "pre_encode.ort" to 2_113_472L,
        "encoder_layers.int8.ort" to 69_971_216L,
        "speaker_head.ort" to 4_111_384L,
        "spkcache_update.ort" to 535_480L,
        "learnable_sil_emb.npy" to 2_176L,
        "mel_window_hann400_periodic_false.npy" to 1_728L,
        "mel_filterbank_128x257_slaney.npy" to 131_712L,
    )

    @Synchronized
    fun ensureInstalled(context: Context, dest: File): File {
        return ensureAssetInstalled(context, ASSET_PATH, dest, MIN_BYTES)
    }

    @Synchronized
    fun ensureDiarizationInstalled(context: Context, workPath: File): Pair<File, File> {
        val embedding = ensureInstalled(context, File(workPath, DINGQIAO_SPEAKER_MODEL_FILENAME))
        val segmentation = ensureAssetInstalled(
            context,
            SEGMENTATION_ASSET_PATH,
            File(workPath, SEGMENTATION_FILENAME),
            SEGMENTATION_MIN_BYTES,
        )
        return segmentation to embedding
    }

    @Synchronized
    fun ensureComplementaryDiarizationInstalled(context: Context, workPath: File): File =
        ensureAssetInstalled(context, "amphion-dingqiao/campplus.onnx",
            File(workPath, "campplus.onnx"), 20L * 1024L * 1024L)

    @Synchronized
    fun ensureCommunityInstalled(context: Context, workPath: File): List<File> {
        // The INT8 encoder replaced the FP32 one; drop the superseded 21 MB copy.
        File(workPath, "community-wespeaker-encoder.fp32.onnx").delete()
        return communityAssets(context, workPath)
    }

    /**
     * 装好 Sortformer 的七个资产并返回它们所在的目录。文件名必须与交付清单一致：原生侧按
     * 固定名字从该目录读（`sortformer_diarization_v1.json` 的 `files`）。
     */
    @Synchronized
    fun ensureSortformerInstalled(context: Context, workPath: File): File {
        val dir = File(workPath, SORTFORMER_DIRNAME)
        for ((name, size) in SORTFORMER_ASSETS) {
            ensureAssetInstalled(context, "$SORTFORMER_ASSET_DIR/$name", File(dir, name), size)
        }
        return dir
    }

    fun isSortformerReady(workPath: File): Boolean {
        val dir = File(workPath, SORTFORMER_DIRNAME)
        return SORTFORMER_ASSETS.all { (name, size) -> isReady(File(dir, name), size) }
    }

    private fun communityAssets(context: Context, workPath: File): List<File> = listOf(
        SEGMENTATION_FILENAME to SEGMENTATION_MIN_BYTES,
        "community-wespeaker-encoder.int8.onnx" to 5_468_354L,
        "community-wespeaker-pool.fp32.onnx" to 5_264_664L,
        "community-feature.f32" to 83_840L,
        "community-plda.f64" to 398_352L,
    ).map { (name, size) ->
        ensureAssetInstalled(context, "amphion-dingqiao/$name", File(workPath, name), size)
    }

    private fun ensureAssetInstalled(
        context: Context,
        assetPath: String,
        dest: File,
        minBytes: Long,
    ): File {
        if (isReady(dest, minBytes)) return dest

        dest.parentFile?.mkdirs()
        val tmp = File(dest.parentFile, "${dest.name}.tmp")
        try {
            context.assets.open(assetPath).use { input ->
                FileOutputStream(tmp).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buffer)
                        if (n <= 0) break
                        output.write(buffer, 0, n)
                    }
                    output.fd.sync()
                }
            }
            if (!isReady(tmp, minBytes)) {
                throw IOException("embedded model is incomplete: ${tmp.length()} bytes")
            }
            if (dest.exists() && !dest.delete()) {
                throw IOException("cannot replace existing speaker model: ${dest.absolutePath}")
            }
            if (!tmp.renameTo(dest)) {
                throw IOException("cannot move speaker model into place: ${dest.absolutePath}")
            }
            return dest
        } catch (t: Throwable) {
            tmp.delete()
            throw IllegalStateException(
                "speaker model install failed: $assetPath -> ${dest.absolutePath}: ${t.message}",
                t,
            )
        }
    }

    fun isReady(file: File): Boolean =
        file.isFile && file.canRead() && file.length() >= MIN_BYTES

    private fun isReady(file: File, minBytes: Long): Boolean =
        file.isFile && file.canRead() && file.length() >= minBytes
}
