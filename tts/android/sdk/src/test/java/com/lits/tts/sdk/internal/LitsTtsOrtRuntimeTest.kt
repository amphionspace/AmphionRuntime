package com.lits.tts.sdk.internal

import org.junit.Assert.assertEquals
import org.junit.Test

class LitsTtsOrtRuntimeTest {
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
}
