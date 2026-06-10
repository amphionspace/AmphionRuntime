package com.amphion.police.station

/**
 * P4：识别端侧解码崩溃/乱码，跳过后处理以免放大噪声。
 */
object PoliceStationDecodeGuard {

    private val GIBBERISH = Regex(
        """[A-Za-z]{4,}|TWIG|NOISE|滚滚滚|呜呜|嗯嗯嗯|帮我帮我|汇总会汇|通通控控""",
    )

    /** 文本是否像解码崩溃（乱码、极短且无派出所、CJK 占比过低等）。 */
    fun isDecodeCollapse(text: String): Boolean {
        val t = text.trim()
        if (t.isEmpty()) return true
        if (GIBBERISH.containsMatchIn(t)) return true
        if (!t.contains("派出所") && t.length < 12) return true
        val cjk = t.count { it in '\u4e00'..'\u9fff' }
        if (t.length >= 20 && cjk.toFloat() / t.length < 0.45f) return true
        return false
    }
}
