package com.amphion.asr.sample.police_terms

import android.content.Context
import com.amphion.asr.AsrConfig
import com.amphion.asr.AsrLanguage
import com.amphion.asr.VadConfig
import com.amphion.asr.sample.HotwordsPrefs
import com.amphion.asr.sample.MainActivity
import com.amphion.police.PoliceEngineConfig
import com.amphion.police.PoliceHotwordProfile
import com.amphion.police.terms.PoliceTermsHotwords

/**
 * 构建警务术语场景 ASR 配置：SDK ITN + 可选术语热词偏置。
 *
 * 流水线：ASR(final 已 ITN) → [PoliceTermsEnhance.apply] → 业务。
 */
object PoliceTermsAsrConfig {

    data class Options(
        val termsHotwords: Boolean = true,
        val termsNormalize: Boolean = true,
        val itn: Boolean = true,
        val batchMode: Boolean = false,
        /** Hidden pruning experiment override; null preserves the existing preference behavior. */
        val hotwordProfile: PoliceHotwordProfile? = null,
        /** 主动 endpoint 尾静音阈值（ms）；null=沿用默认（batchMode 下为 0=关闭）。仅端点实验用。 */
        val activeEndpointMs: Int? = null,
    )

    fun effectiveHotwords(
        context: Context,
        lang: AsrLanguage,
        termsHotwords: Boolean,
    ): List<String> {
        val user = HotwordsPrefs(context).activeWords(lang)
        val merged = PoliceTermsHotwords.mergeWithUserWords(user, termsHotwords)
        if (merged.isNotEmpty()) return merged
        val poolArmed = user.isNotEmpty() || termsHotwords
        return if (poolArmed) listOf(PoliceEngineConfig.HOTWORD_POOL_PLACEHOLDER) else emptyList()
    }

    fun build(
        context: Context,
        lang: AsrLanguage = AsrLanguage.ZH_EN,
        options: Options = Options(),
        hotwordsScore: Float = MainActivity.HOTWORDS_SCORE,
    ): AsrConfig {
        val words = if (options.hotwordProfile == null) {
            effectiveHotwords(context, lang, options.termsHotwords)
        } else {
            PoliceEngineConfig.effectiveHotwordsForProfile(
                userHotwords = HotwordsPrefs(context).activeWords(lang),
                profile = options.hotwordProfile,
                plateHotwords = false,
                stationHotwords = false,
                termsHotwords = true,
            )
        }
        val b = AsrConfig.Builder()
            .numThreads(2)
            .punctuation(true)
            .itn(options.itn)
            .vad(true)
            .endpoint(true)
        val epMs = options.activeEndpointMs ?: if (options.batchMode) 0 else null
        if (epMs != null) {
            b.vadConfig(VadConfig(activeEndpointSilenceMs = epMs))
        }
        if (words.isNotEmpty()) {
            b.hotwords(words, hotwordsScore)
        }
        return b.build()
    }
}
