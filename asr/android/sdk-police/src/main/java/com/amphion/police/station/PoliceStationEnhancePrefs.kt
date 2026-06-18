package com.amphion.police.station

import android.content.Context

/** 派出所增强开关（热词 + 后处理分层，对齐 plate 包）。 */
class PoliceStationEnhancePrefs(context: Context) {

    private val sp = context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    var stationHotwordsEnabled: Boolean
        get() = sp.getBoolean(KEY_STATION_HOTWORDS, true)
        set(value) = sp.edit().putBoolean(KEY_STATION_HOTWORDS, value).apply()

    var stationNormalizeEnabled: Boolean
        get() = sp.getBoolean(KEY_STATION_NORMALIZE, true)
        set(value) = sp.edit().putBoolean(KEY_STATION_NORMALIZE, value).apply()

    /** P3：FST 后处理（global/polish FST + gazetteer 宿主；需 TextRewriteFst JNI）。 */
    var stationFstEnabled: Boolean
        get() = sp.getBoolean(KEY_STATION_FST, true)
        set(value) = sp.edit().putBoolean(KEY_STATION_FST, value).apply()

    /**
     * V2 派出所后处理（字级候选格 + gazetteer 当校验器，面向泛化，对齐车牌 [plate] 包的 plateV2）。
     * 默认 false = 走老方案 [PoliceStationNormalizer]，可灰度切换；开启后行为见 [PoliceStationNormalizerV2]。
     */
    var stationV2Enabled: Boolean
        get() = sp.getBoolean(KEY_STATION_V2, false)
        set(value) = sp.edit().putBoolean(KEY_STATION_V2, value).apply()

    companion object {
        private const val NAME = "amphion_police_station_enhance"
        private const val KEY_STATION_HOTWORDS = "station_hotwords"
        private const val KEY_STATION_NORMALIZE = "station_normalize"
        private const val KEY_STATION_FST = "station_fst"
        private const val KEY_STATION_V2 = "station_v2"
    }
}
