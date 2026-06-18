package com.amphion.police.terms

import android.content.Context

/**
 * 警用 ASR final 文本的术语后处理：谐音替换 → gazetteer 最长匹配 → 记录 span。
 *
 * 方案 A：[useFst]=true 时 global 谐音走 FST，gazetteer 仍在 Kotlin 宿主。
 */
class PoliceTermsNormalizer private constructor(
    private val homophones: PoliceTermsHomophoneDict,
    private val gazetteer: PoliceTermsGazetteer,
    private val fstRuntime: PoliceTermsFstRuntime?,
) : AutoCloseable {

    companion object {
        fun create(context: Context, useFst: Boolean = false): PoliceTermsNormalizer =
            PoliceTermsNormalizer(
                PoliceTermsHomophoneDict.load(context),
                PoliceTermsGazetteer.load(context),
                fstRuntime = if (useFst) PoliceTermsFstRuntime.create(context) else null,
            )

        internal fun create(
            homophones: PoliceTermsHomophoneDict,
            gazetteer: PoliceTermsGazetteer,
            fstRuntime: PoliceTermsFstRuntime? = null,
        ): PoliceTermsNormalizer = PoliceTermsNormalizer(homophones, gazetteer, fstRuntime)
    }

    val fstEnabled: Boolean get() = fstRuntime != null

    override fun close() {
        fstRuntime?.close()
    }

    fun gazetteer(): PoliceTermsGazetteer = gazetteer

    fun normalize(text: String): PoliceTermsNormalizeResult {
        if (text.isEmpty()) {
            return PoliceTermsNormalizeResult(text, emptyList())
        }
        val corrected = if (fstRuntime != null) {
            fstRuntime.applyGlobal(text)
        } else {
            homophones.applyPhrases(text)
        }
        val spans = locateSpans(corrected)
        return PoliceTermsNormalizeResult(corrected, spans)
    }

    private fun locateSpans(text: String): List<PoliceTermsSpan> {
        val spans = mutableListOf<PoliceTermsSpan>()
        var i = 0
        while (i < text.length) {
            val term = gazetteer.findLongestAt(text, i)
            if (term != null) {
                spans.add(
                    PoliceTermsSpan(
                        start = i,
                        end = i + term.length,
                        raw = term,
                        normalized = term,
                        valid = gazetteer.isKnown(term),
                    ),
                )
                i += term.length
            } else {
                i++
            }
        }
        return spans
    }
}
