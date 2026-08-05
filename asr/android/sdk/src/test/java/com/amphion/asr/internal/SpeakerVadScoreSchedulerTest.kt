package com.amphion.asr.internal

import org.junit.Assert.assertEquals
import org.junit.Test

class SpeakerVadScoreSchedulerTest {
    @Test
    fun scoreDeadlinesDoNotDependOnCallerPcmPartitioning() {
        val totalSamples = 32_000
        val realtime = List(totalSamples / 320) { 320 }
        val irregular = buildList {
            val pattern = intArrayOf(160, 1_120, 640, 2_400, 320, 3_040)
            var remaining = totalSamples
            var index = 0
            while (remaining > 0) {
                val size = minOf(remaining, pattern[index % pattern.size])
                add(size)
                remaining -= size
                index += 1
            }
        }

        val expected = listOf(16_000, 19_200, 24_000, 28_800)
        assertEquals(expected, scoreDeadlines(realtime))
        assertEquals(expected, scoreDeadlines(irregular))
        assertEquals(expected, scoreDeadlines(listOf(totalSamples)))
    }

    @Test
    fun resetReanchorsDeadlinesToTheNextNativeSegment() {
        val scheduler = SpeakerVadScoreScheduler(windowSamples = 16_000, hopSamples = 4_800)
        assertEquals(16_000, scheduler.samplesUntilNextScore())
        assertEquals(true, scheduler.observe(16_000))
        assertEquals(3_200, scheduler.samplesUntilNextScore())

        scheduler.reset()

        assertEquals(16_000, scheduler.samplesUntilNextScore())
        assertEquals(false, scheduler.observe(8_000))
        assertEquals(8_000, scheduler.samplesUntilNextScore())
    }

    @Test
    fun windowShorterThanHopDoesNotScoreBeforeTheFirstHop() {
        val scheduler = SpeakerVadScoreScheduler(windowSamples = 8_000, hopSamples = 16_000)

        assertEquals(16_000, scheduler.samplesUntilNextScore())
        assertEquals(true, scheduler.observe(16_000))
        assertEquals(16_000, scheduler.samplesUntilNextScore())
    }

    private fun scoreDeadlines(partitions: List<Int>): List<Int> {
        val scheduler = SpeakerVadScoreScheduler(windowSamples = 16_000, hopSamples = 4_800)
        val deadlines = mutableListOf<Int>()
        for (partition in partitions) {
            var remaining = partition
            while (remaining > 0) {
                val accepted = minOf(remaining, scheduler.samplesUntilNextScore())
                if (scheduler.observe(accepted)) deadlines += scheduler.totalSamples
                remaining -= accepted
            }
        }
        return deadlines
    }
}
