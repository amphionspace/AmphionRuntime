package com.amphion.police.station

/**
 * 派出所增强后处理：在 SDK 已对 final 做过 ITN 之后，可选执行 [PoliceStationNormalizer]。
 */
object PoliceStationEnhance {

    fun apply(
        asrFinalText: String,
        normalizer: PoliceStationNormalizer,
        normalizeEnabled: Boolean,
    ): PoliceStationNormalizeResult {
        if (!normalizeEnabled || asrFinalText.isEmpty()) {
            return PoliceStationNormalizeResult(asrFinalText, emptyList())
        }
        return normalizer.normalize(asrFinalText)
    }
}
