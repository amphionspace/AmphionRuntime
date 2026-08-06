package com.lits.tts.sdk.internal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class LitsTtsOrtRuntimeTest {
    @Test
    fun streamingRuntimeDefaultsToNoCacheAndSixteenFrameDecoderLeftContext() {
        assertFalse(LitsTtsRuntimeOptions.decoderCacheEnabled)
        assertEquals(16, LitsTtsRuntimeOptions.decoderLeftContextFrames)
    }

    @Test
    fun streamingChunkSlicesCanUseSmallerFirstChunk() {
        val slices = LitsTtsOrtRuntime.buildStreamingChunkSlices(
            melLength = 370,
            firstChunkSize = 50,
            chunkSize = 100,
        )

        assertEquals(listOf(0, 50, 150, 250), slices.map { it.startIdx })
        assertEquals(listOf(50, 100, 100, 100), slices.map { it.chunkSize })
        assertEquals(listOf(0, 50, 100, 100), slices.map { it.previousChunkSize })
    }

    @Test
    fun streamingChunkSlicesKeepSingleFinalSliceForShortAudio() {
        val slices = LitsTtsOrtRuntime.buildStreamingChunkSlices(
            melLength = 40,
            firstChunkSize = 50,
            chunkSize = 100,
        )

        assertEquals(listOf(0), slices.map { it.startIdx })
        assertEquals(listOf(50), slices.map { it.chunkSize })
        assertEquals(listOf(0), slices.map { it.previousChunkSize })
    }

    @Test
    fun streamingChunkSlicesSupportTestV4DynamicGrowth() {
        val slices = LitsTtsOrtRuntime.buildStreamingChunkSlices(
            melLength = 700,
            firstChunkSize = 25,
            chunkSize = 50,
            secondChunkSize = 50,
            steadyChunkSize = 100,
            chunkGrowthFactor = 2,
            maxChunkSize = 200,
        )

        assertEquals(listOf(0, 25, 75, 175, 375, 575), slices.map { it.startIdx })
        assertEquals(listOf(25, 50, 100, 200, 200, 200), slices.map { it.chunkSize })
        assertEquals(listOf(0, 25, 50, 100, 200, 200), slices.map { it.previousChunkSize })
    }
}
