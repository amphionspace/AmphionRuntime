package com.amphion.asr.internal

import android.util.Log
import com.amphion.asr.AsrLogLevel

internal object Logger {

    private const val TAG = "AsrSdk"

    @Volatile
    private var minLevel: AsrLogLevel = AsrLogLevel.WARN

    @Volatile
    var httpTimeoutMs: Int = 30_000
        private set

    fun setLevel(level: AsrLogLevel) {
        minLevel = level
    }

    fun setHttpTimeoutMs(ms: Int) {
        httpTimeoutMs = ms
    }

    fun d(msg: String) { if (allow(AsrLogLevel.DEBUG)) Log.d(TAG, msg) }
    fun i(msg: String) { if (allow(AsrLogLevel.INFO))  Log.i(TAG, msg) }
    fun w(msg: String) { if (allow(AsrLogLevel.WARN))  Log.w(TAG, msg) }
    fun e(msg: String, t: Throwable? = null) {
        if (allow(AsrLogLevel.ERROR)) {
            if (t == null) Log.e(TAG, msg) else Log.e(TAG, msg, t)
        }
    }

    private fun allow(level: AsrLogLevel): Boolean {
        if (minLevel == AsrLogLevel.NONE) return false
        return level.ordinal >= minLevel.ordinal
    }
}
