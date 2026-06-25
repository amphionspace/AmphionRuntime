package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 汇总全部省份真人真机复测语料（evaluation/plate_number/ 各 *_human_retest 目录），
 * 用**当前** V1 / V2 后处理统计分省 + 全国准确率。
 *
 * 运行：bash evaluation/plate_number/run_human_retest_national.sh
 */
class HumanRetestNationalTest {

    private data class Row(val exp: String, val regionKey: String, val regionCn: String, val asr: String, val source: String)

    @Test
    fun national_human_retest_v1_v2() {
        val base = locateEvalBase()
        val rows = loadAllHumanRetestRows(base)
        assumeTrue("未找到任何 *_human_retest 语料", rows.isNotEmpty())

        val v1 = buildV1()
        val home = System.getProperty("realmic.home", "冀辽").toList()
        val v2 = buildV2(home)

        var total = 0
        var v1Exact = 0
        var v2Exact = 0
        var mergeExact = 0
        val byRegion = linkedMapOf<String, IntArray>() // key -> [n,v1,v2]
        val byRegionCn = linkedMapOf<String, String>()

        for (r in rows) {
            val g1 = v1.normalize(r.asr).primaryPlate ?: ""
            val g2 = v2.normalize(r.asr).primaryPlate ?: ""
            val ok1 = g1 == r.exp
            val ok2 = g2 == r.exp
            if (g1.ifEmpty { g2 } == r.exp) mergeExact++

            total++
            val s = byRegion.getOrPut(r.regionKey) { IntArray(3) }
            byRegionCn[r.regionKey] = r.regionCn
            s[0]++
            if (ok1) { v1Exact++; s[1]++ }
            if (ok2) { v2Exact++; s[2]++ }
        }

        val outDir = File(base, "human_retest_national")
        outDir.mkdirs()

        val sb = StringBuilder()
        sb.appendLine("全国真人真机复测 V1 vs V2（当前后处理，汇总全部 *_human_retest）")
        sb.appendLine("v2 辖区先验: ${if (home.isEmpty()) "无(全国中立)" else home.joinToString("")}")
        sb.appendLine("语料目录数: ${base.listFiles()?.count { it.isDirectory && it.name.endsWith("_human_retest") } ?: 0}")
        sb.appendLine("覆盖省份数: ${byRegion.size}")
        sb.appendLine()
        sb.appendLine("==== 全国合计 ====")
        sb.appendLine("total=$total")
        sb.appendLine("v1_exact=$v1Exact (${pct(v1Exact, total)})")
        sb.appendLine("v2_exact=$v2Exact (${pct(v2Exact, total)})")
        sb.appendLine("delta_v2_minus_v1=${v2Exact - v1Exact}")
        sb.appendLine("merge_exact=$mergeExact (${pct(mergeExact, total)})")
        sb.appendLine()
        sb.appendLine("==== 分省（按省份简称排序）====")
        sb.appendLine("province_cn\tregion_key\tn\tv1\tv1%\tv2\tv2%")
        for (key in byRegion.keys.sortedBy { byRegionCn[it] ?: it }) {
            val s = byRegion.getValue(key)
            val cn = byRegionCn[key] ?: key
            sb.appendLine(
                "$cn\t$key\t${s[0]}\t${s[1]}\t${pct(s[1], s[0])}\t${s[2]}\t${pct(s[2], s[0])}",
            )
        }

        val report = sb.toString()
        println(report)
        File(outDir, "metrics_national_v1_v2.txt").writeText(report)

        val miss = buildString {
            appendLine("region_key\texpected\tv1\tv2\tasr\tsource")
            for (r in rows) {
                val g1 = v1.normalize(r.asr).primaryPlate ?: ""
                val g2 = v2.normalize(r.asr).primaryPlate ?: ""
                if (g2 != r.exp) {
                    appendLine("${r.regionKey}\t${r.exp}\t$g1\t$g2\t${r.asr}\t${r.source}")
                }
            }
        }
        File(outDir, "v2_miss_all.tsv").writeText(miss)
        println("[OK] -> ${outDir.absolutePath}/metrics_national_v1_v2.txt")
    }

    private fun loadAllHumanRetestRows(base: File): List<Row> {
        val dirs = base.listFiles()
            ?.filter { it.isDirectory && it.name.endsWith("_human_retest") }
            ?.sortedBy { it.name }
            ?: emptyList()
        val out = mutableListOf<Row>()
        for (d in dirs) {
            val casesFile = File(d, "staging/cases.tsv")
            val evalFile = File(d, "result/plate_eval.tsv")
            if (!evalFile.isFile) continue
            val evalRows = evalFile.readLines().drop(1).filter { it.isNotBlank() }.map { it.split("\t") }
            if (casesFile.isFile) {
                val cases = casesFile.readLines().drop(1).filter { it.isNotBlank() }.map { it.split("\t") }
                val hdr = casesFile.readLines().first().split("\t")
                val ci = hdr.withIndex().associate { (i, n) -> n to i }
                val n = minOf(cases.size, evalRows.size)
                if (cases.size != evalRows.size) {
                    println("[WARN] ${d.name}: cases=${cases.size} eval=${evalRows.size}, use first $n")
                }
                for (i in 0 until n) {
                    val c = cases[i]
                    val e = evalRows[i]
                    val expIdx = ci["expected_plate"] ?: 2
                    val regIdx = ci["region"] ?: 3
                    val exp = e.getOrElse(1) { "" }.ifEmpty { c.getOrElse(expIdx) { "" } }
                    val asr = e.getOrElse(2) { "" }
                    if (exp.isBlank() || asr.isBlank()) continue
                    val (key, cn) = regionFromPlate(exp, c.getOrElse(regIdx) { "" })
                    out.add(Row(exp, key, cn, asr, d.name))
                }
            } else {
                for (e in evalRows) {
                    val exp = e.getOrElse(1) { "" }
                    val asr = e.getOrElse(2) { "" }
                    if (exp.isBlank() || asr.isBlank()) continue
                    val (key, cn) = regionFromPlate(exp, "")
                    out.add(Row(exp, key, cn, asr, d.name))
                }
            }
        }
        return out
    }

    /** 统一用 expected_plate 首字定省；region 列仅作兜底。 */
    private fun regionFromPlate(plate: String, regionCol: String): Pair<String, String> {
        if (plate.isEmpty()) return "unknown" to "未知"
        val ch = plate[0]
        val fromChar = PROVINCE_CHAR_TO_KEY[ch]
        if (fromChar != null) return fromChar to (PROVINCE_KEY_TO_CN[fromChar] ?: fromChar)
        val col = regionCol.trim()
        if (col.length == 1 && PROVINCE_CHAR_TO_KEY.containsKey(col[0])) {
            val k = PROVINCE_CHAR_TO_KEY.getValue(col[0])
            return k to (PROVINCE_KEY_TO_CN[k] ?: k)
        }
        if (col.isNotBlank() && col != "?" && !col.startsWith("human")) {
            val k = col.lowercase()
            return k to (PROVINCE_KEY_TO_CN[k] ?: col)
        }
        return "unknown" to ch.toString()
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
        error("eval base not found: $rel")
    }

    companion object {
        private val PROVINCE_CHAR_TO_KEY = mapOf(
            '京' to "beijing", '津' to "tianjin", '沪' to "shanghai", '渝' to "chongqing",
            '冀' to "hebei", '豫' to "henan", '云' to "yunnan", '辽' to "liaoning",
            '黑' to "heilongjiang", '湘' to "hunan", '皖' to "anhui", '鲁' to "shandong",
            '新' to "xinjiang", '苏' to "jiangsu", '浙' to "zhejiang", '赣' to "jiangxi",
            '鄂' to "hubei", '桂' to "guangxi", '甘' to "gansu", '晋' to "shanxi",
            '蒙' to "neimenggu", '陕' to "shaanxi", '吉' to "jilin", '闽' to "fujian",
            '贵' to "guizhou", '粤' to "guangdong", '青' to "qinghai", '藏' to "xizang",
            '川' to "sichuan", '宁' to "ningxia", '琼' to "hainan",
        )

        private val PROVINCE_KEY_TO_CN = mapOf(
            "beijing" to "北京", "tianjin" to "天津", "shanghai" to "上海", "chongqing" to "重庆",
            "hebei" to "河北", "henan" to "河南", "yunnan" to "云南", "liaoning" to "辽宁",
            "heilongjiang" to "黑龙江", "hunan" to "湖南", "anhui" to "安徽", "shandong" to "山东",
            "xinjiang" to "新疆", "jiangsu" to "江苏", "zhejiang" to "浙江", "jiangxi" to "江西",
            "hubei" to "湖北", "guangxi" to "广西", "gansu" to "甘肃", "shanxi" to "山西",
            "neimenggu" to "内蒙古", "shaanxi" to "陕西", "jilin" to "吉林", "fujian" to "福建",
            "guizhou" to "贵州", "guangdong" to "广东", "qinghai" to "青海", "xizang" to "西藏",
            "sichuan" to "四川", "ningxia" to "宁夏", "hainan" to "海南",
        )
    }
}
