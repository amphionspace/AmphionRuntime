package com.amphion.asr.internal

import kotlin.math.sqrt

/** Chunk-invariant evidence that unresolved non-silent audio occurred during the initial wait. */
internal class InitialAcousticActivityTracker(
    sampleRate: Int,
    private val rmsThreshold: Float = DEFAULT_RMS_THRESHOLD,
    private val requiredActiveWindows: Int = DEFAULT_REQUIRED_ACTIVE_WINDOWS,
) {
    private val windowSamples = (sampleRate / WINDOWS_PER_SECOND).coerceAtLeast(1)
    private val recentSamples = (sampleRate * RECENT_ACTIVITY_MS / 1000).coerceAtLeast(1)
    private var squareSum = 0.0
    private var samplesInWindow = 0
    private var zeroCrossingsInWindow = 0
    private var previousSample = 0.0f
    private var hasPreviousSample = false
    private var consecutiveActiveWindows = 0
    private var samplesSinceActivity = Long.MAX_VALUE
    private var consecutiveSpeechLikeWindows = 0
    private var speechLikeMinRms = Double.POSITIVE_INFINITY
    private var speechLikeMaxRms = 0.0
    private var speechLikeActivityDetected = false
    private var samplesSinceSpeechLikeActivity = Long.MAX_VALUE

    fun observe(samples: FloatArray) {
        for (sample in samples) {
            squareSum += sample * sample
            if (hasPreviousSample && (sample >= 0.0f) != (previousSample >= 0.0f)) {
                zeroCrossingsInWindow += 1
            }
            previousSample = sample
            hasPreviousSample = true
            samplesInWindow += 1
            if (samplesInWindow < windowSamples) continue

            val rms = sqrt(squareSum / samplesInWindow)
            val active = rms >= rmsThreshold
            consecutiveActiveWindows = if (active) consecutiveActiveWindows + 1 else 0
            if (consecutiveActiveWindows >= requiredActiveWindows) {
                samplesSinceActivity = 0L
            } else if (samplesSinceActivity != Long.MAX_VALUE) {
                samplesSinceActivity += samplesInWindow
            }
            val zeroCrossingRate = zeroCrossingsInWindow.toDouble() / (samplesInWindow - 1).coerceAtLeast(1)
            val speechLikeWindow = active && zeroCrossingRate in MIN_SPEECH_ZCR..MAX_SPEECH_ZCR
            if (speechLikeWindow) {
                consecutiveSpeechLikeWindows += 1
                speechLikeMinRms = minOf(speechLikeMinRms, rms)
                speechLikeMaxRms = maxOf(speechLikeMaxRms, rms)
                if (
                    consecutiveSpeechLikeWindows >= requiredActiveWindows &&
                    speechLikeMaxRms >= speechLikeMinRms * MIN_SPEECH_ENERGY_RATIO
                ) {
                    speechLikeActivityDetected = true
                    samplesSinceSpeechLikeActivity = 0L
                }
            } else {
                consecutiveSpeechLikeWindows = 0
                speechLikeMinRms = Double.POSITIVE_INFINITY
                speechLikeMaxRms = 0.0
            }
            if (samplesSinceSpeechLikeActivity != Long.MAX_VALUE && samplesSinceSpeechLikeActivity != 0L) {
                samplesSinceSpeechLikeActivity += samplesInWindow
            } else if (samplesSinceSpeechLikeActivity == 0L && !speechLikeWindow) {
                samplesSinceSpeechLikeActivity += samplesInWindow
            }
            squareSum = 0.0
            samplesInWindow = 0
            zeroCrossingsInWindow = 0
            hasPreviousSample = false
        }
    }

    fun hasRecentActivity(): Boolean = samplesSinceActivity <= recentSamples

    fun hasSpeechLikeActivity(): Boolean = speechLikeActivityDetected

    fun hasRecentSpeechLikeActivity(): Boolean = samplesSinceSpeechLikeActivity <= recentSamples

    companion object {
        // Three consecutive 20 ms windows above -40 dBFS reject isolated clicks. This evidence can
        // only grant one bounded confirmation window; it never marks speech by itself.
        private const val WINDOWS_PER_SECOND = 50
        private const val DEFAULT_RMS_THRESHOLD = 0.01f
        private const val DEFAULT_REQUIRED_ACTIVE_WINDOWS = 3
        private const val RECENT_ACTIVITY_MS = 300
        private const val MIN_SPEECH_ZCR = 0.005
        private const val MAX_SPEECH_ZCR = 0.35
        private const val MIN_SPEECH_ENERGY_RATIO = 3.0
    }
}
