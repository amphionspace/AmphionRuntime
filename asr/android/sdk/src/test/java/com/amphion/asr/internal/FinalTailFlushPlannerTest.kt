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
}
