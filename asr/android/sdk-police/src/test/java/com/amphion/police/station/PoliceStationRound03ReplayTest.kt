package com.amphion.police.station

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 离线回放派出所 Round03（新声学）真机 asr_raw，验证 tier3 谐音修复。
 * 数据：asr/evaluation/police_station/round03/police_station_eval.tsv
 */
class PoliceStationRound03ReplayTest {

    private val evalDir: File by lazy {
        val fromModule = File("../../evaluation/police_station/round03")
        if (fromModule.isDirectory) fromModule.canonicalFile
        else File(System.getProperty("user.dir"))
            .resolve("../../evaluation/police_station/round03")
            .canonicalFile
    }

    private fun normalizer(): PoliceStationNormalizer {
        val csv = resolveAsset("police_station/station_homophones.csv")
        val gaz = resolveAsset("police_station/station_gazetteer.txt")
        return PoliceStationNormalizer.create(
            PoliceStationHomophoneDict.loadFromReader(
                BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
            ),
            PoliceStationGazetteer.loadFromReader(
                BufferedReader(FileReader(gaz, StandardCharsets.UTF_8)),
            ),
        )
    }

    @Test
    fun replay_round03_station_hit_at_least_98_percent() {
        val norm = normalizer()
        val tsv = File(evalDir, "police_station_eval.tsv")
        require(tsv.isFile) { "missing ${tsv.absolutePath}" }

        var total = 0
        var oldHit = 0
        var newHit = 0
        var decodeCollapse = 0
        val stillMiss = mutableListOf<String>()

        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            br.readLine() ?: error("empty tsv")
            br.forEachLine { line ->
                if (line.isBlank()) return@forEachLine
                val p = line.split('\t')
                require(p.size >= 10) { "bad line" }
                val ref = p[2].trim()
                val exp = p[3].trim().ifEmpty { PoliceStationTextUtil.extractStation(ref) }
                val asrRaw = p[4].trim()
                val oldNorm = p[5].trim()
                val oldHyp = oldNorm.ifEmpty { asrRaw }
                val wasHit = p[8].trim().uppercase() == "Y"

                total++
                if (wasHit) oldHit++

                val result = PoliceStationEnhance.apply(asrRaw, norm, normalizeEnabled = true)
                if (result.decodeCollapse) decodeCollapse++
                val newHyp = result.text
                val hit = exp.isNotEmpty() && exp in newHyp
                if (hit) newHit++ else if (exp.isNotEmpty()) {
                    stillMiss += "$exp | ${newHyp.take(60)}"
                }
            }
        }

        assertEquals(394, total)
        val rate = newHit.toDouble() / total
        val report = buildString {
            appendLine("Round03 replay: oldHit=$oldHit newHit=$newHit/$total (${"%.1f".format(rate * 100)}%)")
            appendLine("decodeCollapse=$decodeCollapse")
            appendLine("stillMiss=${stillMiss.size}")
            stillMiss.take(12).forEach { appendLine("  $it") }
        }
        File(evalDir, "metrics_replay.txt").writeText(report, StandardCharsets.UTF_8)
        println(report)

        // round02 真机 391/394 (99.2%)；tier3 回放 390/394 (99.0%)，差 1 条为解码崩溃/高风险故意不修
        assertTrue(
            "station hit $newHit/$total = ${"%.1f".format(rate * 100)}%",
            newHit >= 390,
        )
        assertTrue("should improve over round03 device $oldHit", newHit >= oldHit + 30)
    }

    private fun resolveAsset(rel: String): File {
        val roots = listOf("src/main/assets", "sample/src/main/assets")
        val cwd = File(System.getProperty("user.dir") ?: ".")
        for (base in listOfNotNull(cwd, cwd.parentFile)) {
            for (r in roots) {
                val f = File(base, "$r/$rel")
                if (f.isFile) return f
            }
        }
        error("asset not found: $rel")
    }
}
