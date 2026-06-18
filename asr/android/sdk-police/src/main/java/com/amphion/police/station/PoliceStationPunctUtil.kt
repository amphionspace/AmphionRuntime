package com.amphion.police.station

/**
 * P2：行政链/所名内部顿号、逗号归一（评测集无「派出所，」用法）。
 */
internal object PoliceStationPunctUtil {

    private val ADMIN_DUNHAO = Regex("""([市区县])、""")
    private val STATION_COMMA = Regex("""派出所，""")
    /** ASR 常在「八廓，派出所」中间插入逗号（非「派出所，」）。 */
    private val COMMA_BEFORE_STATION = Regex("""，派出所""")
    private val SUMMARY_COMMA = Regex("""(汇总|统计|导出|整理)，""")

    fun normalizeAdminPunct(text: String): String {
        var s = text
        s = ADMIN_DUNHAO.replace(s, "$1")
        s = STATION_COMMA.replace(s, "派出所")
        s = COMMA_BEFORE_STATION.replace(s, "派出所")
        s = SUMMARY_COMMA.replace(s, "$1")
        return s
    }
}
