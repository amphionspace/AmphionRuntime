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
