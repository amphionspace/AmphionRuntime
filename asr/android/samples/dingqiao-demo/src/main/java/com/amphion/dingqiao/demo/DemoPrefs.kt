package com.amphion.dingqiao.demo

import android.content.Context

object DemoPrefs {

    private const val PREFS = "dingqiao_demo"
    private const val KEY_VOICEPRINT_ID = "voiceprint_id"
    private const val KEY_HOTWORDS = "user_hotwords"

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

    fun getUserHotwords(context: Context): List<String> =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getStringSet(KEY_HOTWORDS, emptySet())
            ?.map { it.trim() }
            ?.filter { it.isNotEmpty() }
            ?.sorted()
            ?: emptyList()

    fun setUserHotwords(context: Context, words: List<String>) {
        val normalized = words.map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putStringSet(KEY_HOTWORDS, normalized)
            .apply()
    }
}
