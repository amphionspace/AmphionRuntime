package com.amphion.asr.internal

/**
 * Bounds manual-finish padding while counting real encoder decode opportunities.
 *
 * Synthetic padding is accepted directly by the recognizer stream and never enters public PCM,
 * VAD, Speaker VAD, or speaker-scoring buffers.
 */
internal class FinalTailFlushPlanner(
    val stepMs: Int,
    val maxPaddingMs: Int,
    val requiredDecodes: Int,
) {
    init {
        require(stepMs > 0) { "stepMs must be > 0" }
        require(maxPaddingMs > 0) { "maxPaddingMs must be > 0" }
        require(requiredDecodes > 0) { "requiredDecodes must be > 0" }
    }

    var paddingDurationMs: Int = 0
        private set

    var decodeOpportunities: Int = 0
        private set

    val isComplete: Boolean
        get() = decodeOpportunities >= requiredDecodes

    val usedFallback: Boolean
        get() = paddingDurationMs >= maxPaddingMs && decodeOpportunities < requiredDecodes

    fun nextPaddingMs(): Int = if (isComplete || paddingDurationMs >= maxPaddingMs) {
        0
    } else {
        minOf(stepMs, maxPaddingMs - paddingDurationMs)
    }

    fun recordPadding(durationMs: Int) {
        val expected = nextPaddingMs()
        require(durationMs > 0 && durationMs == expected) {
            "padding must match nextPaddingMs: $durationMs != $expected"
        }
        paddingDurationMs += durationMs
    }

    fun recordDecode() {
        check(!isComplete) { "final tail flush is already complete" }
        decodeOpportunities += 1
    }
}
