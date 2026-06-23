package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 真机真人录音上的 V1↔V2 对比工装（与 TTS 门禁 [CarPlates2V1V2CompareTest] 同口径）。
 *
 * 用途：当怀疑 TTS 合成音不准导致 V2「假回退」时，用真人真机重录同一批牌复测，
 * 用真实数字裁定「是否可交付 V2-only」。
 *
 * 数据约定（由 evaluation/plate_number/ 下的采集工装产出）：
 * - 录音清单：`realmic/staging/cases.tsv`     列：utt_id, orig_utt_id, expected_plate, region, text, audio_path
 * - 设备转写：`realmic/result/plate_eval.tsv` 列：timestamp_ms, expected_plate, asr_raw, normalized, plate_extracted, plate_valid
 * 两文件均按 utt_id 排序、行数一致（assemble_realmic.py 保证）。
 *
 * 无录音数据时**优雅跳过**（assumeTrue），不影响常规 CI。
 * 一键运行：`bash evaluation/plate_number/run_realmic_compare.sh`
 */
class RealMicCompareTest {

    private data class Row(val uttId: String, val exp: String, val region: String, val asr: String)

    @Test
    fun v2_vs_v1_on_real_mic() {
        val base = locateEvalBase()
        // 可指向专项目录（如 realmic_jir_liaob），默认 realmic。
        val sub = System.getProperty("realmic.dir", "realmic")
        val casesFile = File(base, "$sub/staging/cases.tsv")
        val evalFile = File(base, "$sub/result/plate_eval.tsv")
        assumeTrue(
            "无真机语料，跳过（先用采集工装录音并拉回 plate_eval.tsv）：\n" +
                "  cases=$casesFile\n  eval =$evalFile",
            casesFile.isFile && evalFile.isFile,
        )

        val cases = casesFile.readLines().drop(1).filter { it.isNotBlank() }.map { it.split("\t") }
        val evalRows = evalFile.readLines().drop(1).filter { it.isNotBlank() }.map { it.split("\t") }
        require(cases.size == evalRows.size) {
            "cases/eval 行数不一致：${cases.size} vs ${evalRows.size}（请重跑 assemble_realmic.py / 拉取设备结果）"
        }
        val rows = cases.zip(evalRows).map { (c, e) ->
            Row(uttId = c[0], exp = e.getOrElse(1) { "" }.ifEmpty { c.getOrElse(2) { "" } }, region = c.getOrElse(3) { "?" }, asr = e.getOrElse(2) { "" })
        }
        require(rows.isNotEmpty()) { "空的真机语料" }

        val v1 = buildV1()
        // 部署辖区先验（雄安交付配置）：-Drealmic.home=冀辽；默认空=全国中立。
        val home = System.getProperty("realmic.home", "").toList()
        val v2 = buildV2(home)

        var total = 0
        var v1Exact = 0
        var v2Exact = 0
        var mergeExact = 0
        val recovers = mutableListOf<String>()
        val regresses = mutableListOf<String>()
        val byRegion = linkedMapOf<String, IntArray>()

        for (r in rows) {
            val g1 = v1.normalize(r.asr).primaryPlate ?: ""
            val g2 = v2.normalize(r.asr).primaryPlate ?: ""
            val ok1 = g1 == r.exp
            val ok2 = g2 == r.exp
            if (g1.ifEmpty { g2 } == r.exp) mergeExact++

            total++
            val s = byRegion.getOrPut(r.region) { IntArray(5) }
            s[0]++
            if (ok1) { v1Exact++; s[1]++ }
            if (ok2) { v2Exact++; s[2]++ }
            if (ok2 && !ok1) { recovers.add("${r.region} exp=${r.exp} v1=$g1 | ${r.asr}"); s[3]++ }
            if (ok1 && !ok2) { regresses.add("${r.region} exp=${r.exp} v2=$g2 | ${r.asr}"); s[4]++ }
        }

        val sb = StringBuilder()
        sb.appendLine("realmic real-human/real-device V1 vs V2")
        sb.appendLine("total=$total")
        sb.appendLine("v1_exact=$v1Exact (${pct(v1Exact, total)})")
        sb.appendLine("v2_exact=$v2Exact (${pct(v2Exact, total)})")
        sb.appendLine("delta_v2_minus_v1=${v2Exact - v1Exact}")
        sb.appendLine("merge_exact=$mergeExact (${pct(mergeExact, total)})")
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
        sb.appendLine("--- regress (V2 lost vs V1) ---")
        regresses.forEach { sb.appendLine("  REGRESS $it") }
        sb.appendLine("--- recover (V2 gained vs V1) ---")
        recovers.forEach { sb.appendLine("  RECOVER $it") }

        val report = sb.toString()
        println(report)
        runCatching { File(base, "$sub/result/metrics_v1_v2.txt").writeText(report) }
        // 导出 V2 全部未命中（含双错），供错误模式挖掘。
        runCatching {
            val miss = StringBuilder("expected\tv1\tv2\tasr\n")
            for (r in rows) {
                val g1 = v1.normalize(r.asr).primaryPlate ?: ""
                val g2 = v2.normalize(r.asr).primaryPlate ?: ""
                if (g2 != r.exp) miss.appendLine("${r.exp}\t$g1\t$g2\t${r.asr}")
            }
            File(base, "$sub/result/v2_miss.tsv").writeText(miss.toString())
        }

        // 放行判据（交付 V2-only）：真机上 V2 不差于 V1。此处只做软提示，不强制断言，
        // 因真机语料规模/构成可变；最终由人结合 by_region 决策。
        println(
            if (v2Exact >= v1Exact) {
                "[VERDICT] 真机上 V2 不差于 V1（Δ=${v2Exact - v1Exact}）→ 支持交付 V2-only。"
            } else {
                "[VERDICT] 真机上 V2 仍落后 V1（Δ=${v2Exact - v1Exact}）→ 先用真机回归补 V2 读音表，勿急切 V2-only。"
            },
        )
    }

    private fun buildV1(): PlateNormalizer {
        val csv = TestAssets.resolve("plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(BufferedReader(FileReader(csv, StandardCharsets.UTF_8)))
        return PlateNormalizer.create(dict)
    }

    private fun buildV2(contextProvinces: List<Char> = emptyList()): PlateNormalizerV2 {
        val kb = loadKnowledgeBase()
        return PlateNormalizerV2.create(kb, loadReadingMap(kb), contextProvinces)
    }

    private fun pct(n: Int, d: Int): String =
        if (d == 0) "n/a" else String.format("%.1f%%", 100.0 * n / d)

    private fun locateEvalBase(): File {
        val rel = "evaluation/plate_number"
        var dir: File? = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(12) {
            val baseDir = dir ?: return@repeat
            val f = File(baseDir, rel)
            if (f.isDirectory) return f.canonicalFile
            dir = baseDir.parentFile
        }
        error("eval base not found (walked up from user.dir): $rel")
    }
}
