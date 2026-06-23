package com.amphion.police.plate

import android.content.Context

/** 车牌增强开关（对齐云端 ITN + 热词 + 车牌后处理分层）。 */
class PlateEnhancePrefs(context: Context) {

    private val sp = context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    /** 是否在 ASR 解码时注入 [PlateHotwords.PRESET]（默认开）。 */
    var plateHotwordsEnabled: Boolean
        get() = sp.getBoolean(KEY_PLATE_HOTWORDS, true)
        set(value) = sp.edit().putBoolean(KEY_PLATE_HOTWORDS, value).apply()

    /** 是否在 onFinal 上再跑 [PlateNormalizer]（默认开）。 */
    var plateNormalizeEnabled: Boolean
        get() = sp.getBoolean(KEY_PLATE_NORMALIZE, true)
        set(value) = sp.edit().putBoolean(KEY_PLATE_NORMALIZE, value).apply()

    /**
     * 谐音映射走 FST（[PlateFstRuntime]）；关则回退 [PlateHomophoneDict]。
     * 默认关，便于与 Kotlin 规则 A/B 对照。
     */
    var plateFstEnabled: Boolean
        get() = sp.getBoolean(KEY_PLATE_FST, false)
        set(value) = sp.edit().putBoolean(KEY_PLATE_FST, value).apply()

    /**
     * 是否走车牌后处理 V2（Layer 0 知识库 + 读音映射 + 省份感知校验，面向全国车牌）。
     * 默认关：保留并默认走老方案 [PlateNormalizer]，可随时回退。V2 验证达标后再翻默认值。
     */
    var plateV2Enabled: Boolean
        get() = sp.getBoolean(KEY_PLATE_V2, false)
        set(value) = sp.edit().putBoolean(KEY_PLATE_V2, value).apply()

    companion object {
        private const val NAME = "amphion_plate_enhance"
        private const val KEY_PLATE_HOTWORDS = "plate_hotwords"
        private const val KEY_PLATE_NORMALIZE = "plate_normalize"
        private const val KEY_PLATE_FST = "plate_fst"
        private const val KEY_PLATE_V2 = "plate_v2"
    }
}
