package com.amphion.police.terms

import android.content.Context

/** 警务术语增强开关（热词 + 后处理分层，对齐 plate / police_station 包）。 */
class PoliceTermsEnhancePrefs(context: Context) {

    private val sp = context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    var termsHotwordsEnabled: Boolean
        get() = sp.getBoolean(KEY_TERMS_HOTWORDS, true)
        set(value) = sp.edit().putBoolean(KEY_TERMS_HOTWORDS, value).apply()

    var termsNormalizeEnabled: Boolean
        get() = sp.getBoolean(KEY_TERMS_NORMALIZE, true)
        set(value) = sp.edit().putBoolean(KEY_TERMS_NORMALIZE, value).apply()

    /**
     * global 谐音走 FST（[PoliceTermsFstRuntime]）；关则回退 [PoliceTermsHomophoneDict]。
     * 默认关，便于与 Kotlin 规则 A/B 对照。
     */
    var termsFstEnabled: Boolean
        get() = sp.getBoolean(KEY_TERMS_FST, false)
        set(value) = sp.edit().putBoolean(KEY_TERMS_FST, value).apply()

    /**
     * V2 术语后处理（V1 全局谐音 + 保守字级模糊层，对齐 plate/station 包）。
     * 默认 false = 走老方案 [PoliceTermsNormalizer]，可灰度切换；行为见 [PoliceTermsNormalizerV2]。
     */
    var termsV2Enabled: Boolean
        get() = sp.getBoolean(KEY_TERMS_V2, false)
        set(value) = sp.edit().putBoolean(KEY_TERMS_V2, value).apply()

    companion object {
        private const val NAME = "amphion_police_terms_enhance"
        private const val KEY_TERMS_HOTWORDS = "terms_hotwords"
        private const val KEY_TERMS_NORMALIZE = "terms_normalize"
        private const val KEY_TERMS_FST = "terms_fst"
        private const val KEY_TERMS_V2 = "terms_v2"
    }
}
