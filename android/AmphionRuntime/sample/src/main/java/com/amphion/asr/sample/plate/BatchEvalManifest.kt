package com.amphion.asr.sample.plate

import android.content.Context
import com.amphion.police.plate.PlateTextUtil
import org.json.JSONObject
import java.io.File

/** 批量评测数据目录（adb push）：files/batch-eval/metadata.jsonl + wavs/zh/ 下各 wav */
object BatchEvalManifest {

    const val DIR_NAME = "batch-eval"
    const val METADATA_FILE = "metadata.jsonl"
    const val PROGRESS_FILE = "batch_eval_progress.txt"

    fun batchDir(context: Context): File =
        File(context.getExternalFilesDir(null), DIR_NAME)

    fun metadataFile(context: Context): File =
        File(batchDir(context), METADATA_FILE)

    fun progressFile(context: Context): File =
        File(batchDir(context), PROGRESS_FILE)

    fun resolveWav(batchRoot: File, audioPath: String): File {
        val normalized = audioPath.replace('\\', '/').trim()
        val rel = when {
            normalized.contains("/wavs/") ->
                normalized.substringAfter("/wavs/")
            normalized.startsWith("wavs/") ->
                normalized.removePrefix("wavs/")
            else -> normalized.substringAfterLast('/')
        }
        return File(batchRoot, "wavs/$rel")
    }

    fun loadCases(
        context: Context,
        filterOrigPrefix: String? = null,
    ): List<BatchEvalCase> {
        val root = batchDir(context)
        val meta = metadataFile(context)
        if (!meta.isFile) return emptyList()

        val cases = mutableListOf<BatchEvalCase>()
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
                BatchEvalCase(
                    uttId = uttId,
                    origUttId = orig,
                    refText = text,
                    expectedPlate = PlateTextUtil.extractPlate(text),
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
