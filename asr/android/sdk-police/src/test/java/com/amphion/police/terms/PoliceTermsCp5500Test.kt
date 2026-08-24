package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/** New cp5500 final-text variants and adjacent high-frequency collision guards. */
class PoliceTermsCp5500Test {
    private fun reader(path: String): BufferedReader =
        BufferedReader(InputStreamReader(TestAssets.resolve(path).inputStream(), Charsets.UTF_8))

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
            PoliceTermsExactHomophoneDict.loadFromReader(
                reader("police_terms/term_exact_homophones.csv"),
            ),
        )
    }

    @Test
    fun recoversCp5500EJingbaoVariantsOnlyInAppContext() {
        val normalizer = v2()
        val cases = mapOf(
            "咦劲爆，可以拍照上传。" to "e警保，可以拍照上传。",
            "用义警保处理事故。" to "用e警保处理事故。",
            "请打开咦劲爆客户端拍照。" to "请打开e警保客户端拍照。",
            "登录义警保平台上报材料。" to "登录e警保平台上报材料。",
        )
        for ((raw, expected) in cases) {
            assertEquals("raw=$raw", expected, normalizer.normalize(raw).text)
        }
    }

    @Test
    fun keepsGenericJingbaoAndVolunteerPolicePhrases() {
        val normalizer = v2()
        for (raw in listOf(
            "咦，劲爆新闻又来了。",
            "咦劲爆新闻可以上传到网站。",
            "咦劲爆，新闻可以上传到网站。",
            "咦劲爆.新闻可以上传到网站。",
            "咦劲爆……新闻可以上传到网站。",
            "这条消息很劲爆。",
            "义警保安联合巡逻。",
            "义警保护群众安全。",
            "打开义警保护群众的工作记录。",
            "打开义警保，护群众安全。",
            "打开义警保.护群众安全。",
            "义警保。",
            "咦劲爆。",
            "已经协助处理完毕。",
            "情指行平台调度警力。",
            "民警立即出警。",
        )) {
            assertEquals("raw=$raw", raw, normalizer.normalize(raw).text)
        }
    }
}
