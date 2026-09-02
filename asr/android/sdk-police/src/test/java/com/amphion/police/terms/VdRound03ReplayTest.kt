package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File

/** Round03 VD 口音：增派截断 / 处警 / 已签收 / 签收截断 回放 + round01 TSV 离线验证。 */
class VdRound03ReplayTest {

    private lateinit var normalizer: PoliceTermsNormalizer

    @Before
    fun setUp() {
        normalizer = PoliceTermsNormalizer.create(loadProductionHomophones(), loadProductionGazetteer())
    }

    private fun loadProductionHomophones(): PoliceTermsHomophoneDict {
        val f = locateAsset("term_homophones.csv")
        return PoliceTermsHomophoneDict.loadFromReader(BufferedReader(f.reader()))
    }

    private fun loadProductionGazetteer(): PoliceTermsGazetteer {
        val f = locateAsset("term_gazetteer.txt")
        return PoliceTermsGazetteer.loadFromReader(BufferedReader(f.reader()))
    }

    private fun locateAsset(name: String): File =
        TestAssets.resolve("police_terms/$name")

    @Test
    fun replay_vd_p6_zengpaiTruncation() {
        assertFixed(
            "处警反馈显示，物业正在协助维持秩序，暂不需要增派。",
            "处警反馈显示，物业正在协助维持秩序，暂不需要增派警力。",
        )
        assertFixed(
            "处警反馈显示，双方正在等待民警到场，暂不需要增派警。",
            "处警反馈显示，双方正在等待民警到场，暂不需要增派警力。",
        )
        assertFixed(
            "处警过程中出现现场交通拥堵情况，已请求增派。",
            "处警过程中出现现场交通拥堵情况，已请求增派警力。",
        )
    }

    @Test
    fun replay_vd_p2_chujingExtended() {
        assertFixed(
            "除警途中已联系报警人确认车辆停放方向和郑州市金水区花园路斑马线旁位置。",
            "处警途中已联系报警人确认车辆停放方向和郑州市金水区花园路斑马线旁位置。",
        )
        assertFixed(
            "请出行人员到场后，清河是疑似拉扯行为情况，再反馈是否存在违法行为。",
            "请处警人员到场后，清河是疑似拉扯行为情况，再反馈是否存在违法行为。",
        )
        assertFixed(
            "出警过程中出现未成年人在场情况，已请求请求指挥中心。",
            "处警过程中出现未成年人在场情况，已请求请求指挥中心。",
        )
        assertFixed(
            "二十三次，西七正在出警现场，当事人对事实说法不一致，请后续保持联。",
            "二十三次，西七正在处警现场，当事人对事实说法不一致，请后续保持联。",
        )
    }

    @Test
    fun replay_vd_yiqianshou() {
        assertFixed(
            "以签收警情，目前正在联系报警人确认具体位置、现场状态为对方已经离开，但报警人要求核实。",
            "已签收警情，目前正在联系报警人确认具体位置、现场状态为对方已经离开，但报警人要求核实。",
        )
        assertFixed(
            "你签收警单处警人员正在核对车辆停放方向，现场备注，为报警人不方便离开现场。",
            "已签收警单处警人员正在核对车辆停放方向，现场备注，为报警人不方便离开现场。",
        )
    }

    @Test
    fun replay_vd_qianshouTruncation() {
        assertFixed(
            "餐馆排队争执警情已推送至辖区派出所，请及时签收警。",
            "餐馆排队争执警情已推送至辖区派出所，请及时签收警情。",
        )
        assertFixed(
            "宠物扰民警单已推送至派出所值班人员，请附近警力签收。",
            "宠物扰民警单已推送至派出所值班人员，请附近警力签收警单。",
        )
        assertFixed(
            "先收警情后，发现需要进一步回访确认，请协助核实报警人不方便离开现场。",
            "签收警情后，发现需要进一步回访确认，请协助核实报警人不方便离开现场。",
        )
    }

    @Test
    fun replay_vd_jiejingConfirmed() {
        assertFixed(
            "接警示已确认报警人电话畅通现场地点初步为廊坊市广阳区万达广场附近工地围挡旁。",
            "接警时已确认报警人电话畅通现场地点初步为廊坊市广阳区万达广场附近工地围挡旁。",
        )
        assertFixed(
            "十七。五十六亿接警报警人补充是否存在违法行为事项，涉及疑似拉车门。",
            "十七。五十六已接警报警人补充是否存在违法行为事项，涉及疑似拉车门。",
        )
    }

    @Test
    fun replay_vd_round01_tsv_ifPresent() {
        val tsv = resolveVdRound01Tsv()
        if (!tsv.isFile) {
            println("[SKIP] vd round01 tsv not found: ${tsv.absolutePath}")
            return
        }
        replayTier(tsv, ::isVdP6Term, "vd-p6-zengpai", 0.80)
        replayTier(tsv, ::isVdChujingTerm, "vd-p2-chujing", 0.55)
        replayTier(tsv, ::isVdYiqianshouTerm, "vd-yiqianshou", 0.70)
        replayTier(tsv, ::isVdQianshouTerm, "vd-qianshou", 0.50)
        replayAllMissRows(tsv, 0.85)
    }

    private fun replayTier(
        tsv: File,
        termFilter: (String) -> Boolean,
        label: String,
        minRate: Double,
    ) {
        var missRows = 0
        var fixed = 0
        tsv.readLines().drop(1).forEach { line ->
            val cols = line.split('\t')
            if (cols.size < 8) return@forEach
            val raw = cols[4].trim()
            val miss = cols[7].trim()
            if (miss.isEmpty() || raw.isEmpty()) return@forEach
            val targetMiss = miss.split(',').map { it.trim() }.filter(termFilter)
            if (targetMiss.isEmpty()) return@forEach
            missRows++
            val norm = normalizer.normalize(raw).text
            val stillMiss = targetMiss.any { term -> term !in norm && term !in raw }
            if (!stillMiss) fixed++
        }
        val rate = if (missRows > 0) fixed.toDouble() / missRows else 1.0
        println("[vd replay] $label miss rows=$missRows fixed=$fixed (${"%.1f".format(rate * 100)}%)")
        assertTrue("$label should fix >= ${(minRate * 100).toInt()}% of tier misses", rate >= minRate)
    }

    private fun replayAllMissRows(tsv: File, minRate: Double) {
        var missRows = 0
        var fixed = 0
        tsv.readLines().drop(1).forEach { line ->
            val cols = line.split('\t')
            if (cols.size < 8) return@forEach
            val raw = cols[4].trim()
            val miss = cols[7].trim()
            if (miss.isEmpty() || raw.isEmpty()) return@forEach
            missRows++
            val norm = normalizer.normalize(raw).text
            val expected = cols[3].trim().split(',').map { it.trim() }.filter { it.isNotEmpty() }
            val stillMiss = expected.any { term -> term !in norm && term !in raw }
            if (!stillMiss) fixed++
        }
        val rate = if (missRows > 0) fixed.toDouble() / missRows else 1.0
        println("[vd replay] all-miss-rows=$missRows fixed=$fixed (${"%.1f".format(rate * 100)}%)")
        assertTrue("vd all miss rows should fix >= ${(minRate * 100).toInt()}%", rate >= minRate)
    }

    private fun isVdP6Term(term: String): Boolean = term == "增派警力"

    private fun isVdChujingTerm(term: String): Boolean =
        term.contains("处警") || term == "正在处警"

    private fun isVdYiqianshouTerm(term: String): Boolean =
        term.startsWith("已签收")

    private fun isVdQianshouTerm(term: String): Boolean =
        term.startsWith("签收") && !term.startsWith("已签收")

    private fun assertFixed(raw: String, expected: String) {
        assertEquals(expected, normalizer.normalize(raw).text)
    }

    private fun resolveVdRound01Tsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            val candidate = File(base, "asr/evaluation/police_terms/round01/vd_only_eval.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("asr/evaluation/police_terms/round01/vd_only_eval.tsv")
    }
}
