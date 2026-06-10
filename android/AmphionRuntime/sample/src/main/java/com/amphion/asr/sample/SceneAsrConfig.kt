package com.amphion.asr.sample

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.VadConfig
import com.amphion.asr.sample.plate.PlateHotwords
import com.amphion.asr.sample.police_station.PoliceStationHotwords
import com.amphion.asr.sample.police_terms.PoliceTermsHotwords

/**
 * 多场景 ASR 配置：合并用户热词 + 警务术语 + 车牌 + 派出所预设。
 */
object SceneAsrConfig {

    fun effectiveHotwords(
        context: Context,
        lang: AsrLanguage,
        plateHotwords: Boolean,
        stationHotwords: Boolean,
        termsHotwords: Boolean = true,
    ): List<String> {
        val user = HotwordsPrefs(context).activeWords(lang)
        val out = linkedSetOf<String>()
        user.filter { it.isNotBlank() }.forEach { out.add(it.trim()) }
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
        val poolArmed = user.isNotEmpty() || plateHotwords || stationHotwords || termsHotwords
        return if (poolArmed) listOf(MainActivity.HOTWORD_POOL_PLACEHOLDER) else emptyList()
    }

    fun displayHotwords(
        context: Context,
        lang: AsrLanguage,
        plateHotwords: Boolean,
        stationHotwords: Boolean,
        termsHotwords: Boolean = true,
    ): List<String> = effectiveHotwords(context, lang, plateHotwords, stationHotwords, termsHotwords)
        .filter { it != MainActivity.HOTWORD_POOL_PLACEHOLDER }

    fun build(
        context: Context,
        lang: AsrLanguage = AsrLanguage.ZH_EN,
        plateHotwords: Boolean = true,
        stationHotwords: Boolean = true,
        termsHotwords: Boolean = true,
        itn: Boolean = true,
        batchMode: Boolean = false,
        hotwordsScore: Float = MainActivity.HOTWORDS_SCORE,
    ): AsrConfig {
        val words = effectiveHotwords(context, lang, plateHotwords, stationHotwords, termsHotwords)
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
