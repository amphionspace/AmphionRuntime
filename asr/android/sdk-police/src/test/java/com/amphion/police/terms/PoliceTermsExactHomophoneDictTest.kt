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
            // 2026-08-15 甲方 Harmony SDK 反馈与同批三星音频复测：仅纠正完整 final。
            "山井情。" to "签警情。",
            "  天井干？ " to "  签警单？ ",
            "签景单。" to "签警单。",
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
            assertEquals("签收警单。", normalize("签收警单。"))
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
            assertEquals("请复述山井情这个错误。", normalize("请复述山井情这个错误。"))
            assertEquals("山井情况已经登记。", normalize("山井情况已经登记。"))
            assertEquals("请复述千锦情这个错误。", normalize("请复述千锦情这个错误。"))
            assertEquals("千锦情是作品名。", normalize("千锦情是作品名。"))
            assertEquals("请复述天井干这个错误。", normalize("请复述天井干这个错误。"))
            assertEquals("院子的天井干了。", normalize("院子的天井干了。"))
            assertEquals("天井干燥后再施工。", normalize("天井干燥后再施工。"))
            assertEquals("请复述签景单这个错误。", normalize("请复述签景单这个错误。"))
            assertEquals("签景单据之前先核对内容。", normalize("签景单据之前先核对内容。"))
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
    fun recovers_xiaoqiaoSemanticDeviceFailures_withoutRewritingLegitimateStandaloneTerms() {
        val cases = mapOf(
            // 2026-08-14 甲方小乔语义语料：仅收录明显误识的完整 final。
            "停止群平台。" to "勤指情平台。",
            "因景致联？" to "京警智联？",
            "侧卡盘查！" to "设卡盘查！",
            "停止熊平台。" to "情指行平台。",
            "先收紧张。" to "签收警单。",
            "前所进单。" to "签收警单。",
            "只性接触警。" to "指信接处警。",
            "帮我打开谨信语。" to "帮我打开警信。",
            "指信接触景。" to "指信接处警。",
            "指信接触警。" to "指信接处警。",
            "色卡款场。" to "设卡盘查。",
            // 2026-08-15 甲方术语统计表：仅新增无稳定独立语义的完整 final。
            "色卡盘跺。" to "设卡盘查。",
            "  经纬度菜级？ " to "  经纬度采集？ ",
        )
        val protectedTargets = listOf(
            "e警保", "义警", "争执不下", "京警智联", "人员全项查询", "勤指情平台",
            "处警反馈", "处警完毕", "帮我打开警信", "情指中心", "情指行", "情指行平台",
            "打开帮填", "执行劝返", "拘传", "指信接处警", "指信-接处警", "接处警",
            "摸排", "案结事了", "治爆", "清查快采", "滋事人员", "签收警单",
            "经纬度采集", "缉枪", "羁押", "见警率", "视频清整", "警官", "警戒",
            "警鉴", "设卡盘查", "询问", "边检",
        )
        val excludedStandaloneInputs = listOf(
            // 自然词、姓名、独立警务术语、产品/机构名形态及疑似错标音频均不得猜测改写。
            "不仅反馈", "值不下", "公事人员", "半结石了", "居船", "按揭示",
            "是人员", "进阶促进", "限警力", "陷警力", "易警报", "易锦保", "林子中心",
            "影子中心", "瓶子中心", "零子中心", "引资型平台", "打开邦铁", "经警，智联",
            "金井智联", "帮我打开启", "是彻底先进行", "布景完毕", "日报", "停止行",
            "案件", "渔船", "第一枪", "自报", "低压", "军事人员", "医护人员", "失事人员",
            "报警完毕", "接处", "现场", "申请", "约束", "边界", "咿呀", "一", "一呀",
            "一警报", "引荐", "意境", "意见", "愚蠢", "感谢", "愿景", "是不是", "有人问",
            "极强", "眼见", "林子晴平台", "林子行", "尹见", "李强",
        )
        val normalizers = listOf<(String) -> String>(
            { v1().normalize(it).text },
            { v2().normalize(it).text },
        )
        val existingContextOutputs = mapOf(
            // 既有全局规则会在长上下文中改写“指信接触”；本修复不得在其上继续整句替换。
            "请复述指信接触景这个错误。" to "请复述指信接处警景这个错误。",
            "文本里写着指信接触景，请不要改写。" to "文本里写着指信接处警景，请不要改写。",
            "请复述指信接触警这个错误。" to "请复述指信接处警警这个错误。",
            "文本里写着指信接触警，请不要改写。" to "文本里写着指信接处警警，请不要改写。",
        )

        for (normalize in normalizers) {
            for ((raw, expected) in cases) {
                assertEquals("raw=$raw", expected, normalize(raw))
                val bare = raw.trimEnd('。', '？', '！')
                for (input in listOf(
                    "请复述${bare}这个错误。",
                    "文本里写着${bare}，请不要改写。",
                )) {
                    assertEquals(existingContextOutputs[input] ?: input, normalize(input))
                }
            }
            for (target in protectedTargets) {
                assertEquals("protected target=$target", "$target。", normalize("$target。"))
            }
            for (input in excludedStandaloneInputs) {
                assertEquals("excluded standalone=$input", "$input。", normalize("$input。"))
            }
            for (input in listOf(
                "色卡盘查结果待确认。",
                "经纬度采集级别需要确认。",
                "仅经纬度采集。",
            )) {
                assertEquals(input, normalize(input))
            }
        }
    }

    @Test
    fun recovers_latestPoliceMicFailures_withoutGlobalSubstringRewrites() {
        val cases = mapOf(
            // 产品确认：开启警务增强时，独立“制报”按警务术语“治爆”处理。
            "制报。" to "治爆。",
            "  制报？ " to "  治爆？ ",
            // 甲方反馈与三星真人复测：仅纠正完整“勤指情平台”误识 final。
            "秦志情平台。" to "勤指情平台。",
            "秦止情平台？" to "勤指情平台？",
            "秦纸情平台！" to "勤指情平台！",
            "秦之情平台。" to "勤指情平台。",
            "秦芷情平台。" to "勤指情平台。",
            "秦止晴平台。" to "勤指情平台。",
            // 20260815 三星真人复测：仅纠正完整“案结事了”误识 final。
            "按揭是了。" to "案结事了。",
            "  按揭示了？ " to "  案结事了？ ",
            // 20260815 三星真人复测：产品确认在警务增强下将裸短词视作目标术语。
            "据传。" to "拘传。",
            "  停止情平台？ " to "  勤指情平台？ ",
            "鸡鸭！" to "羁押！",
        )
        val normalizers = listOf<(String) -> String>(
            { v1().normalize(it).text },
            { v2().normalize(it).text },
        )

        for (normalize in normalizers) {
            for ((raw, expected) in cases) {
                assertEquals("raw=$raw", expected, normalize(raw))
            }
            for (input in listOf(
                "请复述制报这个错误。",
                "制报系统正在生成报表。",
                "编制报告要按时完成。",
                "控制报警器已安装。",
                "法制报刊已经送达。",
                "请复述秦志情平台这个错误。",
                "秦止情平台项目正在评审。",
                "请复述秦纸情平台这个错误。",
                "秦之情平台是作品名称。",
                "请复述秦芷情平台这个错误。",
                "秦止晴平台负责人已到场。",
                "请复述按揭是了这个错误。",
                "按揭是了解住房贷款的重要方式。",
                "请复述按揭示了这个错误。",
                "公告揭示了办理风险。",
                "按揭示。",
                "按揭业务办结了。",
                "案结事了。",
                "请复述据传这个错误。",
                "据传该消息尚未证实。",
                "数据传输已经完成。",
                "请复述停止情平台这个错误。",
                "停止情平台项目的讨论。",
                "请复述鸡鸭这个错误。",
                "养殖场里有鸡鸭。",
                "鸡鸭鱼肉都已备齐。",
                "拘传。",
                "勤指情平台。",
                "羁押。",
                "景观。",
                "城市景观需要保护。",
                "警官。",
                "值班警官已经到场。",
                "精简。",
                "精简流程后再提交。",
                "警戒。",
                "警戒区域禁止进入。",
                "警鉴。",
                "打开警鉴查看记录。",
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
