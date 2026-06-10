package com.amphion.asr.sample.police_station

import android.content.Context

/**
 * 警用 ASR final 文本的派出所后处理：
 * P4 解码守卫 → 谐音 → P2 标点 → 站名片段替换 → P3 整句润色。
 */
class PoliceStationNormalizer private constructor(
    private val homophones: PoliceStationHomophoneDict,
    private val gazetteer: PoliceStationGazetteer,
    private val fstRuntime: PoliceStationFstRuntime?,
) : AutoCloseable {

    companion object {
        private val STATION_SUFFIX = Regex("""[\u4e00-\u9fff0-9]{2,28}派出所""")

        fun create(context: Context, useFst: Boolean = false): PoliceStationNormalizer =
            PoliceStationNormalizer(
                PoliceStationHomophoneDict.load(context),
                PoliceStationGazetteer.load(context),
                fstRuntime = if (useFst) PoliceStationFstRuntime.create(context) else null,
            )

        internal fun create(
            homophones: PoliceStationHomophoneDict,
            gazetteer: PoliceStationGazetteer,
            fstRuntime: PoliceStationFstRuntime? = null,
        ): PoliceStationNormalizer = PoliceStationNormalizer(homophones, gazetteer, fstRuntime)
    }

    val fstEnabled: Boolean get() = fstRuntime != null

    override fun close() {
        fstRuntime?.close()
    }

    fun normalize(text: String): PoliceStationNormalizeResult {
        if (text.isEmpty()) {
            return PoliceStationNormalizeResult(text, emptyList(), decodeCollapse = true)
        }
        if (PoliceStationDecodeGuard.isDecodeCollapse(text)) {
            return PoliceStationNormalizeResult(text, emptyList(), decodeCollapse = true)
        }

        var corrected = if (fstRuntime != null) {
            fstRuntime.applyGlobal(text)
        } else {
            homophones.applyGlobalPhrases(text)
        }
        corrected = PoliceStationPunctUtil.normalizeAdminPunct(corrected)

        val span = locateSpan(corrected)
            ?: return finish(applyPolish(corrected), emptyList())
        var normalizedName = normalizeSpan(span.raw, corrected)
        normalizedName = PoliceStationPunctUtil.normalizeAdminPunct(normalizedName)
        val valid = gazetteer.isKnown(normalizedName)
        var outText = corrected.replaceRange(span.start, span.end, normalizedName)
        outText = applyPolish(outText)

        return finish(
            outText,
            listOf(
                PoliceStationSpan(
                    start = span.start,
                    end = span.end,
                    raw = span.raw,
                    normalized = normalizedName,
                    valid = valid,
                ),
            ),
        )
    }

    private fun finish(
        text: String,
        spans: List<PoliceStationSpan>,
    ): PoliceStationNormalizeResult =
        PoliceStationNormalizeResult(text, spans, decodeCollapse = false)

    private data class RawSpan(val start: Int, val end: Int, val raw: String)

    private fun locateSpan(text: String): RawSpan? {
        gazetteer.findLongestIn(text)?.let { known ->
            val start = text.indexOf(known)
            if (start >= 0) {
                return RawSpan(start, start + known.length, known)
            }
        }
        val m = STATION_SUFFIX.findAll(text).toList()
        if (m.isEmpty()) return null
        val best = m.minByOrNull { it.value.length } ?: return null
        return RawSpan(best.range.first, best.range.last + 1, best.value)
    }

    private fun applyPolish(text: String): String =
        if (fstRuntime != null) fstRuntime.applyPolish(text)
        else PoliceStationSentenceUtil.polish(text)

    private fun normalizeSpan(raw: String, context: String): String {
        var corrected = homophones.applyGazetteerConstrained(raw, gazetteer)
        corrected = PoliceStationPunctUtil.normalizeAdminPunct(corrected)
        gazetteer.findLongestIn(corrected)?.let { return it }
        gazetteer.findLongestIn(context)?.let { return it }
        return corrected
    }
}
