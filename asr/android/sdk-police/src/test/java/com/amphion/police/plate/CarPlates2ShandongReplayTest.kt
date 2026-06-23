package com.amphion.police.plate

import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 山东 car_plates2 回放失败归因。 */
class CarPlates2ShandongReplayTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../../../evaluation/plate_number/car_plates2_zh_20260612_0331")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../../../evaluation/plate_number/car_plates2_zh_20260612_0331")
            .canonicalFile
    }

    private val casesTsv: File by lazy {
        File("../../../../evaluation/plate_number/staging_car_plates2_zh_20260612_0331/cases.tsv")
            .canonicalFile
    }

    private fun normalizer(): PlateNormalizer {
        val csv = File("src/main/assets/plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    @Test
    fun replay_shandong_analyze_remaining() {
        val norm = normalizer()
        val cases = casesTsv.readLines().drop(1).map { line ->
            val p = line.split("\t")
            Triple(p[0], p[2], p[3])
        }
        val evalRows = evalDir.resolve("plate_eval.tsv").readLines().drop(1).map { line ->
            line.split("\t")
        }

        var total = 0
        var deviceOk = 0
        var replayOk = 0
        val byPlate = linkedMapOf<String, MutableList<Triple<String, String, String>>>()
        val categories = linkedMapOf<String, Int>()

        for ((case, row) in cases.zip(evalRows)) {
            if (case.third != "shandong") continue
            val exp = row[1].ifEmpty { case.second }
            val asr = row[2]
            val deviceGot = row[4]
            val replayGot = norm.normalize(asr).primaryPlate ?: ""

            total++
            if (deviceGot == exp) deviceOk++
            if (replayGot == exp) replayOk++

            if (replayGot != exp) {
                val plateKey = exp.take(3)
                byPlate.getOrPut(plateKey) { mutableListOf() }
                    .add(Triple(exp, replayGot, asr))
                val cat = classifyFailure(exp, replayGot, asr)
                categories[cat] = (categories[cat] ?: 0) + 1
            }
        }

        var regress = 0
        for ((case, row) in cases.zip(evalRows)) {
            if (case.third == "shandong") continue
            val exp = row[1].ifEmpty { case.second }
            val deviceGot = row[4]
            val replayGot = norm.normalize(row[2]).primaryPlate ?: ""
            if (deviceGot == exp && replayGot != exp) regress++
        }

        val sb = StringBuilder()
        sb.appendLine("=== Shandong replay analysis ===")
        sb.appendLine("baseline_replay=218/300 (72.7%)")
        sb.appendLine("total=$total device=$deviceOk (${pct(deviceOk, total)}) replay=$replayOk (${pct(replayOk, total)})")
        sb.appendLine("delta_replay_vs_device=${replayOk - deviceOk}")
        sb.appendLine("delta_replay_vs_baseline=${replayOk - 218}")
        sb.appendLine("other_province_regressions=$regress")
        sb.appendLine("still_fail=${total - replayOk}")
        sb.appendLine()
        sb.appendLine("by_failure_category:")
        categories.entries.sortedByDescending { it.value }.forEach { (k, v) ->
            sb.appendLine("  $k: $v")
        }
        sb.appendLine()
        sb.appendLine("by_plate (still_fail count):")
        byPlate.entries.sortedByDescending { it.value.size }.forEach { (plate, fails) ->
            sb.appendLine("  $plate: ${fails.size}")
            fails.take(2).forEach { (exp, got, asr) ->
                sb.appendLine("    exp=$exp got=$got | $asr")
            }
        }

        val outFile = evalDir.resolve("metrics_shandong_replay_analysis.txt")
        outFile.writeText(sb.toString())
        println(sb.toString())
    }

    private fun classifyFailure(exp: String, got: String, asr: String): String {
        if (got.isEmpty()) {
            when {
                Regex("鲁[璧塞迪奕逸毅鲁豫记济基卢路如威儿尔279披丕皮炉外味爱奥额债建街宅贞Z G]").containsMatchIn(asr) ->
                    return "no_extract_province_letter_mishear"
                Regex("鲁R.*279|279.*406|鲁\\s*279").containsMatchIn(asr) ->
                    return "no_extract_digit_gap"
                Regex("鲁威|鲁F\\s*1937|次").containsMatchIn(asr) ->
                    return "no_extract_glued_or_truncated"
                Regex("三|四|五|六|七|八|九|零|幺|两").containsMatchIn(asr) &&
                    !Regex("\\d{4,}").containsMatchIn(asr) ->
                    return "no_extract_chinese_digit"
                else -> return "no_extract_other"
            }
        }
        if (got.take(2) != exp.take(2)) return "wrong_province"
        if (got.length >= 2 && exp.length >= 2 && got[1] != exp[1]) return "letter_swap"
        if (got != exp) return "digit_or_tail_error"
        return "other"
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else String.format("%.1f%%", 100.0 * n / d)
}
