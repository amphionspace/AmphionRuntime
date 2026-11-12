package com.amphion.asr.internal

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeakerTailWindowTest {
    private val frame = 160 // 10 ms @16 kHz

    private fun tone(samples: Int, amplitude: Float): FloatArray =
        FloatArray(samples) { i -> if (i % 2 == 0) amplitude else -amplitude }

    @Test
    fun windowEndsAtLastActiveFrameInsteadOfTrailingSilence() {
        val speech = tone(32_000, 0.2f)          // 2 s 语音
        val silence = FloatArray(32_000)          // 2 s 静音
        val segment = speech + silence
        val rawTail = segment.copyOfRange(segment.size - 19_200, segment.size)
        assertTrue("raw tail must be pure silence in this fixture", rawTail.all { it == 0f })
        val tail = speechAlignedTail(segment, 19_200, frame)!!
        assertEquals(19_200, tail.size)
        // 对齐后必须含语音，且结束在语音末帧
        assertTrue(tail.any { it != 0f })
        assertTrue(tail.takeLast(frame).any { it != 0f })
    }

    @Test
    fun plainTailIsReturnedWhenTheSegmentEndsWithSpeech() {
        val speech = tone(32_000, 0.3f)
        val tail = speechAlignedTail(speech, 19_200, frame)!!
        assertArrayEquals(speech.copyOfRange(32_000 - 19_200, 32_000), tail, 0f)
    }

    @Test
    fun noActiveAudioAndTooShortSegmentsAreRejected() {
        assertNull(speechAlignedTail(FloatArray(40_000), 19_200, frame))
        assertNull(speechAlignedTail(tone(10_000, 0.2f), 19_200, frame))
    }
}
