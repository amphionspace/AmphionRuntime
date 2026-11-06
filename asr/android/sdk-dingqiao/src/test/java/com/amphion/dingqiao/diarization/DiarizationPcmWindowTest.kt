package com.amphion.dingqiao.diarization

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** 与鸿蒙 `DiarizationPcmWindow.ts` 同一契约：按绝对样本位置索引，取不到就返回 null，绝不返回错位音频。 */
class DiarizationPcmWindowTest {
    private val sr = 16_000

    private fun pcm(vararg samples: Int): ByteArray {
        val out = ByteArray(samples.size * 2)
        samples.forEachIndexed { i, s -> out[i * 2] = (s and 0xff).toByte(); out[i * 2 + 1] = ((s shr 8) and 0xff).toByte() }
        return out
    }

    @Test
    fun sliceReturnsTheExactSamplesNormalizedToUnitRange() {
        val w = DiarizationPcmWindow(1000, 10.0)          // 1 kHz 便于按毫秒数样本
        w.append(pcm(0, 16384, -16384, 32767, -32768))
        assertEquals(5L, w.totalSamples())
        val out = w.slice(1, 5)!!
        assertArrayEquals(floatArrayOf(0.5f, -0.5f, 32767 / 32768f, -1f), out, 1e-6f)
    }

    @Test
    fun oddTrailingByteIsDropped() {
        val w = DiarizationPcmWindow(sr, 1.0)
        w.append(byteArrayOf(1, 0, 2))
        assertEquals(1L, w.totalSamples())
    }

    @Test
    fun evictedAudioIsNullNotPartialAudio() {
        val w = DiarizationPcmWindow(1000, 2.0)            // 只留 2 秒
        w.append(ByteArray(5000 * 2))                      // 写入 5 秒
        assertEquals(3000L, w.earliestSample())
        assertNull("已覆盖的区间必须返回 null", w.slice(0, 1000))
        assertNull("跨越覆盖边界也必须返回 null", w.slice(2500, 3500))
        assertEquals(1000, w.slice(3500, 4500)!!.size)
    }

    @Test
    fun outOfRangeAndEmptyIntervalsAreNull() {
        val w = DiarizationPcmWindow(1000, 10.0)
        w.append(ByteArray(2000 * 2))
        assertNull(w.slice(1000, 1000))
        assertNull(w.slice(1500, 1000))
        assertNull(w.slice(-10, 100))
        assertNull("超出已写入范围", w.slice(1500, 2001))
        assertEquals(500, w.slice(1500, 2000)!!.size)
    }

    @Test
    fun ringWrapKeepsSampleOrder() {
        val w = DiarizationPcmWindow(1000, 1.0)            // 容量 1000 样本
        w.append(pcm(*IntArray(900) { 1 }))
        w.append(pcm(*IntArray(300) { 2 }))                // 环绕 200 个样本
        val out = w.slice(800, 1200)!!
        assertEquals(400, out.size)
        assertEquals(1 / 32768f, out[0], 1e-9f)
        assertEquals(1 / 32768f, out[99], 1e-9f)
        assertEquals(2 / 32768f, out[100], 1e-9f)
        assertEquals(2 / 32768f, out[399], 1e-9f)
    }

    @Test
    fun resetClearsPositionAndAudio() {
        val w = DiarizationPcmWindow(1000, 10.0)
        w.append(ByteArray(1000 * 2))
        w.reset()
        assertEquals(0L, w.totalSamples())
        assertNull(w.slice(0, 500))
    }
}
