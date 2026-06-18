package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File

/** 用 round11 真机 TSV 回放规则，统计修复后命中率（本地路径）。 */
class Round11ReplayTest {

    private lateinit var normalizer: PlateNormalizer

    @Before
    fun setUp() {
        normalizer = PlateNormalizer.create(loadProductionDict())
    }

    private fun loadProductionDict(): PlateHomophoneDict {
        val f = TestAssets.resolve("plate/plate_homophones.csv")
        return PlateHomophoneDict.loadFromReader(BufferedReader(f.reader()))
    }

    @Test
    fun replay_round11_tsv() {
        val tsv = resolveRound11Tsv()
        if (!tsv.isFile) {
            println("[SKIP] round11 tsv not found: ${tsv.absolutePath}")
            return
        }
        var total = 0
        var match = 0
        var valid = 0
        tsv.readLines().drop(1).forEach { line ->
            val cols = line.split('\t')
            if (cols.size < 6) return@forEach
            val expected = cols[1].trim()
            val raw = cols[2].trim()
            if (expected.isEmpty() || raw.isEmpty()) return@forEach
            total++
            val r = normalizer.normalize(raw)
            if (r.spans.any { it.valid }) valid++
            if (r.primaryPlate == expected) match++
        }
        val rate = if (total > 0) match.toDouble() / total else 0.0
        println("[round11 replay] total=$total exact_match=$match (${"%.1f".format(rate * 100)}%) valid=$valid")
        if (match < total) {
            tsv.readLines().drop(1).forEach { line ->
                val cols = line.split('\t')
                if (cols.size < 6) return@forEach
                val expected = cols[1].trim()
                val raw = cols[2].trim()
                if (expected.isEmpty() || raw.isEmpty()) return@forEach
                val r = normalizer.normalize(raw)
                if (r.primaryPlate != expected) {
                    println("  remain exp=$expected got=${r.primaryPlate ?: "-"} | ${raw.take(72)}")
                }
            }
        }
        assertTrue("round11 replay should reach >=80%", rate >= 0.80)
    }

    private fun resolveRound11Tsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(5) {
            val base = dir ?: return@repeat
            val candidate = File(base, "plate-eval-round11/plate_eval.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("plate-eval-round11/plate_eval.tsv")
    }
}
