package com.amphion.asr.sample.plate

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 轨 B 真机评测落盘：每次 onFinal 追加一行 TSV，adb pull 后用 [run_plate_eval.py] 统计。
 *
 * 路径：/sdcard/Android/data/com.amphion.asr.sample/files/plate-eval/plate_eval.tsv
 */
class PlateEvalRecorder(context: Context) {

    private val dir: File = File(
        context.getExternalFilesDir(null),
        "plate-eval",
    )
    private val tsv: File = File(dir, "plate_eval.tsv")
    private val lock = Any()

    companion object {
        private const val TAG = "PlateEval"
        const val HEADER =
            "timestamp_ms\texpected_plate\tasr_raw\tnormalized\tplate_extracted\tplate_valid\n"

        fun pullHint(): String =
            "adb pull /sdcard/Android/data/com.amphion.asr.sample/files/plate-eval ./plate-eval"
    }

    init {
        dir.mkdirs()
        synchronized(lock) {
            if (!tsv.exists() || tsv.length() == 0L) {
                tsv.writeText(HEADER, Charsets.UTF_8)
            }
        }
    }

    fun append(
        asrRaw: String,
        result: PlateNormalizeResult,
        expectedPlate: String = "",
    ) {
        val plate = result.primaryPlate.orEmpty()
        val valid = result.spans.any { it.valid }
        val line = listOf(
            System.currentTimeMillis().toString(),
            expectedPlate,
            asrRaw,
            result.text,
            plate,
            if (valid) "Y" else "N",
        ).joinToString("\t") { escapeTsv(it) }

        synchronized(lock) {
            tsv.appendText(line + "\n", Charsets.UTF_8)
        }
        Log.i(
            TAG,
            "recorded plate_valid=$valid primary=$plate raw=${asrRaw.take(40)} norm=${result.text.take(40)}",
        )
    }

    fun filePath(): String = tsv.absolutePath

    fun sessionTag(): String =
        SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())

    /** 清空 TSV，仅保留表头（批量评测新会话前调用）。 */
    fun reset() {
        synchronized(lock) {
            tsv.writeText(HEADER, Charsets.UTF_8)
        }
    }

    private fun escapeTsv(s: String): String =
        s.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", "")
}
