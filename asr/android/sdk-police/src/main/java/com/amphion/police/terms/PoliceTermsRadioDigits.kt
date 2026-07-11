package com.amphion.police.terms

/**
 * 电台音标数字归一（Phase 2，20260711 批「特殊代码」）。
 *
 * 映射：洞0 幺1 两2 三3 四4 五5 六6 拐7 八8 勾/钩9。
 *
 * **只在「数字码上下文」里转换**，严格门控避免误伤日常词（一两个 / 拐弯 / 三四天 / 5栋楼 / 做动作 / 桥梁）：
 * 分三档字：
 *  - 强字 [STRONG]（洞幺拐勾钩）：电台专用，日常极少数字外出现；
 *  - 弱字 [WEAK]（两三四五六八）：常用数词，仅在已被强字/阿拉伯数字锚定的码段里才转；
 *  - 误听字 [MISHEAR]（栋→0 动→0 梁→2）：ASR 对 洞/两 的高频误识，仅在**含 ≥3 个阿拉伯数字**的码段里才转
 *    （保护「5栋楼」「第3栋」「做动作」「桥梁」——这些码段阿拉伯数字不足 3）。
 *
 * 「码段」= 由 {阿拉伯数字 ∪ 强/弱/误听字} 组成的极大连续子串。整段满足下列**任一**才判定为码并转换：
 *  1) 阿拉伯数字数 + 强字数 ≥ 2；或
 *  2) 含 ≥1 强字 且 段长 ≥ 3（覆盖纯电台串「幺两三四五」，即便上游 ITN 没转）。
 */
internal object PoliceTermsRadioDigits {

    private val STRONG = mapOf('洞' to '0', '幺' to '1', '拐' to '7', '勾' to '9', '钩' to '9')
    // 弱字：常用数词 + 电台强字的常见同音误听（沟≈勾、腰/撩≈幺）。仅在码段被强字/数字锚定时才转，
    // 故「沟通」「弯腰」「撩起」等孤立出现不受影响（见单测 does_not_corrupt_everyday_words）。
    private val WEAK = mapOf(
        '两' to '2', '三' to '3', '四' to '4', '五' to '5', '六' to '6', '八' to '8',
        '沟' to '9', '腰' to '1', '撩' to '1',
    )
    private val MISHEAR = mapOf('栋' to '0', '动' to '0', '梁' to '2')

    private fun isArabic(c: Char) = c in '0'..'9'
    private fun isConvertible(c: Char) =
        isArabic(c) || c in STRONG || c in WEAK || c in MISHEAR

    fun normalize(text: String): String {
        if (text.isEmpty()) return text
        val sb = StringBuilder(text.length)
        var i = 0
        val n = text.length
        while (i < n) {
            if (!isConvertible(text[i])) {
                sb.append(text[i]); i++; continue
            }
            // 抓极大码段
            var j = i
            while (j < n && isConvertible(text[j])) j++
            val seg = text.substring(i, j)
            sb.append(convertSegment(seg))
            i = j
        }
        return sb.toString()
    }

    private fun convertSegment(seg: String): String {
        var arabic = 0
        var strong = 0
        for (c in seg) {
            if (isArabic(c)) arabic++
            else if (c in STRONG) strong++
        }
        val qualifies = (arabic + strong >= 2) || (strong >= 1 && seg.length >= 3)
        if (!qualifies) return seg

        val allowMishear = arabic >= 3
        val out = StringBuilder(seg.length)
        for (c in seg) {
            val mapped = when {
                isArabic(c) -> c
                c in STRONG -> STRONG.getValue(c)
                c in WEAK -> WEAK.getValue(c)
                c in MISHEAR -> if (allowMishear) MISHEAR.getValue(c) else c
                else -> c
            }
            out.append(mapped)
        }
        return out.toString()
    }
}
