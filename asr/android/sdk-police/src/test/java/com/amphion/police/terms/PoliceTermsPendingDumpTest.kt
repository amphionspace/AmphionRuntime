package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader

/**
 * 一次性开发工具：把真机新模型 asr_raw 喂进当前 V2 后处理，按甲方口径（去标点、逐目标词）
 * 重算整词命中，dump 出「适配后仍未通过」清单，供真人复录参考。非回归断言。
 */
class PoliceTermsPendingDumpTest {

    private fun reader(rel: String): BufferedReader =
        BufferedReader(InputStreamReader(TestAssets.resolve(rel).inputStream(), Charsets.UTF_8))

    private fun v2(): PoliceTermsNormalizerV2 {
        val terms = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct().sortedByDescending { it.length }
        return PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
            terms,
            TermReadingMap.loadFromReader(reader("police_terms/term_homophones.csv")),
        )
    }

    private val punct = "，。、；：？！“”‘’（）()《》【】〔〕—…·,.;:?!\"'`~-_／/\\| \t\r\n".toSet()
    private fun strip(s: String) = s.filterNot { it in punct }

    private fun findEval(): File? {
        var dir: File? = File(System.getProperty("user.dir") ?: ".").canonicalFile
        repeat(12) {
            val base = dir ?: return@repeat
            for (rel in listOf(
                "asr/evaluation/police_terms/round_newmodel/police_terms_eval.tsv",
                "AmphionRuntime/asr/evaluation/police_terms/round_newmodel/police_terms_eval.tsv",
            )) {
                val c = File(base, rel)
                if (c.isFile) return c
            }
            dir = base.parentFile
        }
        return null
    }

    @Test
    fun dump_pending_after_adaptation() {
        val n = v2()
        // 依赖本地评测产物；不在树里时（如 CI）优雅跳过，不算失败。
        val eval = findEval() ?: run {
            org.junit.Assume.assumeTrue("round_newmodel/police_terms_eval.tsv 不存在，跳过 dump", false)
            return
        }
        val cat = mapOf("vocab" to "行业词汇", "appname" to "应用名称",
            "policedialog" to "行业对话", "specialcode" to "特殊代码")
        val out = StringBuilder("类别\tutt_id\t目标词\t参考文本(请照此念)\t新模型asr_raw\t适配后normalized\n")
        var pend = 0
        val perCat = linkedMapOf<String, IntArray>() // [miss, total]
        eval.bufferedReader().useLines { lines ->
            lines.drop(1).forEach { line ->
                val f = line.split("\t")
                if (f.size < 7) return@forEach
                val utt = f[1]; val ref = f[2]; val exp = f[3]; val raw = f[4]
                val c = cat[utt.substringBefore("_")] ?: return@forEach
                if (exp.isBlank()) return@forEach
                val terms = exp.split(",", "，", "、", ";", "；").map { it.trim() }.filter { it.isNotEmpty() }
                if (terms.isEmpty()) return@forEach
                val norm = strip(n.normalize(raw).text)
                val hit = terms.all { strip(it) in norm }
                val cc = perCat.getOrPut(c) { IntArray(2) }
                cc[1]++
                if (!hit) {
                    cc[0]++; pend++
                    out.append("$c\t$utt\t$exp\t$ref\t$raw\t${n.normalize(raw).text}\n")
                }
            }
        }
        val dst = File(eval.parentFile.parentFile, "human_record_pending_after_adaptation.tsv")
        dst.writeText(out.toString())
        println("PENDING_DUMP 写入 ${dst.absolutePath}")
        perCat.forEach { (k, v) -> println("PENDING_CAT $k miss=${v[0]}/${v[1]}") }
        println("PENDING_TOTAL $pend")
        print(out.toString())
    }
}
