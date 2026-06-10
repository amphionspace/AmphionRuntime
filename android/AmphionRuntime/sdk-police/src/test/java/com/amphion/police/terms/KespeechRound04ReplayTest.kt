package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File

/** Round04 KeSpeech：Round02 FST 残留 ASR 误识回放。 */
class KespeechRound04ReplayTest {

    private lateinit var normalizer: PoliceTermsNormalizer

    @Before
    fun setUp() {
        normalizer = PoliceTermsNormalizer.create(
            loadProductionHomophones(),
            loadProductionGazetteer(),
            fstRuntime = null,
        )
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
    fun replay_r04_qianshoujingqinghou() {
        assertFixed(
            "全球警情后发现，双方仍在争执，请协助核实，对方暂时联系不上。",
            "签收警情后发现，双方仍在争执，请协助核实，对方暂时联系不上。",
        )
        assertFixed(
            "前手敬请后发现报警人描述比较模糊，需要现场核查。",
            "签收警情后发现报警人描述比较模糊，需要现场核查。",
        )
    }

    @Test
    fun replay_r04_yiqianshouTruncation() {
        assertFixed(
            "巡逻组已签收。 前往出租车上客点何时租房纠纷？",
            "巡逻组已签收警单，正在前往出租车上客点何时租房纠纷？",
        )
        assertFixed(
            "已签收。 目前正在联系报警人确认监控点位，现场状态为双方仍在争执。",
            "已签收警情，目前正在联系报警人确认监控点位，现场状态为双方仍在争执。",
        )
    }

    @Test
    fun replay_r04_jingliAndJiejing() {
        assertFixed(
            "接警台记录了楼道灯箱线索，后续有年轻警力核实物业联系方式。",
            "接警台记录了楼道灯箱线索，后续由联勤警力核实物业联系方式。",
        )
        assertFixed(
            "警情时已确认报警人电话畅通。现场地点初步为南京市玄武区新街口商圈社区活动室。",
            "接警时已确认报警人电话畅通。现场地点初步为南京市玄武区新街口商圈社区活动室。",
        )
        assertFixed(
            "借进信息显示，报警人位于昆明市五华区翠湖公园东门，需核实车辆停放方向和报警人不方便离开现场。",
            "接警信息显示，报警人位于昆明市五华区翠湖公园东门，需核实车辆停放方向和报警人不方便离开现场。",
        )
    }

    @Test
    fun replay_r04_chujingSplit() {
        assertFixed(
            "就近警力到达现场处，警正在处。 并核对现场人数。",
            "就近警力到达现场处警，正在处理。 并核对现场人数。",
        )
        assertFixed(
            "处中已联系报警人，确认报警人所在位置和海口市龙华区骑楼老街公交车厢内位置。",
            "处警途中已联系报警人，确认报警人所在位置和海口市龙华区骑楼老街公交车厢内位置。",
        )
    }

    @Test
    fun replay_round02_tsv_ifPresent() {
        val tsv = resolveRound02Tsv()
        if (!tsv.isFile) {
            println("[SKIP] round02 tsv not found: ${tsv.absolutePath}")
            return
        }
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
        println("[round04 replay] round02 miss rows=$missRows fixed=$fixed (${"%.1f".format(rate * 100)}%)")
        assertTrue("round04 should fix >= 75% of round02 miss rows", rate >= 0.75)
    }

    private fun assertFixed(raw: String, expected: String) {
        assertEquals(expected, normalizer.normalize(raw).text)
    }

    private fun resolveRound02Tsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            val candidate = File(base, "evaluation/police_terms/round02/police_terms_eval.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("evaluation/police_terms/round02/police_terms_eval.tsv")
    }
}
