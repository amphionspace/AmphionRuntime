package com.amphion.dingqiao.demo

import android.content.Context
import android.net.Uri
import android.os.Environment
import com.amphion.dingqiao.DINGQIAO_SPEAKER_MODEL_FILENAME
import java.io.File

/** Demo 声纹模型就绪检测与导入（避免 adb push 后 root 属主导致 App 不可读）。 */
object VoiceprintModelHelper {

    private const val MIN_BYTES = 30L * 1024 * 1024

    fun modelFile(workPath: String): File = File(workPath, DINGQIAO_SPEAKER_MODEL_FILENAME)

    fun isReady(file: File): Boolean =
        file.isFile && file.canRead() && file.length() >= MIN_BYTES

    /**
     * 若工作目录下模型不可读，尝试从「下载」目录复制一份（adb push 到 Download 时常用）。
     */
    fun tryImportFromDownloads(workPath: String): Boolean {
        val dest = modelFile(workPath)
        if (isReady(dest)) return true
        val candidates = listOf(
            File("/sdcard/Download/$DINGQIAO_SPEAKER_MODEL_FILENAME"),
            File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                DINGQIAO_SPEAKER_MODEL_FILENAME,
            ),
        )
        for (src in candidates) {
            if (!src.isFile || !src.canRead() || src.length() < MIN_BYTES) continue
            copyFile(src, dest)
            if (isReady(dest)) return true
        }
        return isReady(dest)
    }

    fun importFromUri(context: Context, workPath: String, uri: Uri): Boolean {
        val dest = modelFile(workPath)
        context.contentResolver.openInputStream(uri)?.use { input ->
            dest.outputStream().use { output -> input.copyTo(output) }
        } ?: return false
        return isReady(dest)
    }

    private fun copyFile(src: File, dest: File) {
        dest.parentFile?.mkdirs()
        src.inputStream().use { input ->
            dest.outputStream().use { output -> input.copyTo(output) }
        }
    }
}
