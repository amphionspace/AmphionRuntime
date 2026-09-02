package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 离线回放 car_plates2_zh 全量真机 asr_raw（不含上海）。 */
class CarPlates2FullReplayTest {

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
    fun replay_car_plates2_all_provinces_excl_shanghai() {
        val norm = normalizer()
        val cases = casesTsv.readLines().drop(1).map { line ->
            val p = line.split("\t")
            Triple(p[0], p[2], p[3])
        }
        val evalRows = evalDir.resolve("plate_eval.tsv").readLines().drop(1).map { line ->
            line.split("\t")
        }
        require(cases.size == evalRows.size) { "cases/eval size mismatch: ${cases.size} vs ${evalRows.size}" }

        var total = 0
        var deviceMatch = 0
        var replayMatch = 0
        var jjsRegress = 0
        val regressSamples = mutableListOf<String>()
        val byRegion = linkedMapOf<String, IntArray>()

        for ((case, row) in cases.zip(evalRows)) {
            val (uttId, expFromCase, region) = case
            if (region == "shanghai") continue

            val exp = row[1].ifEmpty { expFromCase }
            val asr = row[2]
            val deviceGot = row[4]
            val replayGot = norm.normalize(asr).primaryPlate ?: ""

            total++
            val stats = byRegion.getOrPut(region) { intArrayOf(0, 0, 0) }
            stats[0]++
            if (deviceGot == exp) {
                deviceMatch++
                stats[1]++
            }
            if (replayGot == exp) {
                replayMatch++
                stats[2]++
            }
            if (deviceGot == exp && replayGot != exp) {
                jjsRegress++
                regressSamples.add("$uttId exp=$exp was=$deviceGot replay=$replayGot | $asr")
            }
        }

        val sb = StringBuilder()
        sb.appendLine("car_plates2_zh replay (excl. shanghai)")
        sb.appendLine("total=$total")
        sb.appendLine("device_exact=$deviceMatch (${pct(deviceMatch, total)})")
        sb.appendLine("replay_exact=$replayMatch (${pct(replayMatch, total)})")
        sb.appendLine("delta_replay_vs_device=${replayMatch - deviceMatch}")
        sb.appendLine("jjs_regressions=$jjsRegress")
        sb.appendLine()
        sb.appendLine("by_province:")
        for ((region, s) in byRegion) {
            sb.appendLine(
                "  $region: device=${s[1]}/${s[0]} (${pct(s[1], s[0])}) " +
                    "replay=${s[2]}/${s[0]} (${pct(s[2], s[0])}) delta=${s[2] - s[1]}",
            )
        }
        regressSamples.take(20).forEach { sb.appendLine("  REGRESS $it") }

        val metricsFile = evalDir.resolve("metrics_replay.txt")
        metricsFile.writeText(sb.toString())
        println(sb.toString())

        assertTrue("replay should beat or match device baseline", replayMatch >= deviceMatch)
        assertEquals("no regression on previously-correct cases", 0, jjsRegress)
        assertTrue(
            "overall replay should reach at least 65%",
            replayMatch >= (total * 0.65).toInt(),
        )
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else String.format("%.1f%%", 100.0 * n / d)
}
