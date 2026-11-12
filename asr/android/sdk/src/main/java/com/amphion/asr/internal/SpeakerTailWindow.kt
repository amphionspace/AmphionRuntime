package com.amphion.asr.internal

import kotlin.math.sqrt

/**
 * Take the last [windowSamples] of *active speech* instead of the raw tail of the utterance.
 *
 * A finalized utterance necessarily carries its trailing silence, because the endpoint is what
 * closed it. A speaker-verification window taken from the raw tail can therefore be pure silence,
 * and the extractor cannot embed it: the finish-time departure check then returns without ever
 * deciding, so the next speaker's words stay inside the target's final. This helper walks back to
 * the last frame above a small fraction of the segment peak and ends the window there.
 *
 * Returns null when the segment has no active frame or holds less than one window of audio, which
 * keeps the caller's previous "cannot decide" behavior.
 */
internal fun speechAlignedTail(
    samples: FloatArray,
    windowSamples: Int,
    frameSamples: Int,
    relativeFloor: Float = DEFAULT_SPEECH_FLOOR_RATIO,
): FloatArray? {
    if (windowSamples <= 0 || frameSamples <= 0 || samples.size < windowSamples) return null
    fun frameRms(offset: Int): Float {
        var sum = 0.0
        val end = offset + frameSamples
        for (index in offset until end) sum += samples[index].toDouble() * samples[index]
        return sqrt(sum / frameSamples).toFloat()
    }
    var peak = 0f
    var offset = 0
    while (offset + frameSamples <= samples.size) {
        peak = maxOf(peak, frameRms(offset))
        offset += frameSamples
    }
    if (peak <= 0f) return null
    val floor = peak * relativeFloor
    var end = -1
    offset = samples.size - frameSamples
    while (offset >= 0) {
        if (frameRms(offset) >= floor) {
            end = offset + frameSamples
            break
        }
        offset -= frameSamples
    }
    if (end < windowSamples) return null
    return samples.copyOfRange(end - windowSamples, end)
}

internal const val DEFAULT_SPEECH_FLOOR_RATIO = 0.1f
