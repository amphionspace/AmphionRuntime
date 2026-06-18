package com.amphion.asr.sample.police_terms

import android.content.Context
import com.amphion.asr.sample.plate.BatchEvalManifest
import com.amphion.police.terms.PoliceTermsNormalizer
import com.amphion.police.terms.PoliceTermsTextUtil
import org.json.JSONObject
import java.io.File

/**
 * 警务术语批量评测：复用 [BatchEvalManifest] 数据目录，独立 progress 文件。
 */
object PoliceTermsBatchEvalManifest {

    const val PROGRESS_FILE = "batch_eval_terms_progress.txt"

    fun batchDir(context: Context): File = BatchEvalManifest.batchDir(context)

    fun progressFile(context: Context): File =
        File(batchDir(context), PROGRESS_FILE)

    fun resolveWav(batchRoot: File, audioPath: String): File =
        BatchEvalManifest.resolveWav(batchRoot, audioPath)

    fun loadCases(
        context: Context,
        filterOrigPrefix: String? = "police_terms_samples",
        normalizer: PoliceTermsNormalizer? = null,
    ): List<PoliceTermsBatchEvalCase> {
        val root = batchDir(context)
        val meta = BatchEvalManifest.metadataFile(context)
        if (!meta.isFile) return emptyList()

        val gaz = normalizer?.gazetteer()
        val cases = mutableListOf<PoliceTermsBatchEvalCase>()
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
            val expectedTerms = if (gaz != null) {
                PoliceTermsTextUtil.extractTerms(text, gaz)
            } else {
                emptyList()
            }
            cases.add(
                PoliceTermsBatchEvalCase(
                    uttId = uttId,
                    origUttId = orig,
                    refText = text,
                    expectedTerms = expectedTerms,
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
