package com.amphion.asr.sample.police_station

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.VadConfig
import com.amphion.asr.sample.HotwordsPrefs
import com.amphion.asr.sample.MainActivity

/**
 * 构建派出所场景 ASR 配置：SDK ITN + 可选派出所热词偏置。
 *
 * 流水线：ASR(final 已 ITN) → [PoliceStationEnhance.apply] → 业务。
 */
object PoliceStationAsrConfig {

    data class Options(
        val stationHotwords: Boolean = true,
        val stationNormalize: Boolean = true,
        val itn: Boolean = true,
        val batchMode: Boolean = false,
    )

    fun effectiveHotwords(
        context: Context,
        lang: AsrLanguage,
        stationHotwords: Boolean,
    ): List<String> {
        val user = HotwordsPrefs(context).activeWords(lang)
        val merged = PoliceStationHotwords.mergeWithUserWords(user, stationHotwords)
        if (merged.isNotEmpty()) return merged
        val poolArmed = user.isNotEmpty() || stationHotwords
        return if (poolArmed) listOf(MainActivity.HOTWORD_POOL_PLACEHOLDER) else emptyList()
    }

    fun build(
        context: Context,
        lang: AsrLanguage = AsrLanguage.ZH_EN,
        options: Options = Options(),
        hotwordsScore: Float = MainActivity.HOTWORDS_SCORE,
    ): AsrConfig {
        val words = effectiveHotwords(context, lang, options.stationHotwords)
        val b = AsrConfig.Builder()
            .numThreads(2)
            .punctuation(true)
            .itn(options.itn)
            .vad(true)
            .endpoint(true)
        if (options.batchMode) {
            b.vadConfig(VadConfig(activeEndpointSilenceMs = 0))
        }
        if (words.isNotEmpty()) {
            b.hotwords(words, hotwordsScore)
        }
        return b.build()
    }
}
