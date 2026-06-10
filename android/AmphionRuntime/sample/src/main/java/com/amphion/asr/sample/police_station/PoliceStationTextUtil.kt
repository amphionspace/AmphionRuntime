package com.amphion.asr.sample.police_station

/**
 * 从参考句式提取标准派出所名（与 evaluation/police_station 分析脚本口径一致）。
 */
object PoliceStationTextUtil {

    /**
     * 从 [text] 中「派出所」前的片段剥掉动词/指令前缀，得到期望所名。
     * 长短语在前，避免「汇总一下」被拆成「汇总」+「一下」留下脏前缀。
     */
    private val DELIMITERS = listOf(
        "麻烦汇总一下", "帮忙汇总一下", "麻烦统计一下", "帮忙统计一下",
        "麻烦整理一下", "帮忙整理一下", "麻烦导出一下", "帮忙导出一下",
        "麻烦核对一下", "麻烦核实一下", "麻烦核查一下",
        "对比一下", "看一下", "查一下", "给我看一下", "给我拉一下",
        "整理一下", "汇总一下", "统计一下", "导出一下",
        "麻烦汇总", "帮忙汇总", "麻烦统计", "帮忙统计",
        "麻烦整理", "帮忙整理", "麻烦导出", "帮忙导出",
        "麻烦查一下", "帮我查一下", "帮忙查一下", "帮忙看看",
        "看看", "一下", "帮我", "帮忙", "麻烦", "请把", "给我", "把",
        "查", "看", "核", "拉", "对", "请",
        "汇总", "统计", "导出", "整理", "对比", "核对", "核实", "核查",
    )

    /** 从参考句 [text] 提取期望派出所名（…派出所）。 */
    fun extractStation(text: String): String {
        val idx = text.indexOf("派出所")
        if (idx < 0) return ""
        val start = (idx - 32).coerceAtLeast(0)
        var chunk = text.substring(start, idx + 3)
        for (d in DELIMITERS.sortedByDescending { it.length }) {
            val p = chunk.lastIndexOf(d)
            if (p >= 0) {
                chunk = chunk.substring(p + d.length)
            }
        }
        return chunk.trim()
    }
}
