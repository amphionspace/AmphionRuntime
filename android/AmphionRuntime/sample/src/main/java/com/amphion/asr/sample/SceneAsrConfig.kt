package com.amphion.asr.sample

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.police.PoliceEngineConfig

/**
 * Sample 层 ASR 配置：合并用户热词与警务三场景预设，委托 [PoliceEngineConfig]。
 */
object SceneAsrConfig {

    fun effectiveHotwords(
        context: Context,
        lang: AsrLanguage,
        plateHotwords: Boolean,
        stationHotwords: Boolean,
        termsHotwords: Boolean = true,
    ): List<String> = PoliceEngineConfig.effectiveHotwords(
        userHotwords = HotwordsPrefs(context).activeWords(lang),
        plateHotwords = plateHotwords,
        stationHotwords = stationHotwords,
        termsHotwords = termsHotwords,
    )

    fun displayHotwords(
        context: Context,
        lang: AsrLanguage,
        plateHotwords: Boolean,
        stationHotwords: Boolean,
        termsHotwords: Boolean = true,
    ): List<String> = effectiveHotwords(context, lang, plateHotwords, stationHotwords, termsHotwords)
        .filter { it != PoliceEngineConfig.HOTWORD_POOL_PLACEHOLDER }

    fun build(
        context: Context,
        lang: AsrLanguage = AsrLanguage.ZH_EN,
        plateHotwords: Boolean = true,
        stationHotwords: Boolean = true,
        termsHotwords: Boolean = true,
        itn: Boolean = true,
        batchMode: Boolean = false,
        hotwordsScore: Float = MainActivity.HOTWORDS_SCORE,
    ): AsrConfig = PoliceEngineConfig.build(
        userHotwords = HotwordsPrefs(context).activeWords(lang),
        lang = lang,
        plateHotwords = plateHotwords,
        stationHotwords = stationHotwords,
        termsHotwords = termsHotwords,
        itn = itn,
        batchMode = batchMode,
        hotwordsScore = hotwordsScore,
    )
}
