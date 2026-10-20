package com.amphion.police

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.VadConfig
import com.amphion.police.plate.PlateHotwords
import com.amphion.police.station.PoliceStationHotwords
import com.amphion.police.terms.PoliceTermsHotwords

/**
 * 警务三场景 ASR 热词合并与 [AsrConfig] 构建。
 *
 * 默认全开三场景预设热词；用户热词通过 [userHotwords] 传入（不依赖 sample UI）。
 */
object PoliceEngineConfig {

    /** 预置池（车牌/派出所/术语）的加权分。Police 1.4.0 的候选校准权重，避免短预置词过度覆盖声学结果。 */
    const val HOTWORDS_SCORE_DEFAULT = 1.0f

    /**
     * 调用方热词（sysGeneralLexicon）的逐词加权分。预置池按 1.4.0 校准停在
     * [HOTWORDS_SCORE_DEFAULT]=1.0，但该档对业务专名偏置不足——同音常用词仍会胜出
     * （「鼎桥」被识别成「顶桥」）。3.0 是 docs/asr/AISHELL3_HOTWORDS_EVAL.md 的工作点
     * （热词精确命中率 76.41% → 96.12%），也是车牌 A/B 实测确认的中档。
     */
    const val USER_HOTWORDS_SCORE = 3.0f

    /**
     * 占位热词：池 armed 但无有效词时使用，保证 recognizer 池维度一致。
     */
    const val HOTWORD_POOL_PLACEHOLDER = "__placeholder__"

    /**
     * sherpa-onnx hotwords buffer 的逐词加权语法：`<词> :<分>`。未标注的行回落到
     * ContextGraph 的全局 context_score（= [AsrConfig.hotwordsScore]），所以两档可以同池共存。
     */
    private fun weighted(word: String, score: Float): String = "$word :$score"

    /** 去掉逐词加权后缀，用于把热词回显给用户。 */
    fun displayText(entry: String): String = entry.substringBeforeLast(" :", entry)

    fun effectiveHotwords(
        userHotwords: List<String>,
        plateHotwords: Boolean = true,
        stationHotwords: Boolean = true,
        termsHotwords: Boolean = true,
    ): List<String> {
        // seen 以原词去重，保证同一短语不会同时以带分和不带分两种形式进池。
        val seen = linkedSetOf<String>()
        val out = mutableListOf<String>()
        fun append(value: String, score: Float? = null) {
            val normalized = value.trim()
            if (normalized.isEmpty() || !seen.add(normalized)) return
            out += if (score == null) normalized else weighted(normalized, score)
        }
        userHotwords.forEach { append(it, USER_HOTWORDS_SCORE) }
        if (termsHotwords) {
            PoliceTermsHotwords.PRESET.forEach { append(it) }
        }
        if (plateHotwords) {
            PlateHotwords.PRESET.forEach { append(it) }
        }
        if (stationHotwords) {
            PoliceStationHotwords.PRESET.forEach { append(it) }
        }
        if (out.isNotEmpty()) return out
        val poolArmed = userHotwords.isNotEmpty() || plateHotwords || stationHotwords || termsHotwords
        return if (poolArmed) listOf(HOTWORD_POOL_PLACEHOLDER) else emptyList()
    }

    fun build(
        userHotwords: List<String> = emptyList(),
        lang: AsrLanguage = AsrLanguage.ZH_EN,
        plateHotwords: Boolean = true,
        stationHotwords: Boolean = true,
        termsHotwords: Boolean = true,
        itn: Boolean = true,
        batchMode: Boolean = false,
        hotwordsScore: Float = HOTWORDS_SCORE_DEFAULT,
    ): AsrConfig {
        @Suppress("UNUSED_VARIABLE")
        val unusedLang = lang // reserved for future yue-en police presets
        val words = effectiveHotwords(userHotwords, plateHotwords, stationHotwords, termsHotwords)
        val b = AsrConfig.Builder()
            .numThreads(2)
            .punctuation(true)
            .itn(itn)
            .vad(true)
            .endpoint(true)
        if (batchMode) {
            b.vadConfig(VadConfig(activeEndpointSilenceMs = 0))
        }
        if (words.isNotEmpty()) {
            b.hotwords(words, hotwordsScore)
        }
        return b.build()
    }
}
