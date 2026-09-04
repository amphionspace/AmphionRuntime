package com.amphion.asr.internal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FinalTailFlushPlannerTest {
    @Test
    fun all20MsChunkPhasesReceiveTwoDecodeOpportunities() {
        for (phaseMs in 0 until 640 step 20) {
            val planner = FinalTailFlushPlanner(stepMs = 20, maxPaddingMs = 1280, requiredDecodes = 2)
            var readyAudioMs = phaseMs
            while (!planner.isComplete) {
                if (readyAudioMs >= 640) {
                    readyAudioMs -= 640
                    planner.recordDecode()
                    continue
                }
                val paddingMs = planner.nextPaddingMs()
                assertTrue(paddingMs > 0)
                planner.recordPadding(paddingMs)
                readyAudioMs += paddingMs
            }
            assertEquals(2, planner.decodeOpportunities)
            assertEquals(1280 - phaseMs, planner.paddingDurationMs)
            assertFalse(planner.usedFallback)
        }
    }

    @Test
    fun neverReadyStopsAtTheExisting1280MsCap() {
        val planner = FinalTailFlushPlanner(stepMs = 20, maxPaddingMs = 1280, requiredDecodes = 2)
        while (!planner.isComplete) {
            val paddingMs = planner.nextPaddingMs()
            if (paddingMs == 0) break
            planner.recordPadding(paddingMs)
        }
        assertEquals(1280, planner.paddingDurationMs)
        assertEquals(0, planner.decodeOpportunities)
        assertTrue(planner.usedFallback)
    }

    @Test
    fun singleDecodeRequiresTheFull320MsRightContextMargin() {
        val below = FinalTailFlushPlanner(
            stepMs = 20,
            maxPaddingMs = 1280,
            requiredDecodes = 2,
            singleDecodeMinPaddingMs = 320,
        )
        repeat(15) { below.recordPadding(20) }
        below.recordDecode()
        assertFalse(below.isComplete)

        val boundary = FinalTailFlushPlanner(
            stepMs = 20,
            maxPaddingMs = 1280,
            requiredDecodes = 2,
            singleDecodeMinPaddingMs = 320,
        )
        repeat(16) { boundary.recordPadding(20) }
        boundary.recordDecode()
        assertTrue(boundary.isComplete)
        assertEquals(1, boundary.decodeOpportunities)
    }

    @Test
    fun laterPaddingCannotRetroactivelyQualifyTheFirstDecode() {
        val planner = FinalTailFlushPlanner(
            stepMs = 20,
            maxPaddingMs = 1280,
            requiredDecodes = 2,
            singleDecodeMinPaddingMs = 320,
        )
        repeat(15) { planner.recordPadding(20) }
        planner.recordDecode()
        planner.recordPadding(20)
        assertFalse(planner.isComplete)
        planner.recordDecode()
        assertTrue(planner.isComplete)
        assertEquals(2, planner.decodeOpportunities)
    }

    @Test
    fun rightContextGateIsSafeForEvery20MsChunkPhase() {
        for (phaseMs in 0 until 640 step 20) {
            val planner = FinalTailFlushPlanner(
                stepMs = 20,
                maxPaddingMs = 1280,
                requiredDecodes = 2,
                singleDecodeMinPaddingMs = 320,
            )
            var readyAudioMs = phaseMs
            while (!planner.isComplete) {
                if (readyAudioMs >= 640) {
                    readyAudioMs -= 640
                    planner.recordDecode()
                    continue
                }
                val paddingMs = planner.nextPaddingMs()
                assertTrue(paddingMs > 0)
                planner.recordPadding(paddingMs)
                readyAudioMs += paddingMs
            }
            val firstPaddingMs = 640 - phaseMs
            assertEquals(if (firstPaddingMs >= 320) 1 else 2, planner.decodeOpportunities)
            assertTrue(planner.paddingDurationMs <= 1280)
            assertFalse(planner.usedFallback)
        }
    }

    @Test
    fun speakerRedecodeRequires800MsEvenWhenDecodeIsReadyEarly() {
        val planner = FinalTailFlushPlanner(
            stepMs = 20,
            maxPaddingMs = 1280,
            requiredDecodes = 2,
            singleDecodeMinPaddingMs = 320,
            minimumPaddingMs = 800,
        )
        planner.recordDecode()
        planner.recordDecode()
        assertFalse(planner.isComplete)
        repeat(39) { planner.recordPadding(20) }
        assertFalse(planner.isComplete)
        planner.recordPadding(20)
        assertTrue(planner.isComplete)
        assertEquals(800, planner.paddingDurationMs)
        assertEquals(2, planner.decodeOpportunities)
    }

    @Test
    fun speakerMinimumPaddingDisablesTheSingleDecodeShortcut() {
        val planner = FinalTailFlushPlanner(
            stepMs = 20,
            maxPaddingMs = 1280,
            requiredDecodes = 2,
            singleDecodeMinPaddingMs = 320,
            minimumPaddingMs = 800,
        )
        repeat(16) { planner.recordPadding(20) }
        planner.recordDecode()
        repeat(24) { planner.recordPadding(20) }
        assertFalse(planner.isComplete)
        planner.recordDecode()
        assertTrue(planner.isComplete)
    }
}
