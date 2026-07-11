package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 真人复测残留验证：把 20260711 真人录音的 ASR 原文喂进**更新后的 V2**，看 Phase 3b 分层修复
 * （长词等长近音走模糊层 + 短词无碰撞全局 homophone）能纠回哪些。
 *
 * 数据 = round5_human 里与念稿内容对齐的 mic 行 asr_raw + 目标词。
 */
class PoliceTermsHumanResidualTest {

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

    // (人声 asr_raw, 主目标词) —— 真人也念错的 37 条残留
    private val residuals = listOf(
        "两名民警赶去出警。" to "处警",
        "接警员记录了报案内容。" to "报警",
        "硝胺要有相关手续。" to "销案",
        "技术人员正在现场勘。" to "现场勘查",
        "民警对他进行了讯问。" to "询问",
        "晋黄查处了几家场所。" to "禁黄",
        "参加质报专项检查。" to "治爆",
        "公安机关开展技枪行动。" to "缉枪",
        "机枪自爆同步推进。" to "治爆",
        "牢记四句话，16字总要求。" to "四句话十六字",
        "学习四句话，16字方针。" to "四句话十六字",
        "网真提供了重要线索。" to "网侦",
        "讯问笔录要本人签字。" to "询问笔录",
        "他申请恢复。" to "恢复户口",
        "所里设了毛条。" to "矛调",
        "家庭矛盾要及时疏。" to "疏导",
        "调解的目的是定分值征。" to "定纷止争",
        "定分指针要靠法。" to "定纷止争",
        "实现吸塑霸坊。" to "息诉罢访",
        "西素霸坊是最终目标。" to "息诉罢访",
        "努力避免民转。" to "避免民转刑",
        "做好防暴工作。" to "防盗",
        "防暴宣传进社。" to "防盗",
        "民警在路口交通疏散。" to "交通疏导",
        "警情按类别分留。" to "分流",
        "沪证业务可以网上。" to "户政",
        "规范接触井流程。" to "接处警流程",
        "接触井流程要人人熟悉。" to "接处警流程",
        "这是一级出警。" to "一级处警",
        "实行分类处。" to "分类处警",
        "持续开展制爆机枪。" to "治爆缉枪",
        "制爆机枪成效显。" to "治爆缉枪",
        "配备执法侦察装备。" to "执法侦查装备",
        "执法侦察装备已到位。" to "执法侦查装备",
        "带上现场勘。" to "现场勘查箱",
        "现场勘查乡里有工具。" to "现场勘查箱",
        "景增系统正在维护。" to "警综",
    )

    // Phase 3b 明确加了规则、应当纠回的（其余为硬残留/掉字/ITN，不在断言内）
    private val mustRecover = setOf(
        "硝胺要有相关手续。",
        "晋黄查处了几家场所。",
        "调解的目的是定分值征。",
        "定分指针要靠法。",
        "实现吸塑霸坊。",
        "西素霸坊是最终目标。",
        "规范接触井流程。",
        "接触井流程要人人熟悉。",
        "持续开展制爆机枪。",
        "制爆机枪成效显。",
        "沪证业务可以网上。",
        "景增系统正在维护。",
    )

    @Test
    fun phase3b_recovers_expected_residuals() {
        val n = v2()
        var recovered = 0
        val failedMust = mutableListOf<String>()
        for ((raw, tgt) in residuals) {
            val out = n.normalize(raw).text
            val hit = out.contains(tgt)
            if (hit) recovered++
            println("${if (hit) "✅" else "❌"} 目标=$tgt  in: $raw  out: $out")
            if (raw in mustRecover && !hit) failedMust.add("$raw -> $out (缺 $tgt)")
        }
        println("\n真人残留 ${residuals.size} 条中，更新后 V2 纠回 $recovered 条")
        assertTrue("以下应纠回但未纠回:\n" + failedMust.joinToString("\n"), failedMust.isEmpty())
    }
}
