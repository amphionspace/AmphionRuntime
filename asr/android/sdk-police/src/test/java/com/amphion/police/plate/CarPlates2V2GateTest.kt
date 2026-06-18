package com.amphion.police.plate

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * V2 全国语料回归门禁（P3）。
 *
 * 语料：`test_data/.../car_plates_II_plate_sentences.tsv`（模板合成，19 省，约 3750 句，
 * 句中已内嵌正确的阿拉伯车牌）。本门禁验证 [PlateNormalizerV2] 在**全国普通牌**上「不破坏
 * 已正确的车牌」（保真），并按省统计覆盖率，作为 V2 启用前的回归基线。
 *
 * 注：该语料均为 7 位普通牌；新能源 7/8 位歧义由 [PlateNormalizerV2Test] 单测覆盖。
 * 与真机 asr_raw 的回放门禁（[CarPlates2FullReplayTest]，跑老方案）相互独立、互补。
 */
class CarPlates2V2GateTest {

    private val corpus: File by lazy { locateCorpus() }

    private fun normalizer(): PlateNormalizerV2 {
        val kb = loadKnowledgeBase()
        return PlateNormalizerV2.create(kb, loadReadingMap(kb))
    }

    @Test
    fun v2_preserves_correct_national_plates() {
        val norm = normalizer()
        val rows = corpus.readLines().drop(1)
            .map { it.split("\t") }
            .filter { it.size >= 7 }

        require(rows.isNotEmpty()) { "empty corpus: ${corpus.path}" }

        var total = 0
        var preserved = 0
        val byProvince = linkedMapOf<String, IntArray>() // [total, preserved]
        val failures = mutableListOf<String>()

        for (cols in rows) {
            val plate = cols[2]
            val prefix = cols[3]
            val text = cols[6]
            val province = prefix.take(1)

            total++
            val stats = byProvince.getOrPut(province) { intArrayOf(0, 0) }
            stats[0]++

            val out = norm.normalize(text).text
            // 输入已含正确车牌，V2 必须保真（输出仍包含原车牌串）。
            if (out.contains(plate)) {
                preserved++
                stats[1]++
            } else if (failures.size < 30) {
                failures.add("$prefix exp=$plate | in=$text | out=$out")
            }
        }

        val sb = StringBuilder()
        sb.appendLine("car_plates_II V2 gate (national normal plates)")
        sb.appendLine("total=$total preserved=$preserved (${pct(preserved, total)})")
        sb.appendLine("by_province:")
        for ((p, s) in byProvince.toSortedMap()) {
            sb.appendLine("  $p: ${s[1]}/${s[0]} (${pct(s[1], s[0])})")
        }
        failures.forEach { sb.appendLine("  CORRUPT $it") }
        println(sb.toString())

        assertTrue(
            "V2 corrupted ${total - preserved} already-correct plates:\n" +
                failures.joinToString("\n"),
            preserved == total,
        )
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else String.format("%.2f%%", 100.0 * n / d)

    private fun locateCorpus(): File {
        val rel = "test_data/generation_by_template/generated/" +
            "car_plates_II/car_plates_II_plate_sentences.tsv"
        var dir: File? = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(12) {
            val base = dir ?: return@repeat
            val f = File(base, rel)
            if (f.isFile) return f.canonicalFile
            dir = base.parentFile
        }
        error("corpus not found (walked up from user.dir): $rel")
    }
}
