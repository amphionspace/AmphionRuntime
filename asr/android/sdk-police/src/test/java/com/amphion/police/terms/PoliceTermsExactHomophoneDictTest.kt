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
    fun recovers_signPoliceTerms_deviceFailures_withoutMergingTheTwoTerms() {
        val cases = mapOf(
            // 2026-08-13 三星麦克风实测/同事截图：用户逐次只说“签警情”。
            "仙警情。" to "签警情。",
            "千锦情？" to "签警情？",
            "  千警情。 " to "  签警情。 ",
            "千警情情。" to "签警情。",
            // 2026-08-14 三星麦克风实测及甲方反馈：两个目标术语必须分别恢复。
            "千景情。" to "签警情。",
            "天锦情？" to "签警情？",
            "  天警情。 " to "  签警情。 ",
            "先警情。" to "签警情。",
            "边警情。" to "签警情。",
            // 2026-08-14 三星下一轮麦克风实测：8 次中“前景情”2 次，另有“见见情”1 次。
            "前景情。" to "签警情。",
            "  见见情？ " to "  签警情？ ",
            // 2026-08-14 三星下一轮麦克风实测：两个目标术语分别恢复。
            "见警情。" to "签警情。",
            "  前景单？ " to "  签警单？ ",
            "天井丹。" to "签警单。",
            "天景丹？" to "签警单？",
            "迁警情前要确认警情类别和管辖单位。" to
                "签警情前要确认警情类别和管辖单位。",
            "千景情前要确认警情类别和管辖单位。" to
                "签警情前要确认警情类别和管辖单位。",
            "千景丹之前先核对处置经过和当事人信息。" to
                "签警单之前先核对处置经过和当事人信息。",
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
            assertEquals("签警单。", normalize("签警单。"))
            assertEquals("签警情。", normalize("签警情。"))
            assertEquals("请及时签收警情。", normalize("请及时签收警情。"))
            assertEquals("请复述仙警情这个错误。", normalize("请复述仙警情这个错误。"))
            assertEquals("请复述先警情这个错误。", normalize("请复述先警情这个错误。"))
            assertEquals("请复述前景情这个错误。", normalize("请复述前景情这个错误。"))
            assertEquals("请复述见见情这个错误。", normalize("请复述见见情这个错误。"))
            assertEquals("前景情况良好。", normalize("前景情况良好。"))
            assertEquals("市场前景可期。", normalize("市场前景可期。"))
            assertEquals("我们改天见见面。", normalize("我们改天见见面。"))
            assertEquals("见警情即响应。", normalize("见警情即响应。"))
            assertEquals("看见警情列表后立即处置。", normalize("看见警情列表后立即处置。"))
            assertEquals("街面见警情况良好。", normalize("街面见警情况良好。"))
            assertEquals("常见警情包括纠纷和盗窃。", normalize("常见警情包括纠纷和盗窃。"))
            assertEquals("行业前景单独评估。", normalize("行业前景单独评估。"))
            assertEquals("发展前景单一并不理想。", normalize("发展前景单一并不理想。"))
            assertEquals("画面前景单调，需要调整。", normalize("画面前景单调，需要调整。"))
            assertEquals("请复述前景单这个错误。", normalize("请复述前景单这个错误。"))
            assertEquals("前警情。", normalize("前警情。"))
            assertEquals("查看此前警情。", normalize("查看此前警情。"))
            assertEquals("调取先前警情记录。", normalize("调取先前警情记录。"))
            assertEquals("请复述天景丹这个错误。", normalize("请复述天景丹这个错误。"))
            assertEquals("陈景丹。", normalize("陈景丹。"))
        }
    }

    @Test
    fun recovers_qianshouJingdan_southwesternDeviceFailures_onlyAsWholeUtterances() {
        val cases = mapOf(
            // 2026-08-14 四川话/四川口音固定短语真机回放：用户每次只说“签收警单”。
            "前手进单。" to "签收警单。",
            "  前收金单？ " to "  签收警单？ ",
            "钱收金单。" to "签收警单。",
            "千手精打！" to "签收警单！",
            "千手警单。" to "签收警单。",
            "千手简单？" to "签收警单？",
            "钱收进单。" to "签收警单。",
            "牵手进单。" to "签收警单。",
            "前手简单。" to "签收警单。",
            // 2026-08-14 三星麦克风手工复测 20 次：11 次正确，以下 6 种共 9 次错误。
            "千手经单。" to "签收警单。",
            "千手竞单？" to "签收警单？",
            "牵手静单！" to "签收警单！",
            "千手进单。" to "签收警单。",
            "牵手竞单？" to "签收警单？",
            "千手清单。" to "签收警单。",
            // 同一 WAV 修复后回放新增观测变体。
            "千手订单；" to "签收警单；",
        )
        val normalizers = listOf<(String) -> String>(
            { v1().normalize(it).text },
            { v2().normalize(it).text },
        )

        for (normalize in normalizers) {
            for ((raw, expected) in cases) assertEquals("raw=$raw", expected, normalize(raw))
            for (term in listOf("签收警单。", "签警单。", "签警情。", "签收警情。")) {
                assertEquals(term, normalize(term))
            }
            for (variant in listOf(
                "前手进单", "前收金单", "钱收金单", "千手精打", "千手警单",
                "千手简单", "钱收进单", "牵手进单", "前手简单",
                "千手经单", "千手竞单", "牵手静单", "千手进单", "牵手竞单", "千手清单",
                "千手订单",
            )) {
                val input = "请复述${variant}这个错误。"
                assertEquals(input, normalize(input))
            }
            // 相同字串出现在正常业务上下文中时不得做子串替换。
            for (input in listOf(
                "前手进单后，后手再复核。",
                "财务确认前收金单后再对账。",
                "钱收进单后再开发票。",
                "牵手进单是活动名称。",
                "千手简单模式已关闭。",
                "前手简单，后手复杂。",
                "千手经单行本已经入库。",
                "千手竞单活动已结束。",
                "牵手静单是项目名称。",
                "千手进单后再复核。",
                "牵手竞单是活动名称。",
                "千手清单已经发布。",
                "千手订单已经发货。",
            )) {
                assertEquals(input, normalize(input))
            }
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
