package com.amphion.asr.sample.police_station

/**
 * P3：整句标点与常见句尾/动词归一（提升整句完全匹配率，无 ref 的启发式）。
 */
internal object PoliceStationSentenceUtil {

    private val DATA_COMMA_BEFORE_AN = Regex("""接警数据，按(派警|日期|天分)""")
    private val JINGQING_DUOSHAO_Q = Regex("""接警多少[？?]$""")
    private val JINGQING_DUO_END = Regex("""接警多[。]?$""")
    private val JINGQING_SHU_END = Regex("""接警数[。]?$""")
    private val JINGQING_QINGKUANG_COMMA = Regex("""接警情况，""")

    fun polish(text: String): String = polishEnd(polishMid(text))

    /** P3 中段规则（FST 已覆盖时可跳过，由 [polishEnd] 收尾）。 */
    internal fun polishMid(text: String): String {
        var s = text.trim()
        if (s.isEmpty()) return s
        s = s.replace("麻烦和一下", "麻烦核一下")
            .replace("麻烦和", "麻烦核")
        s = DATA_COMMA_BEFORE_AN.replace(s, "接警数据按$1")
        s = JINGQING_QINGKUANG_COMMA.replace(s, "接警情况")
        return s
    }

    /** 句尾规则（FST 不含，留宿主；与 PC polish_end 一致）。 */
    internal fun polishEnd(text: String): String {
        var s = text
        s = JINGQING_DUOSHAO_Q.replace(s, "接警多少起。")
        s = JINGQING_DUO_END.replace(s, "接警多少起。")
        s = JINGQING_SHU_END.replace(s, "接警数据。")
        if (s.endsWith("？") || s.endsWith("?")) {
            s = s.dropLast(1) + "。"
        }
        if (!s.endsWith("。")) {
            s += "。"
        }
        return s
    }
}
