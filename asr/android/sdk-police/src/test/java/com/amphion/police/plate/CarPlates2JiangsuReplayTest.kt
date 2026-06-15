package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/** 离线回放 car_plates2_zh 江苏真机 asr_raw。 */
class CarPlates2JiangsuReplayTest {

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
    fun replay_jiangsu_car_plates2_no_regression_on_other_provinces() {
        val norm = normalizer()
        val cases = casesTsv.readLines().drop(1).map { line ->
            val p = line.split("\t")
            p[0] to p[2]
        }
        val evalRows = evalDir.resolve("plate_eval.tsv").readLines().drop(1).map { line ->
            line.split("\t")
        }
        require(cases.size == evalRows.size) { "cases/eval size mismatch" }

        var jsTotal = 0
        var jsMatch = 0
        var jsWas = 0
        var otherRegress = 0
        val regressSamples = mutableListOf<String>()
        val stillFail = mutableListOf<String>()
        val newlyFixed = mutableListOf<String>()

        for ((case, row) in cases.zip(evalRows)) {
            val uttId = case.first
            val exp = row[1].ifEmpty { case.second }
            val asr = row[2]
            val deviceGot = row[4]
            val replayGot = norm.normalize(asr).primaryPlate ?: ""

            if (!uttId.startsWith("jiangsu")) {
                if (deviceGot == exp && replayGot != exp) {
                    otherRegress++
                    regressSamples.add(
                        "${case.first} exp=$exp was=$deviceGot replay=$replayGot | $asr",
                    )
                }
                continue
            }
            jsTotal++
            if (deviceGot == exp) jsWas++
            if (replayGot == exp) {
                jsMatch++
            } else {
                stillFail.add("exp=$exp got=$replayGot was=$deviceGot | $asr")
            }
            if (deviceGot != exp && replayGot == exp) {
                newlyFixed.add("exp=$exp was=$deviceGot | $asr")
            }
        }

        println("=== Jiangsu car_plates2 replay ===")
        println("jiangsu_total=$jsTotal")
        println("device_match=$jsWas (${pct(jsWas, jsTotal)})")
        println("replay_match=$jsMatch (${pct(jsMatch, jsTotal)})")
        println("delta_replay_vs_device=${jsMatch - jsWas}")
        println("other_province_regressions=$otherRegress")
        regressSamples.forEach { println("  REGRESS $it") }
        println("still_fail=${stillFail.size}")
        stillFail.take(15).forEach { println("  STILL $it") }
        println("newly_fixed=${newlyFixed.size}")
        newlyFixed.take(15).forEach { println("  FIX  $it") }

        assertTrue("replay should beat device baseline", jsMatch >= jsWas)
        assertEquals("no regression on other provinces", 0, otherRegress)
        assertTrue(
            "jiangsu replay should reach at least 90%",
            jsMatch >= (jsTotal * 0.90).toInt(),
        )
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else "${100.0 * n / d}%"
}
