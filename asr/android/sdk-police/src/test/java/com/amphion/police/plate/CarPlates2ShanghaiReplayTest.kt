package com.amphion.police.plate

import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 上海 car_plates2 回放失败归因。 */
class CarPlates2ShanghaiReplayTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../evaluation/plate_number/car_plates2_shanghai_zh_20260612_1256")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../evaluation/plate_number/car_plates2_shanghai_zh_20260612_1256")
            .canonicalFile
    }

    private val casesTsv: File by lazy {
        File("../../evaluation/plate_number/staging_car_plates2_shanghai_zh_20260612_1256/cases.tsv")
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
    fun replay_shanghai_analyze_remaining() {
        val norm = normalizer()
        val cases = casesTsv.readLines().drop(1).map { line ->
            val p = line.split("\t")
            // utt_id, expected, region, tts_text
            listOf(p[0], p[2], p[3], if (p.size > 4) p[4] else "")
        }
        val evalRows = evalDir.resolve("plate_eval.tsv").readLines().drop(1).map { line ->
            line.split("\t")
        }

        var total = 0
        var deviceOk = 0
        var replayOk = 0
        val byPlate = linkedMapOf<String, MutableList<Triple<String, String, String>>>()
        val categories = linkedMapOf<String, Int>()

        val stillFailRows = mutableListOf<String>()

        for ((case, row) in cases.zip(evalRows)) {
            if (case[2] != "shanghai") continue
            val exp = row[1].ifEmpty { case[1] }
            val asr = row[2]
            val deviceGot = row[4]
            val replayGot = norm.normalize(asr).primaryPlate ?: ""
            val ttsText = case[3]

            total++
            if (deviceGot == exp) deviceOk++
            if (replayGot == exp) replayOk++

            if (replayGot != exp) {
                val plateKey = exp.take(3)
                byPlate.getOrPut(plateKey) { mutableListOf() }
                    .add(Triple(exp, replayGot, asr))
                val cat = classifyFailure(exp, replayGot, asr)
                categories[cat] = (categories[cat] ?: 0) + 1
                stillFailRows += listOf(
                    case[0],
                    exp,
                    deviceGot,
                    replayGot,
                    cat,
                    ttsText,
                    asr,
                ).joinToString("\t") { it.replace("\t", " ") }
            }
        }

        var regress = 0
        val nationalEval = File("../../evaluation/plate_number/car_plates2_zh_20260612_0331/plate_eval.tsv")
            .canonicalFile
        val nationalCases = File("../../evaluation/plate_number/staging_car_plates2_zh_20260612_0331/cases.tsv")
            .canonicalFile
        if (nationalEval.isFile && nationalCases.isFile) {
            val nc = nationalCases.readLines().drop(1).map { it.split("\t") }
            val ne = nationalEval.readLines().drop(1).map { it.split("\t") }
            for ((c, r) in nc.zip(ne)) {
                if (c[3] == "shanghai") continue
                val exp = r[1].ifEmpty { c[2] }
                if (r[4] == exp && (norm.normalize(r[2]).primaryPlate ?: "") != exp) regress++
            }
        }

        val sb = StringBuilder()
        sb.appendLine("=== Shanghai replay analysis ===")
        sb.appendLine("baseline_replay=108/210 (51.4%)")
        sb.appendLine("total=$total device=$deviceOk (${pct(deviceOk, total)}) replay=$replayOk (${pct(replayOk, total)})")
        sb.appendLine("delta_replay_vs_device=${replayOk - deviceOk}")
        sb.appendLine("delta_replay_vs_baseline=${replayOk - 108}")
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

        evalDir.resolve("metrics_shanghai_replay_analysis.txt").writeText(sb.toString())

        val manualHeader = "idx\tutt_id\texpected\tdevice_got\treplay_got\tcategory\ttts_text\tdevice_asr"
        val manualBody = stillFailRows.mapIndexed { i, row -> "${i + 1}\t$row" }.joinToString("\n")
        evalDir.resolve("shanghai_manual_retest_18.tsv").writeText("$manualHeader\n$manualBody\n")
        evalDir.resolve("shanghai_manual_retest_18.txt").writeText(
            buildString {
                appendLine("上海回放仍失败 ${stillFailRows.size} 条 — 人工复测清单")
                appendLine("请按 tts_text 朗读（TTS 原文），对比设备识别是否优于 TTS 批测时的 device_asr。")
                appendLine()
                stillFailRows.forEachIndexed { i, row ->
                    val p = row.split("\t")
                    appendLine("--- #${i + 1} ${p.getOrElse(0) { "" }} ---")
                    appendLine("期望车牌: ${p.getOrElse(1) { "" }}")
                    appendLine("失败类型: ${p.getOrElse(4) { "" }}")
                    appendLine("请朗读: ${p.getOrElse(5) { "" }}")
                    appendLine("TTS批测ASR: ${p.getOrElse(6) { "" }}")
                    appendLine("机端提取: ${p.getOrElse(2) { "" }} | 回放: ${p.getOrElse(3) { "" }}")
                    appendLine()
                }
            },
        )

        println(sb.toString())
    }

    private fun classifyFailure(exp: String, got: String, asr: String): String {
        if (got.isNotEmpty() && got.length >= 2 && exp.length >= 2 && got[1] != exp[1]) {
            return "letter_swap"
        }
        if (got.isEmpty()) {
            when {
                Regex("沪\\d{5}").containsMatchIn(asr) && exp.length >= 2 ->
                    return "no_extract_missing_letter"
                Regex("2849[UV优]|护矮了|户癌酪|护234|1937次").containsMatchIn(asr) ->
                    return "no_extract_risky"
                Regex("[户互护]|户籍|沪溢|沪济").containsMatchIn(asr) ->
                    return "no_extract_hu_homophone"
                else -> return "no_extract_other"
            }
        }
        if (got.endsWith("U") || got.endsWith("V")) return "digit_u_tail"
        return "digit_or_other"
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else String.format("%.1f%%", 100.0 * n / d)
}
