package com.amphion.asr.sample.eval.export

import android.content.Context
import android.util.Log
import com.amphion.asr.sample.eval.data.RecordingStore
import com.amphion.asr.sample.eval.model.RecordingMeta
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * 把符合 [filter] 的 attempts 打包成 zip，写到
 * `<externalFilesDir>/asr-eval-export/eval_<tester>_<timestamp>.zip`。
 *
 * 调用方拿到返回的 zipFile 后，用 `Intent.ACTION_SEND` + `FileProvider` 让用户选 IM /
 * 邮件 / 云盘分享出去；服务端的工程师手动接收后 unzip 到目标目录即可。
 *
 * zip 内部目录结构保持与服务端一致：
 * ```
 * <tester_id>/<sentence_id>/<recording_id>/{audio.wav, meta.json, hypothesis.txt}
 * ```
 * 这样工程师把 zip 解开后可以直接被 asr/tools/eval_wer.py 消费。
 *
 * 失败处理：单条 attempt 读失败仅 log 跳过；整体打包失败抛 IOException。
 */
class ZipExporter : RecordingExporter {

    override fun export(
        ctx: Context,
        store: RecordingStore,
        filter: RecordingExporter.ExportFilter,
    ): RecordingExporter.ExportResult {
        val items = store.scanAll { meta ->
            (filter.testerId == null || meta.testerId == filter.testerId) &&
                (filter.sentenceIdPrefix == null ||
                    meta.sentenceId.startsWith(filter.sentenceIdPrefix)) &&
                (!filter.onlyNotUploaded || !meta.upload.isUploaded)
        }
        if (items.isEmpty()) {
            return RecordingExporter.ExportResult(0, null, 0L)
        }

        val base = ctx.getExternalFilesDir(null) ?: ctx.filesDir
        val outDir = File(base, EXPORT_DIR).apply { if (!isDirectory) mkdirs() }
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val testerTag = filter.testerId ?: "all"
        val zipFile = File(outDir, "eval_${testerTag}_${ts}.zip")

        var totalBytes = 0L
        try {
            ZipOutputStream(BufferedOutputStream(FileOutputStream(zipFile))).use { zos ->
                for (item in items) {
                    totalBytes += zipOneAttempt(zos, item)
                }
            }
        } catch (t: IOException) {
            Log.w(TAG, "zip pack failed: ${t.message}")
            try { zipFile.delete() } catch (_: Throwable) {}
            throw t
        }
        return RecordingExporter.ExportResult(items.size, zipFile, totalBytes)
    }

    private fun zipOneAttempt(zos: ZipOutputStream, item: RecordingStore.ScanItem): Long {
        var bytes = 0L
        val meta: RecordingMeta = item.meta
        val prefix = "${meta.testerId}/${meta.sentenceId}/${meta.recordingId}"

        if (item.metaFile.isFile) {
            bytes += writeEntry(zos, "$prefix/${RecordingStore.META_FILE}", item.metaFile)
        }
        if (item.audio.isFile) {
            bytes += writeEntry(zos, "$prefix/${RecordingStore.AUDIO_FILE}", item.audio)
        }
        if (item.hypothesis.isFile) {
            bytes += writeEntry(zos, "$prefix/${RecordingStore.HYPOTHESIS_FILE}", item.hypothesis)
        }
        return bytes
    }

    private fun writeEntry(zos: ZipOutputStream, name: String, src: File): Long {
        zos.putNextEntry(ZipEntry(name))
        var total = 0L
        FileInputStream(src).use { fis ->
            val buf = ByteArray(8192)
            while (true) {
                val n = fis.read(buf)
                if (n <= 0) break
                zos.write(buf, 0, n)
                total += n
            }
        }
        zos.closeEntry()
        return total
    }

    companion object {
        private const val TAG = "ZipExporter"
        const val EXPORT_DIR = "asr-eval-export"
    }
}
