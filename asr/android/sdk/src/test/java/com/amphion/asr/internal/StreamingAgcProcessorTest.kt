package com.amphion.asr.internal

import com.amphion.asr.AmphionLogLevel
import com.amphion.asr.AsrErrorCode
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamingAgcProcessorTest {

    @Test
    fun automaticAgcIsChunkInvariantAndFlushPreservesRemainder() {
        val input = FloatArray(327) { index -> (index - 160) / 640f }

        val oneChunk = processInChunks(input, intArrayOf(input.size))
        val fragmented = processInChunks(input, intArrayOf(1, 73, 86, 160, 7))

        assertArrayEquals(input, oneChunk.first, 0f)
        assertArrayEquals(input, fragmented.first, 0f)
        assertArrayEquals(oneChunk.second, fragmented.second, 0f)
        assertArrayEquals(FloatArray(input.size) { input[it] * 2f }, oneChunk.second, 0f)
    }

    @Test
    fun backendFailureIsMappedToNativeCrashInsteadOfEscapingDecoderTask() {
        Logger.setLevel(AmphionLogLevel.NONE)
        try {
            val processor = StreamingAgcProcessor(16_000) { FailingBackend() }

            val result = NativeGuard.run("agc.process") {
                processor.process(FloatArray(160))
            }

            assertTrue(result is NativeResult.Err)
            assertEquals(AsrErrorCode.NATIVE_CRASH, (result as NativeResult.Err).error.code)
        } finally {
            Logger.setLevel(AmphionLogLevel.WARN)
        }
    }

    @Test
    fun internalTenMillisecondFramesKeepOneDecoderSubmissionPerCallerChunk() {
        var backendCalls = 0
        val processor = StreamingAgcProcessor(16_000) {
            object : AgcBackend {
                override fun process(frame: FloatArray): FloatArray {
                    backendCalls += 1
                    return frame.copyOf()
                }

                override fun close() = Unit
            }
        }

        val output = processor.process(FloatArray(320))

        assertEquals(2, backendCalls)
        assertEquals(1, output.size)
        assertEquals(320, output.single().raw.size)
        assertEquals(320, output.single().processed.size)
    }

    @Test
    fun largeCallerChunkIsAggregatedWithoutChangingSamples() {
        val input = FloatArray(16_000 * 60) { index -> (index % 257 - 128) / 512f }
        val processor = StreamingAgcProcessor(16_000) { DoublingBackend() }

        val output = processor.process(input).single()

        assertArrayEquals(input, output.raw, 0f)
        assertArrayEquals(FloatArray(input.size) { input[it] * 2f }, output.processed, 0f)
    }

    private fun processInChunks(input: FloatArray, chunkSizes: IntArray): Pair<FloatArray, FloatArray> {
        val processor = StreamingAgcProcessor(16_000) { DoublingBackend() }
        val frames = ArrayList<ProcessedAudioFrame>()
        var offset = 0
        for (size in chunkSizes) {
            frames += processor.process(input.copyOfRange(offset, offset + size))
            offset += size
        }
        frames += processor.flush()
        processor.close()
        return frames.flatMap { it.raw.asIterable() }.toFloatArray() to
            frames.flatMap { it.processed.asIterable() }.toFloatArray()
    }

    private class DoublingBackend : AgcBackend {
        override fun process(frame: FloatArray): FloatArray = FloatArray(frame.size) { frame[it] * 2f }
        override fun close() = Unit
    }

    private class FailingBackend : AgcBackend {
        override fun process(frame: FloatArray): FloatArray =
            throw UnsatisfiedLinkError("AGC library unavailable")

        override fun close() = Unit
    }
}
