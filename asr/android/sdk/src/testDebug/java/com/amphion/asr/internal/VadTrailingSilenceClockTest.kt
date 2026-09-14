package com.amphion.asr.internal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VadTrailingSilenceClockTest {
    @Test
    fun twentyMillisecondCallerFramesCountThirtyTwoMillisecondVadWindows() {
        val clock = VadTrailingSilenceClock(sampleRate = 16_000, endpointSilenceMs = 800)
        var carry = 0
        repeat(39) {
            carry += 320
            val consumed = carry / 512 * 512
            carry -= consumed
            assertFalse(clock.observeSilence(consumed))
        }
        carry += 320
        val consumed = carry / 512 * 512
        assertTrue(clock.observeSilence(consumed))
        assertEquals(800L, clock.elapsedMs())
    }

    @Test
    fun sameSilenceHasSameDecisionWithLargeOrSmallCallerFrames() {
        val small = VadTrailingSilenceClock(16_000, 800)
        val large = VadTrailingSilenceClock(16_000, 800)
        repeat(24) { assertFalse(small.observeSilence(512)) }
        assertFalse(large.observeSilence(24 * 512))
        assertTrue(small.observeSilence(512))
        assertTrue(large.observeSilence(512))
        assertEquals(small.elapsedMs(), large.elapsedMs())
    }

    @Test
    fun speechResetAndDisabledEndpointPreserveAdjacentBehavior() {
        val clock = VadTrailingSilenceClock(16_000, 800)
        assertFalse(clock.observeSilence(12 * 512))
        clock.reset()
        assertFalse(clock.observeSilence(12 * 512))
        assertFalse(VadTrailingSilenceClock(16_000, 0).observeSilence(100 * 512))
    }
}
