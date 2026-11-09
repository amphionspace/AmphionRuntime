package com.amphion.asr.internal

import kotlin.math.PI
import kotlin.math.sin
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class IdleEnergyProbeTest {
    private val sr = 16_000
    private fun noise(n: Int, amp: Float, seed: Int = 1): FloatArray {
        var s = seed.toLong()
        return FloatArray(n) { s = (s * 6364136223846793005L + 1442695040888963407L); amp * (((s ushr 33) % 2001) / 1000f - 1f) }
    }
    private fun tone(n: Int, amp: Float) = FloatArray(n) { (amp * sin(2 * PI * 440 * it / sr)).toFloat() }

    @Test
    fun digitalSilenceThenAnySignalWakes() {
        val p = IdleEnergyProbe(sr); p.arm()
        repeat(5) { assertFalse(p.observe(FloatArray(320))) }
        assertTrue("数字静音后任何可闻信号都要唤醒", p.observe(tone(320, 0.01f)))
    }

    @Test
    fun steadyRoomNoiseDoesNotWake() {
        val p = IdleEnergyProbe(sr); p.arm()
        repeat(100) { assertFalse("稳定噪声底不能唤醒", p.observe(noise(320, 0.01f, it))) }
    }

    @Test
    fun speechAboveNoiseFloorWakes() {
        val p = IdleEnergyProbe(sr); p.arm()
        repeat(50) { p.observe(noise(320, 0.01f, it)) }          // 底 ≈ -45 dBFS
        assertTrue(p.observe(tone(320, 0.06f)))                   // ≈ -27 dBFS，高出 18 dB
    }

    @Test
    fun warmupChunksNeverWake() {
        val p = IdleEnergyProbe(sr); p.arm()
        assertFalse(p.observe(tone(320, 0.5f)))
        assertFalse(p.observe(tone(320, 0.5f)))
    }

    @Test
    fun disarmedProbeIsInert() {
        val p = IdleEnergyProbe(sr)
        assertFalse(p.observe(tone(320, 0.5f)))
        p.arm(); repeat(3) { p.observe(FloatArray(320)) }; p.disarm()
        assertFalse(p.observe(tone(320, 0.5f)))
    }

    @Test
    fun floorRisesSlowlySoABruptLoudStretchStillWakes() {
        val p = IdleEnergyProbe(sr); p.arm()
        repeat(50) { p.observe(noise(320, 0.005f, it)) }
        // 突然持续变响（像有人开始讲话）：第一个 chunk 就该报，而不是等噪声底追上来
        assertTrue(p.observe(noise(320, 0.1f, 7)))
    }
}
