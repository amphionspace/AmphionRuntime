package com.amphion.dingqiao.demo

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class PcmFrameWriterTest {

    @Test
    fun flushFinalFramePadsTailExactlyOnce() {
        val frames = mutableListOf<ByteArray>()
        val writer = PcmFrameWriter(frameBytes = 8) { frames += it }
        writer.accept(shortArrayOf(1, 2, 3, 4, 5))

        writer.flushFinalFrame()
        writer.flushFinalFrame()

        assertEquals(2, frames.size)
        assertArrayEquals(shortArrayOf(1, 2, 3, 4), frames[0].toShorts())
        assertArrayEquals(shortArrayOf(5, 0, 0, 0), frames[1].toShorts())
    }

    private fun ByteArray.toShorts(): ShortArray {
        val buffer = ByteBuffer.wrap(this).order(ByteOrder.LITTLE_ENDIAN)
        return ShortArray(size / 2) { buffer.short }
    }
}
