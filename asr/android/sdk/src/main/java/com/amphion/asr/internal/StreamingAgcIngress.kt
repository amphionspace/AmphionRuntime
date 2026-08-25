package com.amphion.asr.internal

import java.io.Closeable

/** Produces paired raw/processed frames for the session in submission order. */
internal interface AgcFrameProcessor : Closeable {
    fun process(samples: FloatArray): List<ProcessedAudioFrame>
    fun flush(): List<ProcessedAudioFrame>
}

/**
 * Owns the session-to-AGC seam: every produced frame is delivered exactly once and a flush drains
 * the processor remainder through the same consumer before the session changes stream state.
 */
internal class StreamingAgcIngress(
    private val processor: AgcFrameProcessor,
    private val guard: (
        operation: String,
        produce: () -> List<ProcessedAudioFrame>,
    ) -> List<ProcessedAudioFrame>?,
) : Closeable {
    private var closed = false

    fun accept(samples: FloatArray, consume: (ProcessedAudioFrame) -> Unit): Boolean {
        check(!closed) { "AGC ingress is closed" }
        val frames = guard("agc.process") { processor.process(samples) } ?: return false
        frames.forEach(consume)
        return true
    }

    fun flush(operation: String, consume: (ProcessedAudioFrame) -> Unit): Boolean {
        check(!closed) { "AGC ingress is closed" }
        val frames = guard(operation) { processor.flush() } ?: return false
        frames.forEach(consume)
        return true
    }

    override fun close() {
        if (closed) return
        closed = true
        processor.close()
    }
}
