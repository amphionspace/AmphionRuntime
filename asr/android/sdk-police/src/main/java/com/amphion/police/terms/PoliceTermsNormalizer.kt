package com.amphion.police.terms

import android.content.Context

/**
 * 警用 ASR final 文本的术语后处理：谐音替换 → gazetteer 最长匹配 → 记录 span。
 *
 * [useFst]=true 时先走旧 FST，再始终应用当前 CSV 规则；gazetteer 仍在 Kotlin 宿主。
 * FST 是可选加速/兼容层，不得成为另一份会绕过最新术语规则的事实源。
 */
class PoliceTermsNormalizer private constructor(
    private val homophones: PoliceTermsHomophoneDict,
    private val gazetteer: PoliceTermsGazetteer,
    private val fstRuntime: PoliceTermsGlobalRewriter?,
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
            fstRuntime: PoliceTermsGlobalRewriter? = null,
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
        val fstCorrected = fstRuntime?.applyGlobal(text) ?: text
        val homophoneCorrected = homophones.applyPhrases(fstCorrected)
        val corrected = PoliceTermsShortGuard.apply(homophoneCorrected)
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
