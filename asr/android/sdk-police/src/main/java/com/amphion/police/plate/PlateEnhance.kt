package com.amphion.police.plate

/**
 * 车牌增强后处理：在 SDK 已对 final 做过 ITN 之后，可选执行 [PlateNormalizer]。
 */
object PlateEnhance {

    fun apply(
        asrFinalText: String,
        normalizer: PlateNormalizer,
        normalizeEnabled: Boolean,
    ): PlateNormalizeResult {
        if (!normalizeEnabled || asrFinalText.isEmpty()) {
            return PlateNormalizeResult(asrFinalText, emptyList())
        }
        return normalizer.normalize(asrFinalText)
    }
}
