package com.amphion.police.terms

/**
 * 警务术语增强后处理：在 SDK 已对 final 做过 ITN 之后，可选执行 [PoliceTermsNormalizer]。
 */
object PoliceTermsEnhance {

    fun apply(
        asrFinalText: String,
        normalizer: PoliceTermsNormalizer,
        normalizeEnabled: Boolean,
    ): PoliceTermsNormalizeResult {
        if (!normalizeEnabled || asrFinalText.isEmpty()) {
            return PoliceTermsNormalizeResult(asrFinalText, emptyList())
        }
        return normalizer.normalize(asrFinalText)
    }
}
