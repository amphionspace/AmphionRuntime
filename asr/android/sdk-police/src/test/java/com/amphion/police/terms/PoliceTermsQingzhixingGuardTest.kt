package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 「情指行」上下文护栏纠正验证：App 语境下把 请指信/停止行/停止航 纠回 情指行，
 * 且不误伤 停止行动/停止航班/请指信息 等通用词。
 */
class PoliceTermsQingzhixingGuardTest {

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
    fun recovers_qingzhixing_in_app_context() {
        val n = v2()
        // 真机/TTS 实测未命中的三条（App 语境）
        assertTrue(n.normalize("请在手机上打开，请指信客户端。").text.contains("情指行"))
        assertTrue(n.normalize("所有民警都要登录，停止行上报信息。").text.contains("情指行"))
        assertTrue(n.normalize("遇到警情，先在停止航里签收。").text.contains("情指行"))
    }

    @Test
    fun does_not_touch_collision_words() {
        val n = v2()
        // 碰撞后继字：停止行动/停止航班/请指信息 —— 一律不纠
        assertEquals("民警立即停止行动。", n.normalize("民警立即停止行动。").text)
        assertFalse(n.normalize("民警立即停止行动。").text.contains("情指行"))
        assertEquals("因天气停止航班调度。", n.normalize("因天气停止航班调度。").text)
        assertFalse(n.normalize("因天气停止航班调度。").text.contains("情指行"))
        assertEquals("请指信息已上报中心。", n.normalize("请指信息已上报中心。").text)
        assertFalse(n.normalize("请指信息已上报中心。").text.contains("情指行"))
    }

    @Test
    fun does_not_touch_without_context() {
        val n = v2()
        // 无 App 语境、无打开类动词 —— 不纠
        assertFalse(n.normalize("他说了停止行三个字。").text.contains("情指行"))
    }

    @Test
    fun keeps_correct_term() {
        val n = v2()
        assertEquals("请在手机上打开情指行客户端。", n.normalize("请在手机上打开情指行客户端。").text)
    }
}
