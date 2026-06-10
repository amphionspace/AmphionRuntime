package com.amphion.police.terms

/**
 * 从参考句提取期望警务术语（与 evaluation/police_terms 分析脚本口径一致）。
 */
object PoliceTermsTextUtil {

    /** 在 [text] 中按 gazetteer 最长匹配、从左到右非重叠抽取术语。 */
    fun extractTerms(text: String, gazetteer: PoliceTermsGazetteer): List<String> {
        if (text.isEmpty()) return emptyList()
        val found = mutableListOf<String>()
        var i = 0
        while (i < text.length) {
            val term = gazetteer.findLongestAt(text, i)
            if (term != null) {
                found.add(term)
                i += term.length
            } else {
                i++
            }
        }
        return found
    }

    /** 检查 [hyp] 是否包含 [expectedTerms] 中的全部术语。 */
    fun allTermsHit(expectedTerms: List<String>, hyp: String): Boolean {
        if (expectedTerms.isEmpty()) return true
        return expectedTerms.all { hyp.contains(it) }
    }

    fun missedTerms(expectedTerms: List<String>, hyp: String): List<String> =
        expectedTerms.filter { !hyp.contains(it) }
}
