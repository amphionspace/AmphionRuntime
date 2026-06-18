package com.amphion.asr.internal

import android.util.Log
import com.amphion.asr.AmphionLogLevel

internal object Logger {

    private const val TAG = "AmphionRuntime"

    /**
     * 指标专用 tag。和普通诊断日志分开，方便业务方用 `adb logcat -s AmphionMetrics`
     * 单独拉指标流；除 [AmphionLogLevel.NONE] 外恒打。
     */
    private const val METRICS_TAG = "AmphionMetrics"

    @Volatile
    private var minLevel: AmphionLogLevel = AmphionLogLevel.WARN

    fun setLevel(level: AmphionLogLevel) {
        minLevel = level
    }

    fun d(msg: String) { if (allow(AmphionLogLevel.DEBUG)) Log.d(TAG, msg) }
    fun i(msg: String) { if (allow(AmphionLogLevel.INFO))  Log.i(TAG, msg) }
    fun w(msg: String) { if (allow(AmphionLogLevel.WARN))  Log.w(TAG, msg) }
    fun e(msg: String, t: Throwable? = null) {
        if (allow(AmphionLogLevel.ERROR)) {
            if (t == null) Log.e(TAG, msg) else Log.e(TAG, msg, t)
        }
    }

    fun metric(line: String) {
        if (minLevel == AmphionLogLevel.NONE) return
        Log.i(METRICS_TAG, line)
    }

    private fun allow(level: AmphionLogLevel): Boolean {
        if (minLevel == AmphionLogLevel.NONE) return false
        return level.ordinal >= minLevel.ordinal
    }
}
