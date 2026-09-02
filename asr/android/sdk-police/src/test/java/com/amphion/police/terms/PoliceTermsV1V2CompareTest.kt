package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.nio.charset.StandardCharsets

/**
 * 警务术语 V1 ↔ V2 离线对比工装（三轮真机 asr_raw 回放 + 泛化基准）。
 *
 * V1 = [PoliceTermsNormalizer]（整词短语替换 + gazetteer 仅标注）。
 * V2 = [PoliceTermsNormalizerV2]（V1 全局谐音 + 保守字级模糊层：长术语 / 等长近音 / 唯一）。
 *
 * 命中口径同现有回放：expected_terms 每个词出现在输出或原文即算命中。
 * 结果写 asr/evaluation/police_terms/metrics_v1_v2_compare.txt。
 */
class PoliceTermsV1V2CompareTest {

    private val rounds = listOf("round01", "round02", "round03")

    private fun v1(): PoliceTermsNormalizer =
        PoliceTermsNormalizer.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
        )

    private fun v2(): PoliceTermsNormalizerV2 {
        val terms = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct().sortedByDescending { it.length }
        return PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
            terms,
            TermReadingMap.loadFromReader(reader("police_terms/term_homophones.csv")),
        )
    }

    private fun termHit(expected: List<String>, hyp: String, raw: String): Boolean =
        expected.isEmpty() || expected.all { it in hyp || it in raw }

    @Test
    fun compare_v1_v2_over_three_rounds() {
        val v1 = v1()
        val v2 = v2()
        val report = StringBuilder()
        var gTotal = 0; var gV1 = 0; var gV2 = 0; var gWin = 0; var gLose = 0
        val loseSamples = mutableListOf<String>()

        for (round in rounds) {
            val tsv = resolveTsv(round) ?: continue
            var total = 0; var v1Hit = 0; var v2Hit = 0; var win = 0; var lose = 0
            tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
                br.readLine()
                br.forEachLine { line ->
                    val c = line.split('\t')
                    if (c.size < 6) return@forEachLine
                    val expected = c[3].trim().split(',').map { it.trim() }.filter { it.isNotEmpty() }
                    val raw = c[4].trim()
                    if (expected.isEmpty()) return@forEachLine
                    total++
                    val h1 = termHit(expected, v1.normalize(raw).text, raw)
                    val h2 = termHit(expected, v2.normalize(raw).text, raw)
                    if (h1) v1Hit++
                    if (h2) v2Hit++
                    if (h2 && !h1) win++
                    if (h1 && !h2) {
                        lose++
                        if (loseSamples.size < 20) loseSamples += "[$round] ${expected.joinToString("/")} | ${v2.normalize(raw).text.take(40)}"
                    }
                }
            }
            report.appendLine(
                "%-8s total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)  V2独赢=%d V2独输=%d".format(
                    round, total, v1Hit, 100.0 * v1Hit / total, v2Hit, 100.0 * v2Hit / total, win, lose,
                ),
            )
            gTotal += total; gV1 += v1Hit; gV2 += v2Hit; gWin += win; gLose += lose
        }
        report.insert(
            0,
            "=== 警务术语 V1 vs V2 (三轮合计) ===\n" +
                "total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)  V2独赢=%d V2独输=%d\n\n".format(
                    gTotal, gV1, 100.0 * gV1 / gTotal, gV2, 100.0 * gV2 / gTotal, gWin, gLose,
                ),
        )
        report.appendLine().appendLine("V2 独输样例：")
        loseSamples.forEach { report.appendLine("  $it") }

        outDir()?.let { File(it, "metrics_v1_v2_compare.txt").writeText(report.toString(), StandardCharsets.UTF_8) }
        println(report)
        assertTrue("无评测数据", gTotal > 0)
    }

    @Test
    fun generalization_unseen_single_char_mishearings() {
        val v1 = v1()
        val v2 = v2()
        val terms = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }.distinct()
        val knownPhrases = reader("police_terms/term_homophones.csv").readLines()
            .mapNotNull { l ->
                val s = l.trim()
                if (s.isEmpty() || s.startsWith("#")) null else s.split(",").firstOrNull()?.trim()
            }.filter { !it.isNullOrEmpty() }.toHashSet()
        val heardOf = linkedMapOf<Char, MutableSet<Char>>()
        reader("police_terms/term_homophones.csv").readLines().forEach { l ->
            val s = l.trim()
            if (s.isEmpty() || s.startsWith("#")) return@forEach
            val p = s.split(","); if (p.size < 2) return@forEach
            val from = p[0].trim(); val to = p[1].trim()
            if (from.length == to.length) {
                for (i in from.indices) if (from[i] != to[i]) heardOf.getOrPut(to[i]) { linkedSetOf() }.add(from[i])
            }
        }

        var total = 0; var v1Hit = 0; var v2Hit = 0
        for (truth in terms) {
            if (truth.length < 4) continue        // 只考长术语（V2 模糊层只纠 ≥4 字）
            for (i in truth.indices) {
                val heards = heardOf[truth[i]] ?: continue
                for (h in heards) {
                    if (h == truth[i]) continue
                    val variant = truth.substring(0, i) + h + truth.substring(i + 1)
                    if (variant == truth || variant in knownPhrases) continue
                    val sentence = "现场${variant}请尽快处理。"
                    total++
                    if (truth in v1.normalize(sentence).text) v1Hit++
                    if (truth in v2.normalize(sentence).text) v2Hit++
                }
            }
        }
        val report = "=== 警务术语「没见过的单字近音」泛化基准（仅≥4字术语） ===\n" +
            "total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)\n".format(
                total, v1Hit, 100.0 * v1Hit / total, v2Hit, 100.0 * v2Hit / total,
            )
        outDir()?.let { File(it, "metrics_v2_generalization.txt").writeText(report, StandardCharsets.UTF_8) }
        println(report)
        assertTrue("无生成样例", total > 0)
    }

    @Test
    fun generalization_dropped_char_mishearings() {
        val v1 = v1()
        val v2 = v2()
        val terms = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }.distinct()
        val termSet = terms.toHashSet()

        var total = 0; var v1Hit = 0; var v2Hit = 0
        for (truth in terms) {
            if (truth.length < 5) continue        // 变长档只纠 ≥5 字术语
            for (i in truth.indices) {
                val variant = truth.removeRange(i, i + 1)   // 上游漏听一字
                if (variant.isEmpty() || variant == truth || variant in termSet) continue
                val sentence = "现场${variant}请尽快处理。"
                total++
                if (truth in v1.normalize(sentence).text) v1Hit++
                if (truth in v2.normalize(sentence).text) v2Hit++
            }
        }
        val report = "=== 警务术语「漏听一字（变长）」泛化基准（仅≥5字术语） ===\n" +
            "total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)\n".format(
                total, v1Hit, 100.0 * v1Hit / total, v2Hit, 100.0 * v2Hit / total,
            )
        outDir()?.let { File(it, "metrics_v2_generalization_dropped.txt").writeText(report, StandardCharsets.UTF_8) }
        println(report)
        assertTrue("无生成样例", total > 0)
        assertTrue("变长档应至少不弱于 V1", v2Hit >= v1Hit)
    }

    private fun resolveTsv(round: String): File? {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            val f = File(base, "asr/evaluation/police_terms/$round/police_terms_eval.tsv")
            if (f.isFile) return f
            dir = base.parentFile
        }
        return null
    }

    private fun outDir(): File? = resolveTsv("round03")?.parentFile?.parentFile

    private fun reader(rel: String): BufferedReader =
        BufferedReader(TestAssets.resolve(rel).reader())
}
