package com.amphion.police.terms

/**
 * 客户端到场回报只归一句首（或前接标点/空白）的主语，避免术语流水线重复执行时不断补「我」。
 * 不做通用重复字清理，例如「我我觉得已经到达现场」应保持原文。
 */
internal object PoliceTermsArrivalGuard {
    private val PREFIX = Regex("(^|[，。！？!?；;、,\\s])我*已到达现场")

    fun apply(text: String): String = PREFIX.replace(text) { match ->
        "${match.groupValues[1]}我已到达现场"
    }
}
