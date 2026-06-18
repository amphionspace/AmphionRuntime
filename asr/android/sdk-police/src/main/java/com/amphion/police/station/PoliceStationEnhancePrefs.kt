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

    companion object {
        private const val NAME = "amphion_police_station_enhance"
        private const val KEY_STATION_HOTWORDS = "station_hotwords"
        private const val KEY_STATION_NORMALIZE = "station_normalize"
        private const val KEY_STATION_FST = "station_fst"
    }
}
