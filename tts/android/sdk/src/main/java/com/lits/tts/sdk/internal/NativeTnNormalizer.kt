package com.lits.tts.sdk.internal

import android.util.Log
import java.io.File

internal object NativeTnNormalizer {
    private const val TAG = "LitsTnNative"

    private val isAvailable: Boolean by lazy {
        try {
            System.loadLibrary("lits_tn")
            Log.i(TAG, "native TN library loaded name=lits_tn")
            true
        } catch (error: Throwable) {
            Log.w(TAG, "native TN library is unavailable", error)
            false
        }
    }

    fun normalize(rootDir: File, lang: String, text: String): String? {
        if (!isAvailable) return null
        Log.i(TAG, "native TN normalize start lang=$lang root=${rootDir.absolutePath} input=${text.takeForLog()}")
        return normalizeNative(rootDir.absolutePath, lang, text).also { normalized ->
            Log.i(TAG, "native TN normalize success lang=$lang output=${normalized.takeForLog()}")
        }
    }

    fun clear(rootDir: File) {
        if (!isAvailable) return
        runCatching { clearCacheNative(rootDir.absolutePath) }
    }

    private external fun normalizeNative(rulesRoot: String, lang: String, text: String): String

    private external fun clearCacheNative(rulesRoot: String)

    private fun String.takeForLog(maxLength: Int = 160): String =
        if (length <= maxLength) this else take(maxLength) + "...(len=$length)"
}
