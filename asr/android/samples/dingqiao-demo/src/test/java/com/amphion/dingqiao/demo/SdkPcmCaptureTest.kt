package com.amphion.dingqiao.demo

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SdkPcmCaptureTest {

    @Test
    fun snapshotContainsCopiesOfExactSdkFrames() {
        val capture = SdkPcmCapture(frameBytes = 4, maxFrames = 2)
        val first = byteArrayOf(1, 0, 2, 0)
        capture.capture(first)
        first[0] = 99
        capture.capture(byteArrayOf(3, 0, 4, 0))

        val snapshot = capture.snapshot()

        assertArrayEquals(byteArrayOf(1, 0, 2, 0, 3, 0, 4, 0), snapshot.pcm)
        assertEquals(2, snapshot.frameCount)
        assertFalse(snapshot.truncated)
    }

    @Test
    fun exceedingCaptureLimitMarksSnapshotTruncatedWithoutChangingSavedPcm() {
        val capture = SdkPcmCapture(frameBytes = 4, maxFrames = 1)
        capture.capture(byteArrayOf(1, 0, 2, 0))
        capture.capture(byteArrayOf(3, 0, 4, 0))

        val snapshot = capture.snapshot()

        assertArrayEquals(byteArrayOf(1, 0, 2, 0), snapshot.pcm)
        assertEquals(1, snapshot.frameCount)
        assertTrue(snapshot.truncated)
    }
}
