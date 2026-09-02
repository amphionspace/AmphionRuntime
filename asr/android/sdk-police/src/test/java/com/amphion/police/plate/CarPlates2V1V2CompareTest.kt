package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 真机 ASR 误识语料上的 V1↔V2 纠错召回对比门禁（P4 量化）。
 *
 * 与 [CarPlates2V2GateTest]（合成字面牌，测「不破坏」）互补：本测试喂的是**真机 asr_raw**
 * （含真实听岔，如「嘿A 52841」应为「黑A52841」），对每条同时跑老方案 [PlateNormalizer](V1)
 * 与新方案 [PlateNormalizerV2](V2)，对照标注车牌，量化：
 * - v1/v2 精确命中率
 * - recover：V2 命中且 V1 未命中（V2 净挽回）
 * - regress：V1 命中而 V2 未命中（V2 净回退，门禁重点盯防）
 *
 * 语料：`asr/evaluation/plate_number/{car_plates2_zh_*, car_plates2_shanghai_zh_*}`
 * （8 省国测 + 上海），共约 1950 条真机识别结果。
 */
class CarPlates2V1V2CompareTest {

    private data class Row(
        val uttId: String,
        val exp: String,
        val region: String,
        val asr: String,
        val text: String,
    )

    private fun loadCorpus(evalName: String, stagingName: String): List<Row> {
        val base = locateEvalBase()
        val cases = File(base, "$stagingName/cases.tsv").readLines().drop(1).map { it.split("\t") }
        val evalRows = File(base, "$evalName/plate_eval.tsv").readLines().drop(1).map { it.split("\t") }
        require(cases.size == evalRows.size) {
            "cases/eval size mismatch for $evalName: ${cases.size} vs ${evalRows.size}"
        }
        return cases.zip(evalRows).map { (c, e) ->
            Row(
                uttId = c[0],
                exp = e[1].ifEmpty { c[2] },
                region = c[3],
                asr = e[2],
                text = c.getOrElse(4) { "" },
            )
        }
    }

    private fun v1(): PlateNormalizer {
        val csv = TestAssets.resolve("plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(FileReader(csv, StandardCharsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    private fun v2(): PlateNormalizerV2 {
        val kb = loadKnowledgeBase()
        return PlateNormalizerV2.create(kb, loadReadingMap(kb))
    }

    @Test
    fun v2_vs_v1_recall_on_real_asr() {
        val rows = loadCorpus(
            "car_plates2_zh_20260612_0331",
            "staging_car_plates2_zh_20260612_0331",
        ) + loadCorpus(
            "car_plates2_shanghai_zh_20260612_1256",
            "staging_car_plates2_shanghai_zh_20260612_1256",
        )
        require(rows.isNotEmpty()) { "empty real-asr corpus" }

        val v1 = v1()
        val v2 = v2()

        var total = 0
        var v1Exact = 0
        var v2Exact = 0
        // 合并模式（MERGE）投影：V1 找到车牌则用 V1（保其全部命中），否则用 V2 兜底补漏。
        // 这是「灰度首选默认」的预期线上表现，按句级近似（V1.primaryPlate 非空即视为 V1 接管）。
        var mergeExact = 0
        val recovers = mutableListOf<String>()
        val regresses = mutableListOf<String>()
        // V2 未命中的 case（真人复测目标）：uttId, region, exp, v1_got, v2_got, asr_raw, clean_text
        val v2Misses = mutableListOf<Array<String>>()
        // region -> [total, v1, v2, recover, regress]
        val byRegion = linkedMapOf<String, IntArray>()
        // "region\tplate" -> [n, v1_ok, v2_ok]：导出真机复测目标分桶（见 writePlateBuckets）。
        val plateStats = linkedMapOf<String, IntArray>()

        for (r in rows) {
            val g1 = v1.normalize(r.asr).primaryPlate ?: ""
            val g2 = v2.normalize(r.asr).primaryPlate ?: ""
            val ok1 = g1 == r.exp
            val ok2 = g2 == r.exp
            val gMerge = g1.ifEmpty { g2 }
            if (gMerge == r.exp) mergeExact++

            total++
            val s = byRegion.getOrPut(r.region) { IntArray(5) }
            s[0]++
            if (ok1) { v1Exact++; s[1]++ }
            if (ok2) { v2Exact++; s[2]++ }
            if (r.exp.isNotEmpty()) {
                val pb = plateStats.getOrPut("${r.region}\t${r.exp}") { IntArray(3) }
                pb[0]++
                if (ok1) pb[1]++
                if (ok2) pb[2]++
            }
            if (ok2 && !ok1) {
                recovers.add("${r.region} exp=${r.exp} v1=$g1 | ${r.asr}")
                s[3]++
            }
            if (ok1 && !ok2) {
                regresses.add("${r.region} exp=${r.exp} v2=$g2 | ${r.asr}")
                s[4]++
            }
            if (!ok2) {
                v2Misses.add(
                    arrayOf(r.uttId, r.region, r.exp, g1, g2, r.asr, r.text),
                )
            }
        }

        val sb = StringBuilder()
        sb.appendLine("car_plates2 real-asr V1 vs V2 (national + shanghai)")
        sb.appendLine("total=$total")
        sb.appendLine("v1_exact=$v1Exact (${pct(v1Exact, total)})")
        sb.appendLine("v2_exact=$v2Exact (${pct(v2Exact, total)})")
        sb.appendLine("delta_v2_minus_v1=${v2Exact - v1Exact}")
        sb.appendLine("merge_exact(V1 primary + V2 fallback)=$mergeExact (${pct(mergeExact, total)})  delta_merge_minus_v1=${mergeExact - v1Exact}")
        sb.appendLine("recover(v2✓ v1✗)=${recovers.size}  regress(v1✓ v2✗)=${regresses.size}")
        sb.appendLine()
        sb.appendLine("by_region: region total v1 v2 recover regress")
        for ((reg, s) in byRegion.toSortedMap()) {
            sb.appendLine(
                "  $reg: ${s[0]} | v1=${s[1]}(${pct(s[1], s[0])}) v2=${s[2]}(${pct(s[2], s[0])}) " +
                    "rec=${s[3]} reg=${s[4]}",
            )
        }
        sb.appendLine()
        sb.appendLine("--- sample regress (V2 lost vs V1) ---")
        regresses.take(60).forEach { sb.appendLine("  REGRESS $it") }
        sb.appendLine("--- sample recover (V2 gained vs V1) ---")
        recovers.take(40).forEach { sb.appendLine("  RECOVER $it") }
        println(sb.toString())

        writeMetrics(sb.toString())
        writePlateBuckets(plateStats)
        writeV2RetestManifest(v2Misses)

        // 棘轮门禁（ratchet）：基线（2026-06 真机国测+上海 1950 条）
        //   P4 初始：       V2=1079(55.3%)，regress=708
        //   P5-1 扩读音表：  V2=1461(74.9%)，regress=334
        //   P5-2 折叠+锚词： V2=1520(77.9%)，recover=42，regress=278（吉/沪 已接近或反超 V1）
        //   P5-3 结构性补全：V2=1655(84.9%)，recover=47，regress=148
        //     （省份读成字母 U→豫/卢路如→鲁/折遮→浙；机关生僻近音 迪→D 尔→R 等；
        //      数字补位 机关位 1→E/2→R；suppress 消解 优→V/扣→K 平局选错。沪/鲁/豫 已接近或反超 V1）
        // V1=1756(90.1%) 仍领先；剩余缺口多为 V1 逐句硬编码过拟合（嘿嘿→黑C/黑K、辽冀→辽E/辽G、
        // 序号位 U↔1）或不可凭文本恢复项（漏字/同源异标），非纯近音、非泛化可解。
        //
        // 门禁语义：锁住当前 V2 下限、禁止继续回退；目标逐步追平 V1（V2_FLOOR→V1_TARGET）。
        // 每当 V2 鲁棒性提升，请同步上调 V2_FLOOR / 下调 REGRESS_CEIL。
        val v2Floor = 1640           // 当前实测 1655，留少量裕量
        val regressCeil = 160        // 当前实测 148
        val v1Target = v1Exact       // 终极目标：v2Exact 追平 v1Exact
        assertTrue("corpus loaded", total > 0)
        assertTrue(
            "V2 exact regressed below ratchet floor: v2=$v2Exact < $v2Floor (target=$v1Target)",
            v2Exact >= v2Floor,
        )
        assertTrue(
            "V2 regressions exceeded ceiling: regress=${regresses.size} > $regressCeil",
            regresses.size <= regressCeil,
        )
    }

    private fun writeMetrics(text: String) {
        runCatching {
            val out = File(locateEvalBase(), "car_plates2_zh_20260612_0331/metrics_v1_v2.txt")
            out.writeText(text)
        }
    }

    /**
     * 导出「真机复测目标分桶」到 `realmic/plate_buckets.tsv`，供 build_realmic_manifest.py 选牌：
     * - regress：V2 在该牌上不如 V1（v2_ok < v1_ok）→ 真机重测的**重点**（验证是否 TTS 噪声所致）
     * - recover：V2 优于 V1 → 验证 V2 增益在真人音频上是否成立
     * - ok：两者持平 → 抽样作**对照**，确认 V2 不在好牌上引入新回退
     */
    private fun writePlateBuckets(plateStats: Map<String, IntArray>) {
        runCatching {
            val out = File(locateEvalBase(), "realmic/plate_buckets.tsv")
            out.parentFile?.mkdirs()
            val sb = StringBuilder("region\tplate\tbucket\tn\tv1_ok\tv2_ok\n")
            for ((key, s) in plateStats.entries.sortedBy { it.key }) {
                val (region, plate) = key.split("\t")
                val bucket = when {
                    s[2] < s[1] -> "regress"
                    s[2] > s[1] -> "recover"
                    else -> "ok"
                }
                sb.appendLine("$region\t$plate\t$bucket\t${s[0]}\t${s[1]}\t${s[2]}")
            }
            out.writeText(sb.toString())
        }
    }

    // 导出「V2 真人复测清单」到 car_plates2_zh_*/v2_retest_manifest.tsv：
    // 列出当前交付版 V2 在真机 ASR 语料上仍未命中的全部 case，供真人清晰念读复测。
    // 列：region, expected_plate, prompt_text(干净原句/朗读用), v1_got, v2_got, asr_raw(真机听岔), utt_id
    private fun writeV2RetestManifest(misses: List<Array<String>>) {
        runCatching {
            val sorted = misses.sortedWith(compareBy({ it[1] }, { it[2] }, { it[0] }))
            val sb = StringBuilder(
                "region\texpected_plate\tprompt_text\tv1_got\tv2_got\tasr_raw\tutt_id\n",
            )
            for (m in sorted) {
                sb.appendLine("${m[1]}\t${m[2]}\t${m[6]}\t${m[3]}\t${m[4]}\t${m[5]}\t${m[0]}")
            }
            val out = File(
                locateEvalBase(),
                "car_plates2_zh_20260612_0331/v2_retest_manifest.tsv",
            )
            out.writeText(sb.toString())

            val byReg = sorted.groupingBy { it[1] }.eachCount().toSortedMap()
            val summary = StringBuilder("=== car_plates2 V2 真人复测清单（V2 仍未命中）===\n")
            summary.appendLine("total_cases=${sorted.size}")
            summary.appendLine()
            summary.appendLine("by_region:")
            for ((reg, n) in byReg) summary.appendLine("  $reg: $n")
            File(
                locateEvalBase(),
                "car_plates2_zh_20260612_0331/v2_retest_manifest_summary.txt",
            ).writeText(summary.toString())
        }
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else String.format("%.1f%%", 100.0 * n / d)

    private fun locateEvalBase(): File {
        val rel = "asr/evaluation/plate_number"
        var dir: File? = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(12) {
            val base = dir ?: return@repeat
            val f = File(base, rel)
            if (f.isDirectory) return f.canonicalFile
            dir = base.parentFile
        }
        error("eval base not found (walked up from user.dir): $rel")
    }
}
