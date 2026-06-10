package com.amphion.asr.sample.police_station

import android.content.Context
import com.amphion.asr.sample.plate.BatchEvalManifest
import org.json.JSONObject
import java.io.File

/**
 * 派出所批量评测：复用 [BatchEvalManifest] 数据目录，独立 progress 文件。
 */
object PoliceStationBatchEvalManifest {

    const val PROGRESS_FILE = "batch_eval_station_progress.txt"

    fun batchDir(context: Context): File = BatchEvalManifest.batchDir(context)

    fun progressFile(context: Context): File =
        File(batchDir(context), PROGRESS_FILE)

    fun resolveWav(batchRoot: File, audioPath: String): File =
        BatchEvalManifest.resolveWav(batchRoot, audioPath)

    fun loadCases(
        context: Context,
        filterOrigPrefix: String? = "police_station_v2",
    ): List<PoliceStationBatchEvalCase> {
        val root = batchDir(context)
        val meta = BatchEvalManifest.metadataFile(context)
        if (!meta.isFile) return emptyList()

        val cases = mutableListOf<PoliceStationBatchEvalCase>()
        meta.forEachLine { line ->
            val trimmed = line.trim()
            if (trimmed.isEmpty()) return@forEachLine
            val obj = JSONObject(trimmed)
            val orig = obj.optString("orig_utt_id", "")
            if (!filterOrigPrefix.isNullOrEmpty() && !orig.startsWith(filterOrigPrefix)) {
                return@forEachLine
            }
            val uttId = obj.optString("utt_id", "")
            val text = obj.optString("text", "")
            val audioPath = obj.optString("audio_path", "")
            if (uttId.isEmpty() || audioPath.isEmpty()) return@forEachLine
            val wav = resolveWav(root, audioPath)
            if (!wav.isFile) return@forEachLine
            cases.add(
                PoliceStationBatchEvalCase(
                    uttId = uttId,
                    origUttId = orig,
                    refText = text,
                    expectedStation = PoliceStationTextUtil.extractStation(text),
                    wavFile = wav,
                ),
            )
        }
        return cases
    }

    fun loadDoneIds(context: Context): MutableSet<String> {
        val f = progressFile(context)
        if (!f.isFile) return mutableSetOf()
        return f.readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .toMutableSet()
    }

    fun appendDoneId(context: Context, uttId: String) {
        val f = progressFile(context)
        f.parentFile?.mkdirs()
        f.appendText("$uttId\n", Charsets.UTF_8)
    }

    fun clearProgress(context: Context) {
        progressFile(context).delete()
    }
}
