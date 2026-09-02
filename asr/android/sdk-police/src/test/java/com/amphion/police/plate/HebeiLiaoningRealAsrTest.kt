package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.nio.charset.StandardCharsets

/**
 * 在既有真机 ASR 语料上，专测 冀R / 辽B 两类牌的 V1 vs V2 准确率（V2-only 决策参考）。
 *
 * 这两类是甲方现网主力牌、也是老方案 V1 重点精调对象。复用历史真机 plate_eval.tsv
 * （`expected_plate` + `asr_raw` 已就绪），把 asr_raw 喂进**当前** V1 / V2，分牌别统计。
 *
 * 无语料时优雅跳过。报告写到 `asr/evaluation/plate_number/metrics_jiR_liaoB_v1v2.txt`。
 */
class HebeiLiaoningRealAsrTest {

    private val corpora = listOf(
        "round01",
        "dialogue_full_1076",
        "gpu13_accent_dialogue",
        "jjs_car_plates_20260611",
    )

    private val prefixes = listOf("冀R", "辽B")

    @Test
    fun jiR_liaoB_accuracy_on_real_asr() {
        val base = locateEvalBase()
        val files = corpora.map { it to File(base, "$it/plate_eval.tsv") }.filter { it.second.isFile }
        assumeTrue("无可用真机语料（plate_eval.tsv）", files.isNotEmpty())

        val v1 = buildV1()
        val v2 = buildV2()                       // 全国默认（无辖区先验）
        val v2Home = buildV2(listOf('冀', '辽'))  // 雄安部署（辖区先验 = 冀/辽）

        val sb = StringBuilder()
        sb.appendLine("冀R / 辽B real-asr V1 vs V2（当前后处理）")
        sb.appendLine("v2=全国默认  v2H=雄安辖区先验[冀,辽]")
        sb.appendLine()

        // prefix -> [n, v1ok, v2ok, v2homeok]
        val combined = prefixes.associateWith { IntArray(4) }
        val v2Miss = mutableListOf<String>()
        // 分牌别落盘全部 v2H 未命中（聚焦 V1 命中 V2 漏的可补缺口）
        val missByPrefix = prefixes.associateWith { mutableListOf<String>() }

        for ((name, f) in files) {
            val rows = f.readLines().drop(1).filter { it.isNotBlank() }.map { it.split("\t") }
                .filter { it.size >= 3 && prefixes.any { p -> it[1].startsWith(p) } }
            if (rows.isEmpty()) continue
            val per = prefixes.associateWith { IntArray(4) }
            for (r in rows) {
                val exp = r[1]
                val asr = r[2]
                val pfx = prefixes.first { exp.startsWith(it) }
                val ok1 = (v1.normalize(asr).primaryPlate ?: "") == exp
                val ok2 = (v2.normalize(asr).primaryPlate ?: "") == exp
                val ok2h = (v2Home.normalize(asr).primaryPlate ?: "") == exp
                for (acc in listOf(per.getValue(pfx), combined.getValue(pfx))) {
                    acc[0]++; if (ok1) acc[1]++; if (ok2) acc[2]++; if (ok2h) acc[3]++
                }
                if (!ok2h && name == "jjs_car_plates_20260611") {
                    v2Miss.add("$exp  v2H=${v2Home.normalize(asr).primaryPlate ?: ""}  | $asr")
                }
                if (!ok2h && ok1) {
                    val got = v2Home.normalize(asr).primaryPlate ?: ""
                    missByPrefix.getValue(pfx).add("$name\t$exp\t$got\t$asr")
                }
            }
            sb.appendLine("[$name]")
            for (p in prefixes) {
                val s = per.getValue(p)
                if (s[0] == 0) continue
                sb.appendLine("  $p: n=${s[0]}  v1=${s[1]}(${pct(s[1], s[0])})  v2=${s[2]}(${pct(s[2], s[0])})  v2H=${s[3]}(${pct(s[3], s[0])})  Δ(v2H-v1)=${s[3] - s[1]}")
            }
        }

        sb.appendLine()
        sb.appendLine("==== 合计（全部语料）====")
        var tn = 0; var t1 = 0; var t2 = 0; var t2h = 0
        for (p in prefixes) {
            val s = combined.getValue(p)
            if (s[0] == 0) continue
            sb.appendLine("  $p: n=${s[0]}  v1=${s[1]}(${pct(s[1], s[0])})  v2=${s[2]}(${pct(s[2], s[0])})  v2H=${s[3]}(${pct(s[3], s[0])})  Δ(v2H-v1)=${s[3] - s[1]}")
            tn += s[0]; t1 += s[1]; t2 += s[2]; t2h += s[3]
        }
        sb.appendLine("  冀R+辽B 总: n=$tn  v1=$t1(${pct(t1, tn)})  v2=$t2(${pct(t2, tn)})  v2H=$t2h(${pct(t2h, tn)})  Δ(v2H-v1)=${t2h - t1}")

        if (v2Miss.isNotEmpty()) {
            sb.appendLine()
            sb.appendLine("--- jjs(冀R 字母序号牌) v2H 未命中 ---")
            v2Miss.take(40).forEach { sb.appendLine("  $it") }
        }

        val report = sb.toString()
        println(report)
        runCatching { File(base, "metrics_jiR_liaoB_v1v2.txt").writeText(report) }
        runCatching {
            for ((p, miss) in missByPrefix) {
                val tag = if (p == "冀R") "jiR" else "liaoB"
                val body = buildString {
                    appendLine("# v2H 未命中且 V1 命中（corpus\texp\tv2H\tasr）  n=${miss.size}")
                    miss.sorted().forEach { appendLine(it) }
                }
                File(base, "miss_${tag}_v2home.tsv").writeText(body)
            }
        }
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
        val rel = "asr/evaluation/plate_number"
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
