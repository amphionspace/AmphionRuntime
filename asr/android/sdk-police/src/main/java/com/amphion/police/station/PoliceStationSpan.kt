package com.amphion.police.station

/**
 * 在整句里识别到的一段派出所名称候选。
 */
data class PoliceStationSpan(
    val start: Int,
    val end: Int,
    val raw: String,
    val normalized: String,
    val valid: Boolean,
)

/** [PoliceStationNormalizer] 的输出。 */
data class PoliceStationNormalizeResult(
    val text: String,
    val spans: List<PoliceStationSpan>,
    /** P4：解码崩溃时跳过归一，保留原文。 */
    val decodeCollapse: Boolean = false,
) {
    /** 第一个通过 gazetteer 校验的派出所名；无则 null。 */
    val primaryStation: String?
        get() = spans.firstOrNull { it.valid }?.normalized
}
