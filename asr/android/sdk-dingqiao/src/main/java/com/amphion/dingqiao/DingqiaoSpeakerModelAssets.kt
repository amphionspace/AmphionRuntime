package com.amphion.dingqiao

import android.content.Context
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

internal object DingqiaoSpeakerModelAssets {
    private const val ASSET_PATH = "amphion-dingqiao/$DINGQIAO_SPEAKER_MODEL_FILENAME"
    private const val MIN_BYTES = 30L * 1024L * 1024L

    @Synchronized
    fun ensureInstalled(context: Context, dest: File): File {
        if (isReady(dest)) return dest

        dest.parentFile?.mkdirs()
        val tmp = File(dest.parentFile, "${dest.name}.tmp")
        try {
            context.assets.open(ASSET_PATH).use { input ->
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
            if (!isReady(tmp)) {
                throw IOException("embedded speaker model is incomplete: ${tmp.length()} bytes")
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
                "speaker model install failed: $ASSET_PATH -> ${dest.absolutePath}: ${t.message}",
                t,
            )
        }
    }

    fun isReady(file: File): Boolean =
        file.isFile && file.canRead() && file.length() >= MIN_BYTES
}
