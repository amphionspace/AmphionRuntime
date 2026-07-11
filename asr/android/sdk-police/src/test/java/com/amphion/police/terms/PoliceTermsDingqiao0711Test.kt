package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 甲方 0711 群反馈的同音误识修复验证（V2 后处理层）。
 * 1 人像核查(人向)、2 警情(锦琴)、3 劝返(劝法)。屏幕→题目 属指令/声学，走热词，不在此断言。
 */
class PoliceTermsDingqiao0711Test {

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

    @Test
    fun recovers_dingqiao_0711_terms() {
        val n = v2()
        val cases = listOf(
            "开始人向核查" to "人像核查",
            "我已到达锦琴现场" to "警情",
            "执行劝法" to "劝返",
            "打开WE SPACE" to "WeSpace",
        )
        for ((raw, tgt) in cases) {
            val out = n.normalize(raw).text
            println("目标=$tgt  in: $raw  out: $out")
            assertTrue("应纠回 $tgt: $out", out.contains(tgt))
        }
    }
}
