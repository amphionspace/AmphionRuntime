package com.amphion.asr.internal

/** Counts only complete VAD windows, regardless of the caller's PCM frame size. */
internal class VadTrailingSilenceClock(
    private val sampleRate: Int,
    endpointSilenceMs: Int,
) {
    private val thresholdSamples = endpointSilenceMs.toLong() * sampleRate / 1000L
    private var silenceSamples = 0L

    fun observeSilence(consumedVadSamples: Int): Boolean {
        require(consumedVadSamples >= 0)
        if (thresholdSamples <= 0L) return false
        silenceSamples += consumedVadSamples
        return silenceSamples >= thresholdSamples
    }

    fun elapsedMs(): Long = silenceSamples * 1000L / sampleRate

    fun reset() {
        silenceSamples = 0L
    }
}
