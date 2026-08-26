package com.amphion.dingqiao.demo

import java.util.Locale

internal object RecordingUiPolicy {

    enum class DurationState {
        TOO_SHORT,
        READY,
        TOO_LONG,
    }

    fun elapsedLabel(elapsedMs: Long): String {
        val totalTenths = elapsedMs.coerceAtLeast(0L) / 100L
        val minutes = totalTenths / 600L
        val seconds = (totalTenths / 10L) % 60L
        val tenths = totalTenths % 10L
        return String.format(Locale.US, "%02d:%02d.%d", minutes, seconds, tenths)
    }

    fun canRegister(sampleCount: Int, recording: Boolean, registering: Boolean): Boolean =
        sampleCount > 0 && !recording && !registering

    fun durationState(elapsedMs: Long): DurationState = when {
        elapsedMs < 3_000L -> DurationState.TOO_SHORT
        elapsedMs <= 8_000L -> DurationState.READY
        else -> DurationState.TOO_LONG
    }
}
