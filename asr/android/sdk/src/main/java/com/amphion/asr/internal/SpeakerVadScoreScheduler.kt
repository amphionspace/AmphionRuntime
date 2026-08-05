package com.amphion.asr.internal

/**
 * Anchors Speaker VAD score deadlines to absolute PCM sample positions in one native segment.
 *
 * Callers must stop each internal feed at [samplesUntilNextScore], then call [observe]. This keeps
 * the score timeline independent of how the public writeAudio calls partition the same PCM.
 */
internal class SpeakerVadScoreScheduler(
    val windowSamples: Int,
    val hopSamples: Int,
) {
    init {
        require(windowSamples > 0) { "windowSamples must be > 0" }
        require(hopSamples > 0) { "hopSamples must be > 0" }
    }

    var totalSamples: Int = 0
        private set

    private val firstScoreSample: Int = maxOf(windowSamples, hopSamples)
    private var nextScoreSample: Int = firstScoreSample

    fun samplesUntilNextScore(): Int = (nextScoreSample - totalSamples).coerceAtLeast(1)

    /** Returns true exactly when the accepted slice ends at a score deadline. */
    fun observe(samples: Int): Boolean {
        require(samples >= 0) { "samples must be >= 0" }
        require(samples <= samplesUntilNextScore()) {
            "accepted slice crosses Speaker VAD score deadline"
        }
        totalSamples += samples
        if (totalSamples != nextScoreSample) return false

        nextScoreSample += if (nextScoreSample == firstScoreSample) {
            val remainder = firstScoreSample % hopSamples
            if (remainder == 0) hopSamples else hopSamples - remainder
        } else {
            hopSamples
        }
        return true
    }

    fun reset() {
        totalSamples = 0
        nextScoreSample = firstScoreSample
    }
}
