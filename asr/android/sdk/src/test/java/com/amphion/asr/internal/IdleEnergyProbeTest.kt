package com.amphion.asr.internal

import kotlin.math.PI
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class IdleEnergyProbeTest {
    private val sr = 16_000
    private val windowSamples = sr / 50
    private val partitions = listOf(
        intArrayOf(160),
        intArrayOf(320),
        intArrayOf(1_600),
        intArrayOf(16_000),
        intArrayOf(13, 307, 1, 509, 73),
    )

    private fun noise(n: Int, amp: Float, seed: Int = 1): FloatArray {
        var s = seed.toLong()
        return FloatArray(n) {
            s = s * 6364136223846793005L + 1442695040888963407L
            amp * (((s ushr 33) % 2001) / 1000f - 1f)
        }
    }

    private fun tone(n: Int, amp: Float) =
        FloatArray(n) { (amp * sin(2 * PI * 440 * it / sr)).toFloat() }

    private fun firstWakeAt(samples: FloatArray, chunks: IntArray): Int? {
        val p = IdleEnergyProbe(sr)
        p.arm()
        var offset = 0
        var chunk = 0
        while (offset < samples.size) {
            val end = minOf(samples.size, offset + chunks[chunk % chunks.size])
            if (p.observe(samples.copyOfRange(offset, end))) return end
            offset = end
            chunk += 1
        }
        return null
    }

    private fun callbackEndContaining(sample: Int, chunks: IntArray): Int {
        var end = 0
        var chunk = 0
        while (end < sample) {
            end += chunks[chunk % chunks.size]
            chunk += 1
        }
        return end
    }

    @Test
    fun digitalSilenceThenAnySignalWakes() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        repeat(5) { assertFalse(p.observe(FloatArray(windowSamples))) }
        assertTrue("数字静音后任何可闻信号都要唤醒", p.observe(tone(windowSamples, 0.01f)))
    }

    @Test
    fun steadyAudibleRoomNoiseConservativelyWakes() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        // 能量不能区分稳态环境声与持续讲话；可闻输入优先唤醒，不能先学成噪声底。
        repeat(100) { assertTrue(p.observe(noise(windowSamples, 0.01f, it))) }
    }

    @Test
    fun steadySubthresholdNoiseDoesNotWake() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        repeat(100) { assertFalse(p.observe(noise(windowSamples, 0.0001f, it))) }
    }

    @Test
    fun relativeRiseBelowAbsoluteThresholdStillWakes() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        repeat(50) { assertFalse(p.observe(noise(windowSamples, 0.00001f, it))) }
        assertTrue(p.observe(tone(windowSamples, 0.00005f)))
    }

    @Test
    fun immediateAudibleInputWakesForEveryPartition() {
        val samples = tone(sr * 2, 0.01f)
        for (chunks in partitions) {
            assertEquals(
                "arm 后首个完整音频窗必须唤醒，分帧=${chunks.contentToString()}",
                callbackEndContaining(windowSamples, chunks),
                firstWakeAt(samples, chunks),
            )
        }
    }

    @Test
    fun shortOnsetAtEndOfSilenceWakesForEveryPartition() {
        val samples = FloatArray(sr * 2)
        tone(windowSamples, 0.003f).copyInto(samples, sr - windowSamples)
        for (chunks in partitions) {
            assertEquals(
                "静音末尾的 20ms 起音不能被大调用块吞掉，分帧=${chunks.contentToString()}",
                callbackEndContaining(sr, chunks),
                firstWakeAt(samples, chunks),
            )
        }
    }

    @Test
    fun shortAudibleWindowIsNotDilutedByLargeQuietChunk() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        repeat(5) { assertFalse(p.observe(noise(windowSamples, 0.0005f, it))) }
        val samples = FloatArray(sr)
        tone(windowSamples, 0.003f).copyInto(samples, sr - windowSamples)
        assertTrue("每个 20ms 窗单独判断，不能使用整秒平均 RMS", p.observe(samples))
    }

    @Test
    fun quietRiseFromDigitalSilenceWakes() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        repeat(3) { assertFalse(p.observe(FloatArray(windowSamples))) }
        assertTrue(p.observe(tone(windowSamples, 0.00001f)))
    }

    @Test
    fun disarmedProbeIsInert() {
        val p = IdleEnergyProbe(sr)
        assertFalse(p.observe(tone(windowSamples, 0.5f)))
        p.arm()
        repeat(3) { p.observe(FloatArray(windowSamples)) }
        p.disarm()
        assertFalse(p.observe(tone(windowSamples, 0.5f)))
    }

    @Test
    fun rearmingDoesNotRequireWarmup() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        assertTrue(p.observe(tone(windowSamples, 0.5f)))
        p.disarm()
        p.arm()
        assertTrue(p.observe(tone(windowSamples, 0.5f)))
    }

    @Test
    fun floorRisesSlowlySoAbruptQuietStretchStillWakes() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        repeat(50) { assertFalse(p.observe(noise(windowSamples, 0.000005f, it))) }
        assertTrue(p.observe(noise(windowSamples, 0.0001f, 7)))
    }

    @Test
    fun arbitraryFragmentsKeepDecisionAtAudioWindowBoundary() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        assertEquals(320, p.samplesUntilNextDecision)
        assertFalse(p.observe(FloatArray(159)))
        assertEquals(161, p.samplesUntilNextDecision)
        assertFalse(p.observe(FloatArray(160)))
        assertEquals(1, p.samplesUntilNextDecision)
        assertTrue(p.observe(floatArrayOf(0.5f)))
        assertEquals(320, p.samplesUntilNextDecision)
    }

    @Test
    fun rearmDiscardsUnfinishedOldWindow() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        assertFalse(p.observe(FloatArray(319) { 0.5f }))
        p.disarm()
        p.arm()
        assertEquals(320, p.samplesUntilNextDecision)
        assertFalse(p.observe(FloatArray(320)))
    }

    @Test
    fun largeChunkKeepsWakeDecisionWhenItsLastWindowIsSilent() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        val samples = FloatArray(sr)
        tone(windowSamples, 0.003f).copyInto(samples)
        assertTrue(p.observe(samples))
        assertEquals(320, p.samplesUntilNextDecision)
    }

    @Test
    fun subthresholdNoiseRemainsQuietForEveryPartition() {
        val samples = noise(sr * 2, 0.0001f)
        for (chunks in partitions) {
            assertEquals("稳定微弱噪声，分帧=${chunks.contentToString()}", null, firstWakeAt(samples, chunks))
        }
    }

    @Test
    fun emptyCallsDoNotConsumePendingAudio() {
        val p = IdleEnergyProbe(sr)
        p.arm()
        val samples = tone(windowSamples, 0.5f)
        assertFalse(p.observe(samples.copyOfRange(0, 160)))
        assertFalse(p.observe(FloatArray(0)))
        assertTrue(p.observe(samples.copyOfRange(160, samples.size)))
    }
}
