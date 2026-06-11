package com.amphion.dingqiao.demo

import android.content.Context

object DemoPrefs {

    private const val PREFS = "dingqiao_demo"
    private const val KEY_VOICEPRINT_ID = "voiceprint_id"

    fun getVoiceprintId(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_VOICEPRINT_ID, null)
            ?.takeIf { it.isNotBlank() }

    fun setVoiceprintId(context: Context, id: String?) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_VOICEPRINT_ID, id)
            .apply()
    }
}
