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

    const val HOTWORDS_SCORE_DEFAULT = 5.0f

    /**
     * 占位热词：池 armed 但无有效词时使用，保证 recognizer 池维度一致。
     */
    const val HOTWORD_POOL_PLACEHOLDER = "__placeholder__"

    fun effectiveHotwords(
        userHotwords: List<String>,
        plateHotwords: Boolean = true,
        stationHotwords: Boolean = true,
        termsHotwords: Boolean = true,
    ): List<String> {
        val out = linkedSetOf<String>()
        userHotwords.filter { it.isNotBlank() }.forEach { out.add(it.trim()) }
        if (termsHotwords) {
            PoliceTermsHotwords.PRESET.forEach { out.add(it) }
        }
        if (plateHotwords) {
            PlateHotwords.PRESET.forEach { out.add(it) }
        }
        if (stationHotwords) {
            PoliceStationHotwords.PRESET.forEach { out.add(it) }
        }
        if (out.isNotEmpty()) return out.toList()
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
