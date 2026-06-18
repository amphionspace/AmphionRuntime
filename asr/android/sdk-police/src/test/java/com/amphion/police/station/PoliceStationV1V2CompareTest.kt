package com.amphion.police.station

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 派出所 V1 ↔ V2 离线对比工装（同一批真机 asr_raw，三轮回放）。
 *
 * V1 = [PoliceStationNormalizer]（整词短语贪心替换）。
 * V2 = [PoliceStationNormalizerV2]（字级候选格 ∩ gazetteer 校验器，最少近音替换且唯一）。
 *
 * 只对比「站名是否命中」（expected_station 是否出现在输出整句里）。结果写
 * evaluation/police_station/metrics_v1_v2_compare.txt。
 */
class PoliceStationV1V2CompareTest {

    private val rounds = listOf("round01", "round02", "round03")

    private fun evalDir(round: String): File {
        val fromModule = File("../../../../evaluation/police_station/$round")
        return if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../../../evaluation/police_station/$round")
            .canonicalFile
    }

    private fun v1(): PoliceStationNormalizer =
        PoliceStationNormalizer.create(
            PoliceStationHomophoneDict.loadFromReader(reader("police_station/station_homophones.csv")),
            PoliceStationGazetteer.loadFromReader(reader("police_station/station_gazetteer.txt")),
        )

    private fun v2(): PoliceStationNormalizerV2 {
        val names = reader("police_station/station_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct().sortedByDescending { it.length }
        return PoliceStationNormalizerV2.create(
            PoliceStationHomophoneDict.loadFromReader(reader("police_station/station_homophones.csv")),
            PoliceStationGazetteer.loadFromReader(reader("police_station/station_gazetteer.txt")),
            names,
            StationReadingMap.loadFromReader(reader("police_station/station_homophones.csv")),
        )
    }

    @Test
    fun compare_v1_v2_over_three_rounds() {
        val v1 = v1()
        val v2 = v2()

        val report = StringBuilder()
        var gTotal = 0
        var gV1 = 0
        var gV2 = 0
        var gV2OnlyWin = 0
        var gV2OnlyLose = 0
        val v2Lose = mutableListOf<String>()

        for (round in rounds) {
            val tsv = File(evalDir(round), "police_station_eval.tsv")
            if (!tsv.isFile) continue

            var total = 0
            var v1Hit = 0
            var v2Hit = 0
            var v2Win = 0
            var v2Lose0 = 0

            tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
                br.readLine()
                br.forEachLine { line ->
                    if (line.isBlank()) return@forEachLine
                    val p = line.split('\t')
                    if (p.size < 9) return@forEachLine
                    val ref = p[2].trim()
                    val exp = p[3].trim().ifEmpty { PoliceStationTextUtil.extractStation(ref) }
                    val asrRaw = p[4].trim()
                    if (exp.isEmpty()) return@forEachLine

                    total++
                    val h1 = exp in v1.normalize(asrRaw).text
                    val h2 = exp in v2.normalize(asrRaw).text
                    if (h1) v1Hit++
                    if (h2) v2Hit++
                    if (h2 && !h1) v2Win++
                    if (h1 && !h2) {
                        v2Lose0++
                        if (v2Lose.size < 20) v2Lose += "[$round] $exp | ${v2.normalize(asrRaw).text.take(50)}"
                    }
                }
            }
            report.appendLine(
                "%-8s total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)  V2独赢=%d V2独输=%d".format(
                    round, total, v1Hit, 100.0 * v1Hit / total, v2Hit, 100.0 * v2Hit / total, v2Win, v2Lose0,
                ),
            )
            gTotal += total; gV1 += v1Hit; gV2 += v2Hit; gV2OnlyWin += v2Win; gV2OnlyLose += v2Lose0
        }

        report.insert(
            0,
            "=== 派出所 V1 vs V2 (三轮合计) ===\n" +
                "total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)  V2独赢=%d V2独输=%d\n\n".format(
                    gTotal, gV1, 100.0 * gV1 / gTotal, gV2, 100.0 * gV2 / gTotal, gV2OnlyWin, gV2OnlyLose,
                ),
        )
        report.appendLine().appendLine("V2 独输样例（V1对 V2错）：")
        v2Lose.forEach { report.appendLine("  $it") }

        val out = File(evalDir("round03").parentFile, "metrics_v1_v2_compare.txt")
        out.writeText(report.toString(), StandardCharsets.UTF_8)
        println(report)

        assertTrue("无评测数据", gTotal > 0)
    }

    /**
     * 泛化基准：程序化生成站名的「单字近音误识」变体（且该变体整词**不在** V1 谐音表里），
     * 衡量「没人肉补这条」时 V1 vs V2 的纠正率。体现 V2「字级知识跨站名自由重组」的真实增益。
     */
    @Test
    fun generalization_unseen_single_char_mishearings() {
        val v1 = v1()
        val v2 = v2()

        // 站名 + V1 谐音表已知短语集合（用于排除「已被人肉收录」的变体，保证是「没见过」的）
        val names = reader("police_station/station_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }.distinct()
        val knownPhrases = reader("police_station/station_homophones.csv").readLines()
            .mapNotNull { l ->
                val s = l.trim()
                if (s.isEmpty() || s.startsWith("#")) null else s.split(",").firstOrNull()?.trim()
            }.filter { !it.isNullOrEmpty() }.toHashSet()
        // 逆向近音：真值字 -> 可能被听成的字（从 from->to 反推 to 的可替换来源）
        val heardOf = linkedMapOf<Char, MutableSet<Char>>()
        reader("police_station/station_homophones.csv").readLines().forEach { l ->
            val s = l.trim()
            if (s.isEmpty() || s.startsWith("#")) return@forEach
            val p = s.split(","); if (p.size < 2) return@forEach
            val from = p[0].trim(); val to = p[1].trim()
            if (from.length == to.length) {
                for (i in from.indices) if (from[i] != to[i]) {
                    heardOf.getOrPut(to[i]) { linkedSetOf() }.add(from[i])
                }
            }
        }

        var total = 0; var v1Hit = 0; var v2Hit = 0
        for (truth in names) {
            for (i in truth.indices) {
                val heards = heardOf[truth[i]] ?: continue
                for (h in heards) {
                    if (h == truth[i]) continue
                    val variant = truth.substring(0, i) + h + truth.substring(i + 1)
                    if (variant == truth) continue
                    // 排除「整词已被 V1 表收录」的变体——只考「没见过」的新组合
                    if (variant in knownPhrases) continue
                    val sentence = "请查一下${variant}最近一周的接警情况。"
                    total++
                    if (truth in v1.normalize(sentence).text) v1Hit++
                    if (truth in v2.normalize(sentence).text) v2Hit++
                }
            }
        }

        // 变长（漏字）基准：删站名中 1 个字（区/路/市等），模拟 ASR 漏字；二档编辑距离应能补回。
        var dTotal = 0; var dV1 = 0; var dV2 = 0
        for (truth in names) {
            val nameCore = truth.removeSuffix("派出所")
            if (nameCore.length < 4) continue
            for (i in nameCore.indices) {
                val variant = (nameCore.substring(0, i) + nameCore.substring(i + 1)) + "派出所"
                if (variant in knownPhrases || names.contains(variant)) continue
                val sentence = "请查一下${variant}最近一周的接警情况。"
                dTotal++
                if (truth in v1.normalize(sentence).text) dV1++
                if (truth in v2.normalize(sentence).text) dV2++
            }
        }

        val report = "=== 派出所「没见过的单字近音」泛化基准 ===\n" +
            "total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)\n".format(
                total, v1Hit, 100.0 * v1Hit / total, v2Hit, 100.0 * v2Hit / total,
            ) +
            "=== 变长(漏字)基准 ===\n" +
            "total=%d  V1=%d (%.1f%%)  V2=%d (%.1f%%)\n".format(
                dTotal, dV1, 100.0 * dV1 / dTotal, dV2, 100.0 * dV2 / dTotal,
            )
        File(evalDir("round03").parentFile, "metrics_v2_generalization.txt")
            .writeText(report, StandardCharsets.UTF_8)
        println(report)
        assertTrue("无生成样例", total > 0)
    }

    private fun reader(rel: String): BufferedReader {
        val roots = listOf("src/main/assets", "sample/src/main/assets")
        val cwd = File(System.getProperty("user.dir") ?: ".")
        for (base in listOfNotNull(cwd, cwd.parentFile)) {
            for (r in roots) {
                val f = File(base, "$r/$rel")
                if (f.isFile) return BufferedReader(FileReader(f, StandardCharsets.UTF_8))
            }
        }
        error("asset not found: $rel")
    }
}
