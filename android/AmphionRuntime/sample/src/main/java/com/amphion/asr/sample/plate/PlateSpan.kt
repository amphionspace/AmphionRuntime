package com.amphion.asr.sample.plate

/**
 * 在整句里识别到的一段车牌候选。
 *
 * @property start 在原文中的起始下标（含）
 * @property end 在原文中的结束下标（不含）
 * @property raw 原文切片
 * @property normalized 规范化后的车牌；校验失败时与 [raw] 去空格大写结果相同或仍为无效串
 * @property valid 是否通过国标车牌严格正则
 */
data class PlateSpan(
    val start: Int,
    val end: Int,
    val raw: String,
    val normalized: String,
    val valid: Boolean,
)

/**
 * [PlateNormalizer] 的输出。
 */
data class PlateNormalizeResult(
    val text: String,
    val spans: List<PlateSpan>,
) {
    /** 第一个通过校验的车牌；无则 null。 */
    val primaryPlate: String?
        get() = spans.firstOrNull { it.valid }?.normalized
}
