package com.amphion.asr.sample.police_station

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 派出所真机/批量评测落盘：每条追加一行 TSV，adb pull 后用 analyze_police_station_eval.py 统计。
 *
 * 路径：/sdcard/Android/data/com.amphion.asr.sample/files/police-station-eval/police_station_eval.tsv
 */
class PoliceStationEvalRecorder(context: Context) {

    private val dir: File = File(
        context.getExternalFilesDir(null),
        "police-station-eval",
    )
    private val tsv: File = File(dir, "police_station_eval.tsv")
    private val lock = Any()

    companion object {
        private const val TAG = "PoliceStationEval"
        const val HEADER =
            "timestamp_ms\tutt_id\tref_text\texpected_station\tasr_raw\tnormalized\t" +
                "station_extracted\tstation_valid\tstation_hit\tsent_match\tdecode_collapse\n"

        fun pullHint(): String =
            "adb pull /sdcard/Android/data/com.amphion.asr.sample/files/police-station-eval " +
                "./evaluation/police_station/roundN"
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
        uttId: String,
        refText: String,
        expectedStation: String,
        asrRaw: String,
        result: PoliceStationNormalizeResult,
    ) {
        val station = result.primaryStation.orEmpty()
        val valid = result.spans.any { it.valid }
        val stationHit = expectedStation.isNotEmpty() &&
            (asrRaw.contains(expectedStation) || result.text.contains(expectedStation))
        val sentMatch = refText.isNotEmpty() && result.text == refText
        val line = listOf(
            System.currentTimeMillis().toString(),
            uttId,
            refText,
            expectedStation,
            asrRaw,
            result.text,
            station,
            if (valid) "Y" else "N",
            if (stationHit) "Y" else "N",
            if (sentMatch) "Y" else "N",
            if (result.decodeCollapse) "Y" else "N",
        ).joinToString("\t") { escapeTsv(it) }

        synchronized(lock) {
            tsv.appendText(line + "\n", Charsets.UTF_8)
        }
        Log.i(
            TAG,
            "recorded utt=$uttId station_valid=$valid station_hit=$stationHit " +
                "raw=${asrRaw.take(40)} norm=${result.text.take(40)}",
        )
    }

    fun filePath(): String = tsv.absolutePath

    fun sessionTag(): String =
        SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())

    fun reset() {
        synchronized(lock) {
            tsv.writeText(HEADER, Charsets.UTF_8)
        }
    }

    private fun escapeTsv(s: String): String =
        s.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", "")
}
