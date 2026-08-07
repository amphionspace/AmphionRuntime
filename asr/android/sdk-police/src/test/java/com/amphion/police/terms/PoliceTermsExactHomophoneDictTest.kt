package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/** Harmony V0.2.8 甲方报告整句误识回归与合法同音词防误伤。 */
class PoliceTermsExactHomophoneDictTest {

    private fun reader(path: String): BufferedReader =
        BufferedReader(InputStreamReader(TestAssets.resolve(path).inputStream(), Charsets.UTF_8))

    private fun exact(): PoliceTermsExactHomophoneDict =
        PoliceTermsExactHomophoneDict.loadFromReader(reader(EXACT_ASSET))

    private fun v1(): PoliceTermsNormalizer = PoliceTermsNormalizer.create(
        homophones = PoliceTermsHomophoneDict.loadFromReader(reader(HOMOPHONE_ASSET)),
        gazetteer = PoliceTermsGazetteer.loadFromReader(reader(GAZETTEER_ASSET)),
        exactHomophones = exact(),
    )

    private fun v2(): PoliceTermsNormalizerV2 {
        val terms = reader(GAZETTEER_ASSET).readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .distinct()
            .sortedByDescending { it.length }
        return PoliceTermsNormalizerV2.create(
            PoliceTermsHomophoneDict.loadFromReader(reader(HOMOPHONE_ASSET)),
            PoliceTermsGazetteer.loadFromReader(reader(GAZETTEER_ASSET)),
            terms,
            TermReadingMap.loadFromReader(reader(HOMOPHONE_ASSET)),
            exact(),
        )
    }

    @Test
    fun recovers_all_report_exact_mappings_in_v1_and_v2() {
        val mappings = reader(EXACT_ASSET).useLines { lines ->
            lines.map { it.trim() }
                .filter { it.isNotEmpty() && !it.startsWith("#") }
                .map { line ->
                    val parts = line.split(",", limit = 3)
                    parts[0].trim() to parts[1].trim()
                }
                .toList()
        }
        val v1 = v1()
        val v2 = v2()
        val normalizers = listOf<(String) -> String>(
            { v1.normalize(it).text },
            { v2.normalize(it).text },
        )

        for (normalize in normalizers) {
            for ((raw, expected) in mappings) {
                assertEquals("raw=$raw", expected, normalize(raw))
                assertEquals("punctuated raw=$raw", "  $expected。 ", normalize("  $raw。 "))
            }
        }
    }

    @Test
    fun keeps_legitimate_homophones_when_they_have_context() {
        val inputs = listOf(
            "依法讯问犯罪嫌疑人。",
            "犯罪嫌疑人讯问笔录已经归档。",
            "检查防爆设备是否完好。",
            "按照现行规定执行。",
            "委托代理律师办理。",
            "记得带头盔去学校。",
            "这是我的小甜心。",
            "请及时签收警情。",
            "夜班交接时，班长逐条检查是否已签警情？",
            "值班民警已签警单。",
        )
        val v1 = v1()
        val v2 = v2()
        val normalizers = listOf<(String) -> String>(
            { v1.normalize(it).text },
            { v2.normalize(it).text },
        )

        for (normalize in normalizers) {
            for (input in inputs) assertEquals(input, normalize(input))
        }
    }

    @Test
    fun recovers_signPoliceAlert_deviceTtsFailures_withoutRewritingReceiptTerm() {
        val cases = mapOf(
            "迁警情前要确认警情类别和管辖单位。" to
                "签警情前要确认警情类别和管辖单位。",
            "夜班交接时，班长逐条检查是否已签收警情。" to
                "夜班交接时，班长逐条检查是否已签警情。",
            "夜班交接时班长逐条检查是否已签收警情" to
                "夜班交接时班长逐条检查是否已签警情",
        )
        val v1 = v1()
        val v2 = v2()
        val normalizers = listOf<(String) -> String>(
            { v1.normalize(it).text },
            { v2.normalize(it).text },
        )

        for (normalize in normalizers) {
            for ((raw, expected) in cases) assertEquals("raw=$raw", expected, normalize(raw))
            assertEquals("请及时签收警情。", normalize("请及时签收警情。"))
        }
    }

    @Test
    fun exactDictionary_loadsDeviceTtsRows_withChinesePunctuation() {
        assertEquals(
            "夜班交接时，班长逐条检查是否已签警情。",
            exact().applyWholeUtterance("夜班交接时，班长逐条检查是否已签收警情。"),
        )
        assertEquals(
            "夜班交接时班长逐条检查是否已签警情",
            exact().applyWholeUtterance("夜班交接时班长逐条检查是否已签收警情"),
        )
    }

    @Test
    fun includes_report_terms_in_hotword_preset() {
        val expected = setOf(
            "警戒", "询问", "枫桥经验", "警民联调", "催泪喷射器", "布控", "询问笔录",
            "注销户口死亡迁出", "换领", "当场办结", "提醒警示", "一房多租", "欠薪",
            "工伤赔偿", "经营扰民纠纷", "争执不下", "纠纷摸排", "易引发民转刑的矛盾纠纷",
            "街面秩序", "带离", "街面见警", "疏散围观", "限行", "戴头盔", "处警反馈",
            "单警装备需按规定佩戴", "欺凌",
            "签警单", "签警情",
        )
        assertTrue(PoliceTermsHotwords.PRESET.containsAll(expected))
    }

    companion object {
        private const val EXACT_ASSET = "police_terms/term_exact_homophones.csv"
        private const val HOMOPHONE_ASSET = "police_terms/term_homophones.csv"
        private const val GAZETTEER_ASSET = "police_terms/term_gazetteer.txt"
    }
}
