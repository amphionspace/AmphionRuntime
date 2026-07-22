package com.amphion.asr.internal

/**
 * Keeps native-stream Speaker VAD audio separate from public-utterance fallback audio.
 *
 * A token-only native endpoint clears the first buffer after the stream reset, but the second buffer
 * must survive until a public final so two short native segments can still reach the scoring minimum.
 */
internal class SpeakerPcmBuffers(maxSamples: Int) {
    private val maximumSamples = maxSamples.coerceAtLeast(1)
    private val speakerVadParts = mutableListOf<FloatArray>()
    private val fallbackParts = mutableListOf<FloatArray>()
    private var speakerVadSampleCount = 0
    private var fallbackSampleCount = 0

    fun observe(samples: FloatArray, captureSpeakerVad: Boolean, captureFallback: Boolean) {
        if (captureSpeakerVad) {
            val retained = minOf(samples.size, maximumSamples - speakerVadSampleCount)
            if (retained > 0) {
                speakerVadParts += samples.copyOf(retained)
                speakerVadSampleCount += retained
            }
        }
        if (captureFallback) {
            val retained = minOf(samples.size, maximumSamples - fallbackSampleCount)
            if (retained > 0) {
                fallbackParts += samples.copyOf(retained)
                fallbackSampleCount += retained
            }
        }
    }

    fun speakerVadLength(): Int = speakerVadSampleCount

    fun speakerVadTail(sampleCount: Int): FloatArray {
        val retained = sampleCount.coerceIn(0, speakerVadSampleCount)
        val output = FloatArray(retained)
        var destinationEnd = retained
        for (index in speakerVadParts.indices.reversed()) {
            if (destinationEnd == 0) break
            val part = speakerVadParts[index]
            val copied = minOf(part.size, destinationEnd)
            System.arraycopy(
                part,
                part.size - copied,
                output,
                destinationEnd - copied,
                copied,
            )
            destinationEnd -= copied
        }
        return output
    }

    fun fallbackSamples(): FloatArray = concatenate(fallbackParts, fallbackSampleCount)

    fun clearNativeSegment() {
        speakerVadParts.clear()
        speakerVadSampleCount = 0
    }

    fun clearPublicUtterance() {
        fallbackParts.clear()
        fallbackSampleCount = 0
    }

    fun clearAll() {
        clearNativeSegment()
        clearPublicUtterance()
    }

    private fun concatenate(parts: List<FloatArray>, total: Int): FloatArray {
        val output = FloatArray(total)
        var offset = 0
        for (part in parts) {
            System.arraycopy(part, 0, output, offset, part.size)
            offset += part.size
        }
        return output
    }
}
