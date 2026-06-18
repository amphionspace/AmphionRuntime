package com.amphion.asr.sample.plate

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.VadConfig
import com.amphion.asr.sample.HotwordsPrefs
import com.amphion.asr.sample.MainActivity
import com.amphion.police.PoliceEngineConfig
import com.amphion.police.plate.PlateHotwords

/**
 * 构建车牌场景 ASR 配置：SDK ITN（final 内） + 可选车牌热词偏置。
 *
 * 流水线顺序与云端一致：ASR(final 已 ITN) → [PlateEnhance.apply] → 业务。
 */
object PlateAsrConfig {

    data class Options(
        val plateHotwords: Boolean = true,
        val plateNormalize: Boolean = true,
        val itn: Boolean = true,
        val batchMode: Boolean = false,
    )

    fun effectiveHotwords(context: Context, lang: AsrLanguage, plateHotwords: Boolean): List<String> {
        val user = HotwordsPrefs(context).activeWords(lang)
        val merged = PlateHotwords.mergeWithUserWords(user, plateHotwords)
        if (merged.isNotEmpty()) return merged
        val poolArmed = user.isNotEmpty() || plateHotwords
        return if (poolArmed) listOf(PoliceEngineConfig.HOTWORD_POOL_PLACEHOLDER) else emptyList()
    }

    /** 用户可见热词（不含池占位词），用于 UI 展示。 */
    fun displayHotwords(context: Context, lang: AsrLanguage, plateHotwords: Boolean): List<String> {
        return PlateHotwords.mergeWithUserWords(
            HotwordsPrefs(context).activeWords(lang),
            plateHotwords,
        )
    }

    fun build(
        context: Context,
        lang: AsrLanguage = AsrLanguage.ZH_EN,
        options: Options = Options(),
        hotwordsScore: Float = MainActivity.HOTWORDS_SCORE,
    ): AsrConfig {
        val words = effectiveHotwords(context, lang, options.plateHotwords)
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
