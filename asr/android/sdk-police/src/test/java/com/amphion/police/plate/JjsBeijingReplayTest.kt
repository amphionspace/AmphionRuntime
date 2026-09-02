package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 离线回放京津冀 TTS 真机 asr_raw（统计 beijing 条，冀/津不参与 assert）。 */
class JjsBeijingReplayTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../evaluation/plate_number/jjs_car_plates_20260611")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../evaluation/plate_number/jjs_car_plates_20260611")
            .canonicalFile
    }

    private val casesTsv: File by lazy {
        File("../../evaluation/plate_number/staging_jjs_car_plates_20260611/cases.tsv")
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
    fun replay_jjs_beijing_only_no_regression() {
        val norm = normalizer()
        val cases = casesTsv.readLines().drop(1).map { line ->
            val p = line.split("\t")
            p[0] to p[2]
        }
        val evalRows = evalDir.resolve("plate_eval.tsv").readLines().drop(1).map { line ->
            line.split("\t")
        }
        require(cases.size == evalRows.size) { "cases/eval size mismatch" }

        var bjTotal = 0
        var bjMatch = 0
        var bjWas = 0
        var numericTotal = 0
        var numericMatch = 0
        var numericWas = 0
        var mixedTotal = 0
        var mixedMatch = 0
        var hebeiTjRegress = 0
        val regressed = mutableListOf<String>()
        val numericRegressed = mutableListOf<String>()

        for ((case, row) in cases.zip(evalRows)) {
            val uttId = case.first
            val exp = row[1].ifEmpty {
                Regex("(京|津|冀)[A-Z0-9]{6}").find(case.second)?.value ?: ""
            }
            val asr = row[2]
            val deviceGot = row[4]
            val replayGot = norm.normalize(asr).primaryPlate ?: ""

            if (!uttId.startsWith("beijing")) {
                if (deviceGot == exp && replayGot != exp) {
                    hebeiTjRegress++
                }
                continue
            }
            bjTotal++
            if (deviceGot == exp) bjWas++
            if (replayGot == exp) bjMatch++
            else regressed.add("exp=$exp got=$replayGot was=$deviceGot | $asr")
            val numericTail = exp.length >= 3 && exp.substring(2).all { it.isDigit() }
            if (numericTail) {
                numericTotal++
                if (deviceGot == exp) numericWas++
                if (replayGot == exp) numericMatch++
                else numericRegressed.add("$uttId\t$exp\t$replayGot\t$deviceGot\t$asr")
            } else {
                mixedTotal++
                if (replayGot == exp) mixedMatch++
            }
        }

        val report = buildString {
            appendLine("=== JJS Beijing Replay ===")
            appendLine("beijing_total=$bjTotal")
            appendLine("device_match=$bjWas (${pct(bjWas, bjTotal)})")
            appendLine("replay_match=$bjMatch (${pct(bjMatch, bjTotal)})")
            appendLine("delta_replay_vs_device=${bjMatch - bjWas}")
            appendLine("numeric_tail_total=$numericTotal")
            appendLine("numeric_tail_device=$numericWas (${pct(numericWas, numericTotal)})")
            appendLine("numeric_tail_replay=$numericMatch (${pct(numericMatch, numericTotal)})")
            appendLine("numeric_tail_delta=${numericMatch - numericWas}")
            appendLine("mixed_tail_total=$mixedTotal")
            appendLine("mixed_tail_replay=$mixedMatch (${pct(mixedMatch, mixedTotal)})")
            appendLine("hebei_tianjin_wrong_side_effect=$hebeiTjRegress")
            if (regressed.isNotEmpty()) {
                appendLine("--- still_fail (up to 25) ---")
                regressed.take(25).forEach { appendLine(it) }
            }
        }
        evalDir.resolve("metrics_beijing_replay.txt").writeText(report, StandardCharsets.UTF_8)
        evalDir.resolve("metrics_beijing_numeric.txt").writeText(
            "device_numeric_tail=$numericWas/$numericTotal (${pct(numericWas, numericTotal)})\n" +
                "replay_numeric_tail=$numericMatch/$numericTotal (${pct(numericMatch, numericTotal)})\n" +
                "delta_numeric_tail=${numericMatch - numericWas}\n",
            StandardCharsets.UTF_8,
        )
        evalDir.resolve("beijing_numeric_still_fail.tsv").writeText(
            "utt_id\texpected\treplay\tdevice\tasr_raw\n" +
                numericRegressed.joinToString("\n") + "\n",
            StandardCharsets.UTF_8,
        )
        println(report)
        assertEquals(0, hebeiTjRegress)
    }

    private fun pct(n: Int, total: Int): String =
        if (total == 0) "0.0%" else "%.1f%%".format(100.0 * n / total)
}
