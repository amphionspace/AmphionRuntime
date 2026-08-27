package com.amphion.dingqiao.demo

import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.sqrt

data class SdkPcmCaptureSnapshot(
    val pcm: ByteArray,
    val frameCount: Int,
    val durationMs: Long,
    val rmsDbfs: Double,
    val peak: Int,
    val clipSamples: Int,
    val truncated: Boolean,
)

/** Captures the exact fixed-size payloads attempted at the public SDK writeAudio boundary. */
class SdkPcmCapture(
    private val frameBytes: Int = 640,
    private val maxFrames: Int = CustomerScenarioProfiles.SESSION_ROTATE_AUDIO_MS / FRAME_AUDIO_MS,
) {
    private val frames = mutableListOf<ByteArray>()
    private var truncated = false

    @Synchronized
    fun reset() {
        frames.clear()
        truncated = false
    }

    @Synchronized
    fun capture(frame: ByteArray) {
        require(frame.size == frameBytes) { "expected $frameBytes bytes, got ${frame.size}" }
        if (frames.size >= maxFrames) {
            truncated = true
            return
        }
        frames += frame.copyOf()
    }

    @Synchronized
    fun snapshot(): SdkPcmCaptureSnapshot {
        val pcm = ByteArray(frames.size * frameBytes)
        frames.forEachIndexed { index, frame ->
            frame.copyInto(pcm, destinationOffset = index * frameBytes)
        }
        var sumSquares = 0.0
        var peak = 0
        var clipped = 0
        val samples = pcm.size / 2
        val buffer = ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN)
        repeat(samples) {
            val value = buffer.short.toInt()
            val magnitude = abs(value)
            sumSquares += value.toDouble() * value.toDouble()
            peak = maxOf(peak, magnitude)
            if (magnitude >= 32_767) clipped += 1
        }
        val rms = if (samples > 0) sqrt(sumSquares / samples) else 0.0
        val rmsDbfs = if (rms > 0.0) maxOf(-120.0, 20.0 * log10(rms / 32_768.0)) else -120.0
        return SdkPcmCaptureSnapshot(
            pcm = pcm,
            frameCount = frames.size,
            durationMs = pcm.size / 32L,
            rmsDbfs = rmsDbfs,
            peak = peak,
            clipSamples = clipped,
            truncated = truncated,
        )
    }

    private companion object {
        const val FRAME_AUDIO_MS = 20
    }
}
