package com.amphion.police.terms

/** 整句中识别到的警务术语片段。 */
data class PoliceTermsSpan(
    val start: Int,
    val end: Int,
    val raw: String,
    val normalized: String,
    val valid: Boolean,
)

/** [PoliceTermsNormalizer] 的输出。 */
data class PoliceTermsNormalizeResult(
    val text: String,
    val spans: List<PoliceTermsSpan>,
) {
    val matchedTerms: List<String>
        get() = spans.filter { it.valid }.map { it.normalized }.distinct()
}
