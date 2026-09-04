package com.amphion.asr.internal

/**
 * Bounds manual-finish padding while counting real encoder decode opportunities.
 *
 * A first chunk may complete the flush only when it already contains the configured amount of
 * synthetic right context; otherwise the caller must decode a second chunk. Replay streams may
 * additionally require a minimum amount of padding before either completion rule applies.
 * Synthetic padding is accepted directly by the recognizer stream and never enters public PCM,
 * VAD, Speaker VAD, or speaker-scoring buffers.
 */
internal class FinalTailFlushPlanner(
    val stepMs: Int,
    val maxPaddingMs: Int,
    val requiredDecodes: Int,
    val singleDecodeMinPaddingMs: Int = 0,
    val minimumPaddingMs: Int = 0,
) {
    init {
        require(stepMs > 0) { "stepMs must be > 0" }
        require(maxPaddingMs > 0) { "maxPaddingMs must be > 0" }
        require(requiredDecodes > 0) { "requiredDecodes must be > 0" }
        require(singleDecodeMinPaddingMs in 0..maxPaddingMs) {
            "singleDecodeMinPaddingMs must be within the padding bound"
        }
        require(minimumPaddingMs in 0..maxPaddingMs) {
            "minimumPaddingMs must be within the padding bound"
        }
    }

    var paddingDurationMs: Int = 0
        private set

    var decodeOpportunities: Int = 0
        private set

    private var firstDecodePaddingMs: Int = -1

    val isComplete: Boolean
        get() {
            if (paddingDurationMs < minimumPaddingMs) return false
            if (minimumPaddingMs > 0) return decodeOpportunities >= requiredDecodes
            return decodeOpportunities >= requiredDecodes ||
                (decodeOpportunities >= 1 && singleDecodeMinPaddingMs > 0 &&
                    firstDecodePaddingMs >= singleDecodeMinPaddingMs)
        }

    val usedFallback: Boolean
        get() = paddingDurationMs >= maxPaddingMs && !isComplete

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
        if (decodeOpportunities == 0) firstDecodePaddingMs = paddingDurationMs
        decodeOpportunities += 1
    }
}
