package com.amphion.police.terms

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 电台数字归一单测：既要转对码段，也要**不误伤日常词**（门控回归）。
 * 输入取自 20260711「特殊代码」真机 asr_raw（含 ITN 半转 + 洞/两 误听为 栋/动/梁）。
 */
class PoliceTermsRadioDigitsTest {

    private fun norm(s: String) = PoliceTermsRadioDigits.normalize(s)

    @Test
    fun converts_radio_codes_in_digit_context() {
        // 强字 勾/洞 + ITN 半转数字
        assertEquals("设备序列号67890后", norm("设备序列号678勾洞后"))
        // 勾→9 + 误听 栋→0（段含 4 位阿拉伯数字）
        assertEquals("密码943210", norm("密码勾4321栋"))
        // 误听 动→0（前导）
        assertEquals("前五位是01234", norm("前五位是动1234"))
        // 误听 栋→0（尾号）
        assertEquals("尾号567890", norm("尾号56789栋"))
        // 弱字 八 + 误听 栋→0
        assertEquals("编号806521后", norm("编号八栋6521后"))
        // 误听 梁→2 + 勾→9 + 栋→0
        assertEquals("后六位758920", norm("后六位758勾梁栋"))
        // 纯电台串（上游未 ITN 也能救）
        assertEquals("编号12345请", norm("编号幺两三四五请"))
        // 已正确的阿拉伯数字不动
        assertEquals("临时码00176有效", norm("临时码00176有效"))
        // 强字锚定下，同音误听 沟(勾)/腰·撩(幺) 也转（真人复测：拐沟洞腰两 / 拐勾洞撩两 → 79012）
        assertEquals("呼号79012重复", norm("呼号拐沟洞腰两重复"))
        assertEquals("呼号79012重复", norm("呼号拐勾洞撩两重复"))
    }

    @Test
    fun does_not_corrupt_everyday_words() {
        // 弱字无锚点：一两个 / 三四天 / 两三下
        assertEquals("来了一两个人", norm("来了一两个人"))
        assertEquals("过三四天再说", norm("过三四天再说"))
        assertEquals("等两三下就好", norm("等两三下就好"))
        // 强字无锚点：拐弯
        assertEquals("前面拐弯就到", norm("前面拐弯就到"))
        // 误听字：楼栋/动作/桥梁（阿拉伯数字不足 3，不转）
        assertEquals("住在5栋楼", norm("住在5栋楼"))
        assertEquals("第3栋在东边", norm("第3栋在东边"))
        assertEquals("赶紧做动作", norm("赶紧做动作"))
        assertEquals("桥梁很结实", norm("桥梁很结实"))
        assertEquals("20栋居民楼", norm("20栋居民楼"))
        // 弱字单独出现（六月/第三）
        assertEquals("六月的第三周", norm("六月的第三周"))
        // 同音误听字孤立出现（沟/腰/撩 无强字锚定）不得转
        assertEquals("加强沟通协调", norm("加强沟通协调"))
        assertEquals("弯腰捡起东西", norm("弯腰捡起东西"))
        assertEquals("撩起袖子干活", norm("撩起袖子干活"))
        assertEquals("那道山沟很深", norm("那道山沟很深"))
    }
}
