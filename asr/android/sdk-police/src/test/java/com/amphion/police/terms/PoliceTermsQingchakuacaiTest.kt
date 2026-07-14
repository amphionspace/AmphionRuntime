package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/** 清查快采 真机同音误识（查↔茶、采↔彩/菜/餐）纠正验证。 */
class PoliceTermsQingchakuacaiTest {

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
    fun corrects_qingchakuacai_mishears() {
        val n = v2()
        for (bad in listOf("清查快彩", "清查快菜", "清茶快采", "清茶快彩", "清茶快菜", "清茶快餐")) {
            assertEquals("请点击清查快采。", n.normalize("请点击$bad。").text)
        }
        // 正确输入不受影响
        assertEquals("请点击清查快采。", n.normalize("请点击清查快采。").text)
    }
}
