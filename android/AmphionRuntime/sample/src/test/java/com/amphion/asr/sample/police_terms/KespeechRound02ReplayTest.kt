package com.amphion.asr.sample.police_terms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File

/** Round02/03 KeSpeech：P0-P5 典型 ASR 误识回放 + partial TSV 离线验证。 */
class KespeechRound02ReplayTest {

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

    private fun locateAsset(name: String): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(6) {
            val base = dir ?: return@repeat
            val f = File(base, "sample/src/main/assets/police_terms/$name")
            if (f.isFile) return f
            dir = base.parentFile
        }
        error("$name not found from user.dir")
    }

    @Test
    fun replay_p0_orderToJingdan() {
        assertFixed(
            "巡逻组已签收订单正在前往充电桩区域，核实可疑人员徘徊。",
            "巡逻组已签收警单正在前往充电桩区域，核实可疑人员徘徊。",
        )
        assertFixed(
            "签收订单后，请先联系工地围挡旁现场人员，确认是否存在情绪激动。",
            "签收警单后，请先联系工地围挡旁现场人员，确认是否存在情绪激动。",
        )
    }

    @Test
    fun replay_p1_jingdanNearHomophones() {
        assertFixed(
            "路面纠纷简单，已推送请附近警力签收警单。",
            "路面纠纷警单，已推送请附近警力签收警单。",
        )
        assertFixed(
            "签收进单后，发现现场情况还不明确，需要联系报警人补充涉事物品情况。",
            "签收警单后，发现现场情况还不明确，需要联系报警人补充涉事物品情况。",
        )
        assertFixed(
            "巡逻组已签收金单正在前往出租车上客点何时租房纠纷？",
            "巡逻组已签收警单正在前往出租车上客点何时租房纠纷？",
        )
    }

    @Test
    fun replay_p2_chujingVsChujing() {
        assertFixed(
            "请出警人员到场后，先核实现场交通拥堵情况，再反馈现场是否仍有争执。",
            "请处警人员到场后，先核实现场交通拥堵情况，再反馈现场是否仍有争执。",
        )
        assertFixed(
            "促进过程中发现报警人和对方是邻居，正在做双方工作。",
            "处警过程中发现报警人和对方是邻居，正在做双方工作。",
        )
    }

    @Test
    fun replay_p3_jiejingNearHomophones() {
        assertFixed(
            "基金登记完成后，我们会按流程派发给属地单位。",
            "接警登记完成后，我们会按流程派发给属地单位。",
        )
        assertFixed(
            "基金信息显示，报警人位于武汉市江汉区江汉路步行街需何时门店名称和现场有老人需要召。",
            "接警信息显示，报警人位于武汉市江汉区江汉路步行街需何时门店名称和现场有老人需要召。",
        )
        assertFixed(
            "借警台记录了婴儿车线索，后续由处置小组核实涉事车辆颜色。",
            "接警台记录了婴儿车线索，后续由处置小组核实涉事车辆颜色。",
        )
        assertFixed(
            "二十一点三十三分以接警报警人补充报警人所在位置事项涉及楼上漏水争议。",
            "二十一点三十三分已接警报警人补充报警人所在位置事项涉及楼上漏水争议。",
        )
    }

    @Test
    fun replay_p4_baojingrenSplit() {
        assertFixed(
            "我们正在处警，请报警，人先在原地等候。",
            "我们正在处警，请报警人先在原地等候。",
        )
        assertFixed(
            "接警员反馈报警，人称有人敲门骚扰，请辖区注意核。",
            "接警员反馈报警人称有人敲门骚扰，请辖区注意核。",
        )
        assertFixed(
            "签收警情后，请关注婴儿车相关线索报警，人称车辆暂时无法移动。",
            "签收警情后，请关注婴儿车相关线索报警人称车辆暂时无法移动。",
        )
    }

    @Test
    fun replay_p5_jiemianPatrolGroup() {
        assertFixed(
            "请介面巡逻组签收简单报警人正在乌鲁木齐市天山区人民广场夜市摊位旁等候。",
            "请街面巡逻组签收警单报警人正在乌鲁木齐市天山区人民广场夜市摊位旁等候。",
        )
        assertFixed(
            "见面巡逻组到达现场，处警，正在处理共享单车栈道，并核对双方关系。",
            "街面巡逻组到达现场，处警，正在处理共享单车栈道，并核对双方关系。",
        )
        assertFixed(
            "接警台记录了收费盗闸线索，后续由接免巡逻组核实具体位置。",
            "接警台记录了收费盗闸线索，后续由街面巡逻组核实具体位置。",
        )
    }

    @Test
    fun replay_p0p2_round02c_uplift() {
        assertFixed(
            "该警单仍未确认，请值班人员完成签收，简单操作，并注意车辆漏油风险。",
            "该警单仍未确认，请值班人员完成签收警单操作，并注意车辆漏油风险。",
        )
        assertFixed(
            "辖区派出所一签收订单，你先开展登记备案，并回传门店名称。",
            "辖区派出所已签收警单，你先开展登记备案，并回传门店名称。",
        )
        assertFixed(
            "前收精南后，请备注初置后，请及时反馈，便于后续处置回填。",
            "签收警单后，请备注初置后，请及时反馈，便于后续处置回填。",
        )
        assertFixed(
            "十三点五十正在出京现场通道被临时占用，请后续保持联系。",
            "十三点五十正在处警现场通道被临时占用，请后续保持联系。",
        )
    }

    @Test
    fun replay_kespeech_partial_tsv_ifPresent() {
        val tsv = resolveKespeechPartialTsv()
        if (!tsv.isFile) {
            println("[SKIP] kespeech partial tsv not found: ${tsv.absolutePath}")
            return
        }
        replayTier(tsv, ::isP0P1P2Term, "p0-p2", 0.78)
        replayTier(tsv, ::isP3Term, "p3", 0.35)
        replayTier(tsv, ::isP4Term, "p4", 0.45)
        replayTier(tsv, ::isP5Term, "p5", 0.50)
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
        println("[kespeech replay] $label miss rows=$missRows fixed=$fixed (${"%.1f".format(rate * 100)}%)")
        assertTrue("$label should fix >= ${(minRate * 100).toInt()}% of tier misses", rate >= minRate)
    }

    private fun isP0P1P2Term(term: String): Boolean =
        term.contains("警单") || term.contains("处警")

    private fun isP3Term(term: String): Boolean =
        term.contains("接警")

    private fun isP4Term(term: String): Boolean =
        term == "报警人"

    private fun isP5Term(term: String): Boolean =
        term.contains("街面巡逻组") || term.contains("巡逻组")

    private fun assertFixed(raw: String, expected: String) {
        assertEquals(expected, normalizer.normalize(raw).text)
    }

    private fun resolveKespeechPartialTsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(6) {
            val base = dir ?: return@repeat
            val candidate = File(base, "evaluation/police_terms/round01_partial/kespeech_only_eval.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("evaluation/police_terms/round01_partial/kespeech_only_eval.tsv")
    }
}
