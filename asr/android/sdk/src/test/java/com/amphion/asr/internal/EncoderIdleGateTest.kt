package com.amphion.asr.internal

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EncoderIdleGateTest {
    private fun ramp(from: Int, n: Int) = FloatArray(n) { (from + it).toFloat() }

    @Test
    fun startsActiveAndEnterIdleIsIdempotent() {
        val g = EncoderIdleGate(sampleRate = 1000, preRollMs = 100)
        assertFalse(g.idle)
        g.enterIdle()
        g.enterIdle()
        assertTrue(g.idle)
        assertEquals("重复 enterIdle 不能重复计数", 1, g.idleEntries)
    }

    @Test
    fun resumeReturnsPreRollInArrivalOrder() {
        val g = EncoderIdleGate(sampleRate = 1000, preRollMs = 100)   // 容量 100
        g.enterIdle()
        g.observe(ramp(0, 30))
        g.observe(ramp(30, 30))
        val out = g.resume()
        assertArrayEquals(ramp(0, 60), out, 0f)
        assertFalse(g.idle)
        assertEquals(60L, g.idleSamples)
        assertEquals(1, g.resumes)
        assertEquals("resume 后环必须清空", 0, g.bufferedSamples)
    }

    @Test
    fun ringKeepsOnlyTheNewestPreRoll() {
        val g = EncoderIdleGate(sampleRate = 1000, preRollMs = 100)
        g.enterIdle()
        g.observe(ramp(0, 70))
        g.observe(ramp(70, 70))        // 共 140，只留最后 100：40..139
        assertEquals(100, g.bufferedSamples)
        assertArrayEquals(ramp(40, 100), g.resume(), 0f)
        assertEquals(140L, g.idleSamples)
    }

    @Test
    fun oversizedChunkKeepsItsTail() {
        val g = EncoderIdleGate(sampleRate = 1000, preRollMs = 100)
        g.enterIdle()
        g.observe(ramp(0, 250))
        assertArrayEquals(ramp(150, 100), g.resume(), 0f)
        // 大 chunk 之后再来小 chunk，顺序仍然正确
        g.enterIdle()
        g.observe(ramp(0, 250))
        g.observe(ramp(250, 10))
        assertArrayEquals(ramp(160, 100), g.resume(), 0f)
    }

    @Test
    fun countersSurviveResetButBufferDoesNot() {
        val g = EncoderIdleGate(sampleRate = 1000, preRollMs = 100)
        g.enterIdle()
        g.observe(ramp(0, 50))
        g.reset()
        assertFalse(g.idle)
        assertEquals(0, g.bufferedSamples)
        assertEquals(50L, g.idleSamples)
        assertEquals(1, g.idleEntries)
    }

    @Test(expected = IllegalStateException::class)
    fun observeWhileActiveIsAProgrammingError() {
        EncoderIdleGate(1000, 100).observe(ramp(0, 10))
    }
}
