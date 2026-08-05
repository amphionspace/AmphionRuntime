package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 甲方蓝色 bubble 反馈：二至三字警务短词即使进入热词图，仍可能落到常见近音字。
 *
 * 这组测试约束短词纠正只能在“整句就是术语”或带明确警务锚点时生效，不能把
 * 接触景点、接触警报、接触井下设备等普通表达改成接处警。
 */
class PoliceTermsShortGuardTest {

    private fun reader(rel: String): BufferedReader =
        BufferedReader(InputStreamReader(TestAssets.resolve(rel).inputStream(), Charsets.UTF_8))

    private fun v1(): PoliceTermsNormalizer = PoliceTermsNormalizer.create(
        PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
        PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
    )

    private fun v2(): PoliceTermsNormalizerV2 {
        val terms = reader("police_terms/term_gazetteer.txt").readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct()
            .sortedByDescending { it.length }
        return PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader("police_terms/term_homophones.csv")),
            PoliceTermsGazetteer.loadFromReader(reader("police_terms/term_gazetteer.txt")),
            terms,
            TermReadingMap.loadFromReader(reader("police_terms/term_homophones.csv")),
        )
    }

    @Test
    fun recovers_customer_short_terms_in_v1_and_v2() {
        val normalizers = listOf<(String) -> String>(
            { v1().normalize(it).text },
            { v2().normalize(it).text },
        )
        val cases = linkedMapOf(
            "喻传。" to "拘传。",
            "居传" to "拘传",
            "拒传。" to "拘传。",
            "接触景。" to "接处警。",
            "接触警。" to "接处警。",
            "接触井。" to "接处警。",
            "接触颈。" to "接处警。",
            "接出警。" to "接处警。",
            "街处警。" to "接处警。",
            "女性接触颈。" to "指信接处警。",
        )

        for (normalize in normalizers) {
            for ((raw, expected) in cases) {
                assertEquals("raw=$raw", expected, normalize(raw))
            }
        }
    }

    @Test
    fun recovers_short_terms_with_police_context() {
        val normalizers = listOf<(String) -> String>(
            { v1().normalize(it).text },
            { v2().normalize(it).text },
        )
        val cases = linkedMapOf(
            "办理喻传要经过审批。" to "办理拘传要经过审批。",
            "依法居传到案。" to "依法拘传到案。",
            "申请拒传审批。" to "申请拘传审批。",
            "规范接触警流程。" to "规范接处警流程。",
            "接出警记录已经上传。" to "接处警记录已经上传。",
            "移动接触颈系统正在同步。" to "移动接处警系统正在同步。",
        )

        for (normalize in normalizers) {
            for ((raw, expected) in cases) {
                assertEquals("raw=$raw", expected, normalize(raw))
            }
        }
    }

    @Test
    fun keeps_generic_collision_phrases_unchanged() {
        val normalizers = listOf<(String) -> String>(
            { v1().normalize(it).text },
            { v2().normalize(it).text },
        )
        val inputs = listOf(
            "工作人员接触景点游客。",
            "现场接触景点游客。",
            "不要接触警报装置。",
            "施工人员接触井下设备。",
            "这篇文章介绍街处的警务站。",
            "系统拒传文件后会自动重试。",
        )

        for (normalize in normalizers) {
            for (input in inputs) {
                assertEquals(input, normalize(input))
            }
        }
    }

    @Test
    fun includes_context_rich_hotwords() {
        val expected = setOf(
            "办理拘传",
            "依法拘传",
            "进行拘传",
            "拘传到案",
            "拘传审批",
            "规范接处警",
            "接处警记录",
            "接处警工作",
            "接处警规范",
        )
        assertTrue(PoliceTermsHotwords.PRESET.containsAll(expected))
    }
}
