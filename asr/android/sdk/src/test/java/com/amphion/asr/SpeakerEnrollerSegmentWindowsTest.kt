package com.amphion.asr

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 分段模板的切窗规则与鸿蒙 `SpeakerEnroller.enrollFileSegmentTemplates` 一致（缺陷 #97 第二轮）。 */
class SpeakerEnrollerSegmentWindowsTest {
    private val sr = 16_000
    private fun tone(seconds: Double, level: Float) = FloatArray((seconds * sr).toInt()) { if (it % 16 < 8) level else -level }

    @Test
    fun eightSecondSampleYieldsSevenTwoSecondWindowsAtOneSecondHop() {
        val windows = SpeakerEnroller.segmentTemplateWindows(tone(8.0, 0.1f), sr)
        assertEquals(7, windows.size)
        assertTrue(windows.all { it.size == 2 * sr })
    }

    @Test
    fun silentWindowsAreSkippedAndShortSamplesBecomeOneSegment() {
        val speech = tone(3.0, 0.1f)
        val silence = FloatArray(3 * sr)
        val windows = SpeakerEnroller.segmentTemplateWindows(speech + silence, sr)
        // 6 s → 5 个窗：起点 0/1/2 s 含语音，起点 3/4 s 全静音被跳过；起点 2 s 的窗只有一半语音仍过 −35 dBFS。
        assertEquals(3, windows.size)
        assertEquals(1, SpeakerEnroller.segmentTemplateWindows(tone(1.0, 0.1f), sr).size)
        assertEquals(0, SpeakerEnroller.segmentTemplateWindows(FloatArray(sr), sr).size)
        assertEquals(0, SpeakerEnroller.segmentTemplateWindows(FloatArray(0), sr).size)
    }
}
