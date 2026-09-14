package com.amphion.asr.internal

/** Native builds without the negative-rule guard treat -1 as an immediate Rule3 endpoint. */
internal object NativeRule3Duration {
    // Native Rule3 compares float-second durations; this remains unreachable without overflow.
    private const val DISABLED_DURATION_SECONDS = Float.MAX_VALUE

    fun forRecognizer(configuredSeconds: Float): Float =
        if (configuredSeconds < 0f) DISABLED_DURATION_SECONDS else configuredSeconds
}
