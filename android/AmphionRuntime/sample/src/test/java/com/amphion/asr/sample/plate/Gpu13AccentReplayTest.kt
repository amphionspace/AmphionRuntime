package com.amphion.asr.sample.plate

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 离线回放 gpu13 口音对话 540 条真机 asr_raw。 */
class Gpu13AccentReplayTest {

    private val evalDir: File =
        File("../../../../evaluation/plate_number/gpu13_accent_dialogue").canonicalFile

    private fun normalizer(): PlateNormalizer {
        val csv = File("src/main/assets/plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    private fun levenshtein(a: String, b: String): Int {
        if (a == b) return 0
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length
        var prev = IntArray(b.length + 1) { it }
        for (i in a.indices) {
            val cur = IntArray(b.length + 1)
            cur[0] = i + 1
            for (j in b.indices) {
                cur[j + 1] = minOf(
                    cur[j] + 1,
                    prev[j + 1] + 1,
                    prev[j] + if (a[i] == b[j]) 0 else 1,
                )
            }
            prev = cur
        }
        return prev[b.length]
    }

    @Test
    fun replay_gpu13_accent_metrics() {
        val norm = normalizer()
        val tsv = File(evalDir, "plate_eval.tsv")
        val meta = File(evalDir, "metadata.gpu13.jsonl")
        val refs = meta.readLines().map { line ->
            Regex(""""text"\s*:\s*"([^"]*)"""")
                .find(line)!!.groupValues[1].replace("\\u0026", "&")
        }
        val rows = mutableListOf<Triple<String, String, String>>() // exp, asr, refText
        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            br.readLine()
            var i = 0
            br.forEachLine { line ->
                val p = line.split('\t')
                rows += Triple(
                    p[1].trim().ifEmpty { PlateTextUtil.extractPlate(refs[i]) },
                    p[2].trim(),
                    refs[i],
                )
                i++
            }
        }
        assertEquals(540, rows.size)

        var exact = 0
        var valid = 0
        var sent = 0
        var cerEdits = 0
        var cerLen = 0
        val stillFail = mutableListOf<String>()
        for ((exp, asr, refText) in rows) {
            val result = PlateEnhance.apply(asr, norm, normalizeEnabled = true)
            val got = result.primaryPlate.orEmpty()
            if (got == exp) exact++
            if (result.spans.any { it.valid }) valid++
            if (result.text == refText) sent++
            cerLen += refText.length
            cerEdits += levenshtein(refText, result.text)
            if (got != exp) {
                stillFail += listOf(exp, got, asr).joinToString("\t")
            }
        }

        val report = buildString {
            appendLine("gpu13 accent dialogue replay (n=540)")
            appendLine("完整车牌命中: $exact/540 = ${pct(exact, 540)}")
            appendLine("有效车牌提取:   $valid/540 = ${pct(valid, 540)}")
            appendLine("整句完全匹配:   $sent/540 = ${pct(sent, 540)}")
            appendLine("语料级整句CER:  ${cerEdits.toDouble() / cerLen}")
            appendLine("still_fail: ${stillFail.size}")
        }
        File(evalDir, "metrics_replay.txt").writeText(report, StandardCharsets.UTF_8)
        File(evalDir, "failures_replay.tsv").writeText(
            "expected\treplay_got\tasr_raw\n" + stillFail.joinToString("\n"),
            StandardCharsets.UTF_8,
        )
        println(report)
    }

    private fun pct(n: Int, total: Int): String =
        if (total == 0) "0.0%" else "%.1f%%".format(100.0 * n / total)
}
