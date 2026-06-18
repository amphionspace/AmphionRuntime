package com.amphion.asr.sample.police_terms

import android.content.Context
import android.util.Log
import com.amphion.police.terms.PoliceTermsNormalizeResult
import com.amphion.police.terms.PoliceTermsTextUtil
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 警务术语真机/批量评测落盘：每条追加一行 TSV，adb pull 后用 analyze_police_terms_eval.py 统计。
 *
 * 路径：/sdcard/Android/data/com.amphion.asr.sample/files/police-terms-eval/police_terms_eval.tsv
 */
class PoliceTermsEvalRecorder(context: Context) {

    private val dir: File = File(
        context.getExternalFilesDir(null),
        "police-terms-eval",
    )
    private val tsv: File = File(dir, "police_terms_eval.tsv")
    private val lock = Any()

    companion object {
        private const val TAG = "PoliceTermsEval"
        const val HEADER =
            "timestamp_ms\tutt_id\tref_text\texpected_terms\tasr_raw\tnormalized\t" +
                "term_hit\tterm_miss_detail\tsent_match\n"

        fun pullHint(): String =
            "adb pull /sdcard/Android/data/com.amphion.asr.sample/files/police-terms-eval " +
                "./evaluation/police_terms/roundN"
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
        expectedTerms: List<String>,
        asrRaw: String,
        result: PoliceTermsNormalizeResult,
    ) {
        val hyp = result.text
        val termHit = expectedTerms.isEmpty() ||
            PoliceTermsTextUtil.allTermsHit(expectedTerms, asrRaw) ||
            PoliceTermsTextUtil.allTermsHit(expectedTerms, hyp)
        val missDetail = expectedTerms
            .filter { !asrRaw.contains(it) && !hyp.contains(it) }
            .joinToString(",")
        val sentMatch = refText.isNotEmpty() && hyp == refText
        val line = listOf(
            System.currentTimeMillis().toString(),
            uttId,
            refText,
            expectedTerms.joinToString(","),
            asrRaw,
            hyp,
            if (termHit) "Y" else "N",
            missDetail,
            if (sentMatch) "Y" else "N",
        ).joinToString("\t") { escapeTsv(it) }

        synchronized(lock) {
            tsv.appendText(line + "\n", Charsets.UTF_8)
        }
        Log.i(
            TAG,
            "recorded utt=$uttId term_hit=$termHit sent_match=$sentMatch " +
                "raw=${asrRaw.take(40)} norm=${hyp.take(40)}",
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
