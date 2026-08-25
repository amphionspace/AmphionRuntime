package com.amphion.asr.internal

import java.io.Closeable

internal data class ProcessedAudioFrame(
    val raw: FloatArray,
    val processed: FloatArray,
)

internal interface AgcBackend : Closeable {
    /** Process exactly one 10 ms mono PCM frame and return the same sample count. */
    fun process(frame: FloatArray): FloatArray
}

/**
 * Converts arbitrary caller chunks into the fixed 10 ms frames required by WebRTC AGC2.
 *
 * Raw and processed samples stay paired so VAD and speaker verification keep using the original
 * waveform while only ASR consumes the normalized waveform. This object is decoder-thread only.
 */
internal class StreamingAgcProcessor(
    sampleRate: Int,
    private val backendFactory: () -> AgcBackend = { NativeAgcBackend(sampleRate) },
) : AgcFrameProcessor {

    private val frameSamples = (sampleRate / FRAMES_PER_SECOND).also {
        require(sampleRate > 0 && sampleRate % FRAMES_PER_SECOND == 0) {
            "sampleRate must have an integral 10ms frame, got $sampleRate"
        }
    }
    private var carry = FloatArray(0)
    private var backend: AgcBackend? = null
    private var closed = false

    override fun process(samples: FloatArray): List<ProcessedAudioFrame> {
        check(!closed) { "AGC processor is closed" }
        if (samples.isEmpty()) return emptyList()
        val merged = if (carry.isEmpty()) samples else carry + samples
        val completeSamples = merged.size / frameSamples * frameSamples
        if (completeSamples == 0) {
            carry = merged.copyOf()
            return emptyList()
        }
        val rawOutput = FloatArray(completeSamples)
        val processedOutput = FloatArray(completeSamples)
        var offset = 0
        while (offset < completeSamples) {
            val raw = merged.copyOfRange(offset, offset + frameSamples)
            val frame = processFrame(raw)
            frame.raw.copyInto(rawOutput, offset)
            frame.processed.copyInto(processedOutput, offset)
            offset += frameSamples
        }
        carry = if (offset < merged.size) merged.copyOfRange(offset, merged.size) else FloatArray(0)
        // Keep WebRTC's 10 ms processing contract internal. The decoder should retain the caller's
        // submission granularity instead of paying one decode dispatch per AGC frame.
        return listOf(ProcessedAudioFrame(rawOutput, processedOutput))
    }

    override fun flush(): List<ProcessedAudioFrame> {
        check(!closed) { "AGC processor is closed" }
        if (carry.isEmpty()) return emptyList()

        val raw = carry
        carry = FloatArray(0)
        val padded = raw.copyOf(frameSamples)
        val processed = processFrame(padded).processed.copyOf(raw.size)
        return listOf(ProcessedAudioFrame(raw, processed))
    }

    private fun processFrame(raw: FloatArray): ProcessedAudioFrame {
        val processed = (backend ?: backendFactory().also { backend = it }).process(raw)
        check(processed.size == raw.size) {
            "AGC backend changed frame size: ${raw.size} -> ${processed.size}"
        }
        return ProcessedAudioFrame(raw, processed)
    }

    override fun close() {
        if (closed) return
        closed = true
        carry = FloatArray(0)
        backend?.close()
        backend = null
    }

    private companion object {
        const val FRAMES_PER_SECOND = 100
    }
}
