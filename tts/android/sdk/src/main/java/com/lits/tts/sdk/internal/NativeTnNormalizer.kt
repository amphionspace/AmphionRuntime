package com.lits.tts.sdk.internal

import android.util.Log
import java.io.File

internal object NativeTnNormalizer {
    private const val TAG = "LitsTnNative"

    private val isAvailable: Boolean by lazy {
        try {
            System.loadLibrary("lits_tn")
            true
        } catch (error: Throwable) {
            Log.w(TAG, "native TN library is unavailable", error)
            false
        }
    }

    fun normalize(rootDir: File, lang: String, text: String): String? {
        if (!isAvailable) return null
        return normalizeNative(rootDir.absolutePath, lang, text)
    }

    fun clear(rootDir: File) {
        if (!isAvailable) return
        runCatching { clearCacheNative(rootDir.absolutePath) }
    }

    private external fun normalizeNative(rulesRoot: String, lang: String, text: String): String

    private external fun clearCacheNative(rulesRoot: String)
}
