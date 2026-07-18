package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 新声学模型（bundle 20260718）适配验证：real-device asr_raw 回放。
 *
 * 换新声学模型后，App 专名出现一批**新的**同音误识串（旧模型没有这些误识）。
 * 下面正例的 raw 全部取自三星真机新模型批量评测的 asr_raw 原文（非构造），
 * 断言 V2 后处理能把甲方目标词纠回；负例保证新增映射不误伤通用句。
 */
class PoliceTermsNewModel0718Test {

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
    fun recovers_new_model_appname_misrecognitions() {
        val n = v2()
        // raw(真机新模型 asr_raw) to 甲方目标词
        val cases = listOf(
            "用易警宝处理事故。" to "e警保",            // appname_0030
            "宜简宝可以拍照上传。" to "e警保",          // appname_0031
            "仅仅智联可以免密登录。" to "京警智联",      // appname_0060
            "在轻质星平台上查警情情。" to "情指行平台",   // appname_0057
            "停止晴平台在维护。" to "勤指情平台",        // appname_0045
            "打开指信接触。" to "指信接处警",           // appname_0022
            "规范接触景流程。" to "接处警流程",          // vocab_1382
            "接触景流程要人人熟悉。" to "接处警流程",     // vocab_1383
            // 停止行 走上下文护栏（前有 App 语境词 平台/下发指令）
            "停止行平台下发指令。" to "情指行平台",       // appname_0056
        )
        for ((raw, tgt) in cases) {
            val out = n.normalize(raw).text
            println("目标=$tgt  in: $raw  out: $out")
            assertTrue("应纠回 $tgt: $out", out.contains(tgt))
        }
    }

    @Test
    fun recovers_new_model_human_retest_residual() {
        val n = v2()
        // raw 取自真人真机复测的 normalized 残留误识（短词硬伤里可安全规则化的 4 条）
        val cases = listOf(
            "秦子晴平台调度警力。" to "勤指情平台",   // appname_0044
            "所里设了毛条室。" to "矛调",            // vocab_0667
            "调解的目的是定分指征。" to "定纷止争",    // vocab_0914
            "网真提供了重要线索。" to "网侦",         // vocab_0389
        )
        for ((raw, tgt) in cases) {
            val out = n.normalize(raw).text
            println("目标=$tgt  in: $raw  out: $out")
            assertTrue("应纠回 $tgt: $out", out.contains(tgt))
        }
    }

    @Test
    fun recovers_new_model_human_retest_round2() {
        val n = v2()
        val cases = listOf(
            "悉宿霸坊是最终目标。" to "息诉罢访",     // vocab_0997(真人)
            "制报工作要落实到位。" to "治爆",         // vocab_0198
            "参加制报专项检查。" to "治爆",           // vocab_0199
            "即强制暴同步推。" to "缉枪治爆",         // vocab_0201(真人)
            "登陆移动警务门户。" to "登录移动警务门户", // appname_0012(真人)
        )
        for ((raw, tgt) in cases) {
            val out = n.normalize(raw).text
            println("目标=$tgt  in: $raw  out: $out")
            assertTrue("应纠回 $tgt: $out", out.contains(tgt))
        }
    }

    @Test
    fun does_not_touch_generic_phrases() {
        val n = v2()
        // 停止行 + 碰撞后继字：通用句，不得纠成 情指行
        for (s in listOf("请立即停止行动。", "他停止行为了。", "车辆停止行驶。")) {
            val out = n.normalize(s).text
            assertFalse("不得误纠 情指行: $s -> $out", out.contains("情指行"))
        }
        // 仅仅 / 轻质 / 接触 单独出现：不得触发专名映射
        assertFalse(n.normalize("这仅仅是一次演练。").text.contains("京警智联"))
        assertFalse(n.normalize("轻质油要单独存放。").text.contains("情指行"))
        assertFalse(n.normalize("现场接触景点游客。").text.contains("接处警"))
        assertFalse(n.normalize("停止晴天作业。").text.contains("勤指情"))
        // 网真 只在「网真提供」锚下纠正，通用「互联网真的」不得误伤
        assertFalse(n.normalize("互联网真的很方便。").text.contains("网侦"))
        // 毛条 单独（无 室 锚）不得纠成 矛调
        assertFalse(n.normalize("毛条要单独存放。").text.contains("矛调"))
        // 登陆 通用义（作战/沿海）不得纠成 登录
        assertFalse(n.normalize("台风即将登陆沿海地区。").text.contains("登录"))
        assertFalse(n.normalize("抢滩登陆作战演习。").text.contains("登录"))
        // 制报 仅带 工作/专项 锚才纠；编制报告/控制报警 等通用词不得纠成 治爆
        assertFalse(n.normalize("编制报告要按时完成。").text.contains("治爆"))
        assertFalse(n.normalize("控制报警器已安装。").text.contains("治爆"))
    }
}
