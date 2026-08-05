package com.amphion.police.terms

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * 20260727 新增指令：术语命中补洞 + V2 变长不得删虚词。
 */
class PoliceTermsRound10TermHitTest {

    private lateinit var v2: PoliceTermsNormalizerV2

    @Before
    fun setUp() {
        v2 = newV2()
    }

    @Test
    fun fixes_term_miss_patterns() {
        fun fix(raw: String, expected: String) {
            assertEquals(expected, v2.normalize(raw).text)
        }
        fix("现在打开帮把字段填上。", "现在打开帮填把字段填上。")
        fix(
            "打开警信发消息给刘队长内容，为今天几点集合？",
            "打开警信发消息给刘队长，内容为：今天几点集合？",
        )
        fix("用VCOOM向张伟发起呼叫。", "用WeCom向张伟发起呼叫。")
        fix("请用微COM向张伟发起呼叫。", "请用WeCom向张伟发起呼叫。")
        fix("现在帮我导航，去高新区软件园。", "现在帮我导航去高新区软件园。")
        fix("我已到场帮我反馈。", "我已到场，帮我反馈。")
        fix("请查看报案，现场视频核对经过。", "请查看报案现场视频核对经过。")
        fix("现场清场结束，盘查任务。", "现场清场，结束盘查任务。")
        fix(
            "帮我核查身份证号码为370 503 19911230983。",
            "帮我核查身份证，号码为：37050319911230983。",
        )
        fix(
            "核查身份证号370 503 19911230983。",
            "核查身份证号：37050319911230983。",
        )
        fix("帮我核查车牌号川AF60080。", "帮我核查车牌号：川A F60080。")
        assertEquals(
            "帮我核查车牌号：川A F60080。",
            v2.polish("帮我核查车牌号川AF60080。"),
        )
        // WeCom 大小写/截断变体
        fix("用VCOM向张伟发起呼叫。", "用WeCom向张伟发起呼叫。")
        fix("用VCOM想张伟发起呼叫。", "用WeCom向张伟发起呼叫。")
        fix("用Weconmm向张伟发起呼叫。", "用WeCom向张伟发起呼叫。")
        fix("用WeConmm向张伟发起呼叫。", "用WeCom向张伟发起呼叫。")
        fix("VCOM向张伟发起呼叫。", "WeCom向张伟发起呼叫。")
        fix("Weconmm向张伟发起呼叫。", "WeCom向张伟发起呼叫。")
    }

    @Test
    fun var_len_does_not_drop_leading_particles() {
        fun keep(raw: String) {
            assertEquals(raw, v2.normalize(raw).text)
        }
        keep("现在帮我打开时钟设个提醒。")
        keep("马上启动帮写功能，生成文本。")
        keep("请打开帮填功能，补全表单。")
        keep("请创建一个警单登记情况。")
    }

    private fun newV2(): PoliceTermsNormalizerV2 {
        fun reader(rel: String) =
            BufferedReader(InputStreamReader(TestAssets.resolve(rel).inputStream(), Charsets.UTF_8))
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
        )
    }

}
