package com.amphion.asr.internal

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class StreamingAgcIngressTest {

    @Test
    fun acceptAndFlushDeliverEveryFrameOnceAndInOrder() {
        val processor = RecordingProcessor()
        var guardDepth = 0
        val ingress = StreamingAgcIngress(processor) { _, produce ->
            guardDepth += 1
            try {
                produce()
            } finally {
                guardDepth -= 1
            }
        }
        val delivered = ArrayList<ProcessedAudioFrame>()

        ingress.accept(floatArrayOf(1f, 2f)) {
            assertEquals(0, guardDepth)
            delivered.add(it)
        }
        ingress.accept(floatArrayOf(3f)) {
            assertEquals(0, guardDepth)
            delivered.add(it)
        }
        ingress.flush("agc.flush(test)") {
            assertEquals(0, guardDepth)
            delivered.add(it)
        }

        assertEquals(3, delivered.size)
        assertArrayEquals(floatArrayOf(1f, 2f), delivered[0].raw, 0f)
        assertArrayEquals(floatArrayOf(11f, 12f), delivered[0].processed, 0f)
        assertArrayEquals(floatArrayOf(3f), delivered[1].raw, 0f)
        assertArrayEquals(floatArrayOf(13f), delivered[1].processed, 0f)
        assertArrayEquals(floatArrayOf(99f), delivered[2].raw, 0f)
        assertArrayEquals(floatArrayOf(109f), delivered[2].processed, 0f)
        assertEquals(2, processor.acceptCalls)
        assertEquals(1, processor.finishCalls)
    }

    @Test
    fun closeOwnsProcessorLifecycleAndIsIdempotent() {
        val processor = RecordingProcessor()
        val ingress = StreamingAgcIngress(processor) { _, produce -> produce() }

        ingress.close()
        ingress.close()

        assertEquals(1, processor.closeCalls)
    }

    private class RecordingProcessor : AgcFrameProcessor {
        var acceptCalls = 0
        var finishCalls = 0
        var closeCalls = 0

        override fun process(samples: FloatArray): List<ProcessedAudioFrame> {
            acceptCalls += 1
            return listOf(
                ProcessedAudioFrame(
                    samples.copyOf(),
                    FloatArray(samples.size) { samples[it] + 10f },
                ),
            )
        }

        override fun flush(): List<ProcessedAudioFrame> {
            finishCalls += 1
            return listOf(ProcessedAudioFrame(floatArrayOf(99f), floatArrayOf(109f)))
        }

        override fun close() {
            closeCalls += 1
        }
    }
}
