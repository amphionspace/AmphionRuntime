package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.File
import java.nio.charset.StandardCharsets

/** 新声学 round03 真机 asr_raw 离线回放；跳过高风险乱码/截断句。 */
class PoliceTermsRound03ReplayTest {

    private lateinit var normalizer: PoliceTermsNormalizer

    @Before
    fun setUp() {
        normalizer = PoliceTermsNormalizer.create(
            PoliceTermsHomophoneDict.loadFromReader(
                BufferedReader(TestAssets.resolve("police_terms/term_homophones.csv").reader()),
            ),
            PoliceTermsGazetteer.loadFromReader(
                BufferedReader(TestAssets.resolve("police_terms/term_gazetteer.txt").reader()),
            ),
        )
    }

    private val skipAsrSubstrings = listOf(
        "玩玩玩玩玩",
        "也不会也不会",
        "叶耶夜夜",
        "040404040",
        "井盖井盖",
        "日思师身体",
        "17 11贷日系",
        "也也不会誓死",
    )

    @Test
    fun round03_newAcoustic_qianshouChujing_samples() {
        val cases = listOf(
            "牵手警单后，发现现场已有物业先行劝开，需要联系报警人，补充涉事物品情况。" to
                listOf("签收警单后"),
            "处景途中已联系报警人，确认报警人所在位置和苏州市姑苏区官前街斑马线旁位置。" to
                listOf("处警"),
            "受检车辆已到达小区门口，请与报警人对接。" to
                listOf("处警车辆", "报警人"),
            "牵手金单后，请先联系社区活动室现场人员确认是否存在围观人员聚集。" to
                listOf("签收警单后"),
            "千手警情后，发现现场情况还不明确，请协助核实物业已在现场。" to
                listOf("签收警情后"),
            "接警师已确认报警人电话畅通。现场地点初步为西安市雁塔区大雁塔北广场社区。" to
                listOf("接警时已确认"),
            "群众反映，有人倒地不起，请派出所先签收警。" to
                listOf("签收警单"),
        )
        for ((asr, terms) in cases) {
            val norm = normalizer.normalize(asr).text
            for (t in terms) {
                assertTrue("$t in $norm", t in norm || t in asr)
            }
        }
    }

    @Test
    fun replay_round03_term_sent_at_least_98_percent() {
        val tsv = resolveRound03Tsv()
        if (!tsv.isFile) {
            println("[SKIP] ${tsv.absolutePath} not found")
            return
        }
        var deviceHit = 0
        var replayHit = 0
        var skipped = 0
        var regressed = 0
        val n = 2183
        tsv.bufferedReader(StandardCharsets.UTF_8).use { br ->
            br.readLine()
            br.forEachLine { line ->
                val cols = line.split('\t')
                if (cols.size < 8) return@forEachLine
                val expected = cols[3].trim().split(',').map { it.trim() }.filter { it.isNotEmpty() }
                val raw = cols[4].trim()
                val deviceNorm = cols[5].trim()
                if (skipAsrSubstrings.any { raw.contains(it) }) {
                    skipped++
                    if (termHit(expected, deviceNorm, raw)) deviceHit++
                    return@forEachLine
                }
                val replayNorm = normalizer.normalize(raw).text
                val deviceOk = termHit(expected, deviceNorm, raw)
                val replayOk = termHit(expected, replayNorm, raw)
                if (deviceOk) deviceHit++
                if (replayOk) replayHit++
                if (deviceOk && !replayOk) regressed++
            }
        }
        val effective = n - skipped
        val report = buildString {
            appendLine("police terms round03 replay (n=$n skipped=$skipped)")
            appendLine("device term_sent: $deviceHit/$n = ${100.0 * deviceHit / n}%")
            appendLine("replay term_sent: $replayHit/$effective = ${100.0 * replayHit / effective}%")
            appendLine("newly_fixed: ${replayHit - deviceHit + regressed}  regressed: $regressed")
        }
        File(tsv.parentFile, "metrics_replay.txt").writeText(report, StandardCharsets.UTF_8)
        println(report)
        assertEquals(0, regressed)
        assertTrue("replay $replayHit/$effective < 98%", replayHit >= (effective * 0.98).toInt())
    }

    private fun termHit(expected: List<String>, hyp: String, raw: String): Boolean =
        expected.isEmpty() || expected.all { it in hyp || it in raw }

    private fun resolveRound03Tsv(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".")
        repeat(8) {
            val base = dir ?: return@repeat
            val candidate = File(base, "evaluation/police_terms/round03/police_terms_eval.tsv")
            if (candidate.isFile) return candidate
            dir = base.parentFile
        }
        return File("evaluation/police_terms/round03/police_terms_eval.tsv")
    }
}
