package com.amphion.police.plate

import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 辽宁 car_plates2 回放失败归因。 */
class CarPlates2LiaoningReplayTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../evaluation/plate_number/car_plates2_zh_20260612_0331")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../evaluation/plate_number/car_plates2_zh_20260612_0331")
            .canonicalFile
    }

    private val casesTsv: File by lazy {
        File("../../evaluation/plate_number/staging_car_plates2_zh_20260612_0331/cases.tsv")
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
    fun replay_liaoning_analyze_remaining() {
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
            if (case.third != "liaoning") continue
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
            if (case.third == "liaoning") continue
            val exp = row[1].ifEmpty { case.second }
            val deviceGot = row[4]
            val replayGot = norm.normalize(row[2]).primaryPlate ?: ""
            if (deviceGot == exp && replayGot != exp) regress++
        }

        val sb = StringBuilder()
        sb.appendLine("=== Liaoning replay analysis ===")
        sb.appendLine("baseline_replay=138/225 (61.3%)")
        sb.appendLine("total=$total device=$deviceOk (${pct(deviceOk, total)}) replay=$replayOk (${pct(replayOk, total)})")
        sb.appendLine("delta_replay_vs_device=${replayOk - deviceOk}")
        sb.appendLine("delta_replay_vs_baseline=${replayOk - 138}")
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

        evalDir.resolve("metrics_liaoning_replay_analysis.txt").writeText(sb.toString())
        println(sb.toString())
    }

    private fun classifyFailure(exp: String, got: String, asr: String): String {
        if (got.isNotEmpty() && got.length >= 2 && exp.length >= 2 && got[1] != exp[1]) {
            return "letter_swap"
        }
        if (got.isEmpty()) {
            when {
                Regex("聊|辽冀|辽际|辽济|辽徽|辽威|辽宁|辽涝|聊恩|辽债|刘H").containsMatchIn(asr) ->
                    return "no_extract_liao_homophone"
                Regex("辽52841|辽57384|辽68147").containsMatchIn(asr) ->
                    return "no_extract_missing_letter"
                Regex("160\\s*538|292\\s*631").containsMatchIn(asr) ->
                    return "no_extract_digit_gap"
                else -> return "no_extract_other"
            }
        }
        return "digit_or_other"
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else String.format("%.1f%%", 100.0 * n / d)
}
